from __future__ import annotations

import math
import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import settings
from .db import execute, fetch_all, fetch_one

APPROVED = "APPROVED"
WATCHLIST = "WATCHLIST"
RESEARCH = "RESEARCH"
REJECTED = "REJECTED"
STALE = "STALE"
QUALITY_STATUSES = {APPROVED, WATCHLIST, RESEARCH, REJECTED, STALE}
SAME_BAR_STOP_FIRST_REASON = "stop_loss_same_bar_ambiguous"
MAX_AMBIGUOUS_EXIT_RATE_FOR_APPROVAL = 0.20


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _int(value: Any, default: int = 0) -> int:
    parsed = _finite(value)
    if parsed is None:
        return default
    return int(parsed)


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_stale_backtest(value: Any, *, now: datetime | None = None) -> bool:
    parsed = _parse_dt(value)
    if parsed is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    max_age_days = max(1, int(_safe_setting("strategy_quality_max_age_days", 14)))
    return now - parsed > timedelta(days=max_age_days)


def _normalize_status(value: Any) -> str | None:
    if value in (None, ""):
        return None
    status = str(value).strip().upper()
    return status if status in QUALITY_STATUSES else None


def _safe_setting(name: str, default: Any) -> Any:
    return getattr(settings, name, default)


def _quality_thresholds() -> dict[str, Any]:
    min_trades = int(settings.strategy_approval_min_trades)
    min_pf = float(settings.strategy_approval_min_profit_factor)
    max_dd = float(settings.strategy_approval_max_drawdown)
    min_return = float(settings.strategy_approval_min_total_return)
    return {
        "min_trades": min_trades,
        "min_profit_factor": min_pf,
        "max_drawdown": max_dd,
        "min_total_return": min_return,
        "watch_trades": max(10, min_trades // 2),
        "watch_profit_factor": max(1.01, min_pf - 0.10),
        "walk_forward_min_pass_rate": float(_safe_setting("strategy_walk_forward_min_pass_rate", 0.55)),
        "walk_forward_min_windows": int(_safe_setting("strategy_walk_forward_min_windows", 3)),
        "require_walk_forward_for_approval": bool(_safe_setting("require_walk_forward_for_approval", True)),
        "quality_max_age_days": int(_safe_setting("strategy_quality_max_age_days", 14)),
        "min_expectancy": float(_safe_setting("strategy_min_expectancy", 0.0)),
        "min_recent_30d_return": float(_safe_setting("strategy_min_recent_30d_return", -0.03)),
    }


def evaluate_strategy_quality(metrics: dict[str, Any]) -> dict[str, Any]:
    """Classify symbol+interval+strategy quality from persisted research evidence.

    A signal can exist as a research candidate, but only an approved strategy-quality
    row may become an operator review setup. Walk-forward stability is considered
    when available; old rows without those metrics are still evaluated by legacy
    backtest evidence so production upgrades do not wipe existing approvals.
    """
    trades = _int(metrics.get("trades_count"), 0)
    pf = _finite(metrics.get("profit_factor"))
    dd = _finite(metrics.get("max_drawdown"))
    total_return = _finite(metrics.get("total_return"))
    sharpe = _finite(metrics.get("sharpe"))
    win_rate = _finite(metrics.get("win_rate"))
    expectancy = _finite(metrics.get("expectancy"))
    wf_rate = _finite(metrics.get("walk_forward_pass_rate"))
    wf_windows = _int(metrics.get("walk_forward_windows"), 0)
    last_backtest_at = metrics.get("last_backtest_at") or metrics.get("created_at")
    last_30d_return = _finite(metrics.get("last_30d_return"))
    ambiguous_exit_count = _int(metrics.get("ambiguous_exit_count"), 0)
    ambiguous_exit_rate = _finite(metrics.get("ambiguous_exit_rate"), 0.0) or 0.0

    thresholds = _quality_thresholds()
    min_trades = int(thresholds["min_trades"])
    min_pf = float(thresholds["min_profit_factor"])
    max_dd = float(thresholds["max_drawdown"])
    min_return = float(thresholds["min_total_return"])
    watch_trades = int(thresholds["watch_trades"])
    watch_pf = float(thresholds["watch_profit_factor"])
    wf_min_rate = float(thresholds["walk_forward_min_pass_rate"])
    wf_min_windows = int(thresholds["walk_forward_min_windows"])
    require_wf = bool(thresholds["require_walk_forward_for_approval"])
    min_expectancy = float(thresholds["min_expectancy"])
    min_recent_30d_return = float(thresholds["min_recent_30d_return"])

    diagnostics = dict(thresholds)
    diagnostics.update({
        "ambiguous_exit_count": ambiguous_exit_count,
        "ambiguous_exit_rate": ambiguous_exit_rate,
        "max_ambiguous_exit_rate_for_approval": MAX_AMBIGUOUS_EXIT_RATE_FOR_APPROVAL,
        "exit_reason_counts": metrics.get("exit_reason_counts") if isinstance(metrics.get("exit_reason_counts"), dict) else {},
    })

    if _is_stale_backtest(last_backtest_at):
        return {
            "quality_status": STALE,
            "quality_score": 0,
            "evidence_grade": "STALE_BACKTEST",
            "quality_reason": f"Бэктест старше {diagnostics['quality_max_age_days']} дн.; нужна актуализация evidence перед любой ручной проверкой входа.",
            "quality_diagnostics": diagnostics,
        }

    if trades <= 0:
        return {
            "quality_status": RESEARCH,
            "quality_score": 0,
            "evidence_grade": "NO_BACKTEST",
            "quality_reason": "Бэктест отсутствует; сетап может быть только исследовательским кандидатом.",
            "quality_diagnostics": diagnostics,
        }

    sample_factor = max(0.0, min(1.0, trades / max(min_trades, 1)))
    pf_factor = 0.0 if pf is None else max(0.0, min(1.0, pf / max(min_pf, 1e-9)))
    dd_factor = 0.5 if dd is None else max(0.0, min(1.0, 1.0 - dd / max(max_dd * 1.5, 1e-9)))
    return_factor = 0.0 if total_return is None else max(0.0, min(1.0, (total_return - min_return + 0.10) / 0.35))
    sharpe_factor = 0.5 if sharpe is None else max(0.0, min(1.0, (sharpe + 0.25) / 1.75))
    win_factor = 0.5 if win_rate is None else max(0.0, min(1.0, win_rate / 0.58))
    expectancy_factor = 0.5 if expectancy is None else max(0.0, min(1.0, (expectancy + 0.005) / 0.03))
    wf_factor = 0.5 if wf_rate is None or wf_windows < wf_min_windows else max(0.0, min(1.0, wf_rate / max(wf_min_rate, 1e-9)))
    score = int(round(100 * (
        0.24 * sample_factor
        + 0.22 * pf_factor
        + 0.16 * dd_factor
        + 0.11 * return_factor
        + 0.09 * sharpe_factor
        + 0.05 * win_factor
        + 0.05 * expectancy_factor
        + 0.08 * wf_factor
    )))
    if ambiguous_exit_count > 0:
        # Большая доля same-bar SL/TP означает, что OHLC-таймфрейм слишком грубый
        # для уверенного quality approval: результат зависит от неизвестного
        # порядка тиков внутри свечи. Не отбрасываем стратегию автоматически, но
        # снижаем score и не даём ей стать APPROVED при чрезмерной неоднозначности.
        score = max(0, score - int(round(min(30.0, ambiguous_exit_rate * 100.0))))

    intrabar_uncertainty = ambiguous_exit_count >= 3 and ambiguous_exit_rate > MAX_AMBIGUOUS_EXIT_RATE_FOR_APPROVAL

    negative_enough = trades >= watch_trades and (
        (pf is not None and pf < 1.0)
        or (dd is not None and dd > max(max_dd * 1.5, max_dd + 0.12))
        or (total_return is not None and total_return < -0.05)
        or (expectancy is not None and expectancy < min_expectancy and trades >= min_trades)
        or (last_30d_return is not None and last_30d_return < min_recent_30d_return)
        or (wf_rate is not None and wf_windows >= wf_min_windows and wf_rate <= max(0.25, wf_min_rate - 0.25))
    )
    if negative_enough:
        return {
            "quality_status": REJECTED,
            "quality_score": min(score, 35),
            "evidence_grade": "FAILED",
            "quality_reason": f"Стратегия отклонена: сделок {trades}, PF {pf if pf is not None else '—'}, DD {dd if dd is not None else '—'}.",
            "quality_diagnostics": diagnostics,
        }

    pf_ok = pf is not None and pf >= min_pf
    dd_ok = dd is not None and dd <= max_dd
    ret_ok = total_return is None or total_return >= min_return
    wf_available = wf_rate is not None and wf_windows >= wf_min_windows
    wf_ok = (not require_wf and not wf_available) or (wf_available and wf_rate >= wf_min_rate)
    expectancy_ok = expectancy is None or expectancy >= min_expectancy
    recent_ok = last_30d_return is None or last_30d_return >= min_recent_30d_return
    if trades >= min_trades and pf_ok and dd_ok and ret_ok and wf_ok and expectancy_ok and recent_ok and not intrabar_uncertainty:
        wf_tail = "" if wf_rate is None else f", WF {wf_rate:.0%}"
        return {
            "quality_status": APPROVED,
            "quality_score": max(score, 70),
            "evidence_grade": "APPROVED",
            "quality_reason": f"Стратегия допущена: сделок {trades}, PF {pf:.2f}, DD {dd:.2%}{wf_tail}.",
            "quality_diagnostics": diagnostics,
        }

    if intrabar_uncertainty:
        return {
            "quality_status": WATCHLIST if trades >= watch_trades else RESEARCH,
            "quality_score": min(max(score, 35), 60),
            "evidence_grade": "INTRABAR_UNCERTAINTY",
            "quality_reason": f"Стратегия требует проверки на меньшем таймфрейме: {ambiguous_exit_count} из {trades} сделок ({ambiguous_exit_rate:.1%}) имели одновременный SL/TP внутри одной свечи и засчитаны как SL-first.",
            "quality_diagnostics": diagnostics,
        }

    if trades >= watch_trades and pf is not None and pf >= watch_pf and (dd is None or dd <= max(max_dd * 1.25, max_dd + 0.05)):
        wf_note = " Требуется walk-forward evidence для допуска REVIEW_ENTRY." if require_wf and not wf_available else ""
        return {
            "quality_status": WATCHLIST,
            "quality_score": max(score, 45),
            "evidence_grade": "WF_PENDING" if require_wf and not wf_available else "WATCHLIST",
            "quality_reason": f"Стратегия в наблюдении: evidence близок к допуску, но фильтр approval еще не пройден.{wf_note}",
            "quality_diagnostics": diagnostics,
        }

    return {
        "quality_status": RESEARCH,
        "quality_score": min(score, 55),
        "evidence_grade": "INSUFFICIENT",
        "quality_reason": f"Недостаточная статистика стратегии: сделок {trades}; требуется минимум {min_trades} и PF >= {min_pf:.2f}.",
        "quality_diagnostics": diagnostics,
    }


def effective_strategy_quality(row: dict[str, Any]) -> dict[str, Any]:
    explicit_status = _normalize_status(row.get("quality_status"))
    if explicit_status:
        evaluated = evaluate_strategy_quality(row)
        if evaluated.get("quality_status") in {STALE, REJECTED}:
            return evaluated
        if explicit_status == APPROVED and evaluated.get("quality_status") != APPROVED:
            # Защита от устаревших/legacy строк: сохраненный APPROVED не должен обходить
            # новые 2026-gate требования к walk-forward, свежести и expectancy.
            return evaluated
        return {
            "quality_status": explicit_status,
            "quality_score": _int(row.get("quality_score"), 0),
            "evidence_grade": str(row.get("evidence_grade") or explicit_status),
            "quality_reason": str(row.get("quality_reason") or "Strategy-quality row supplied by backend."),
            "quality_diagnostics": row.get("quality_diagnostics") if isinstance(row.get("quality_diagnostics"), dict) else row.get("diagnostics") if isinstance(row.get("diagnostics"), dict) else {},
        }
    return evaluate_strategy_quality(row)


def is_strategy_approved(row: dict[str, Any]) -> bool:
    if not settings.require_strategy_approval_for_review:
        return True
    return effective_strategy_quality(row)["quality_status"] == APPROVED


def _ensure_strategy_quality_table() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS strategy_quality (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            category TEXT NOT NULL,
            symbol TEXT NOT NULL,
            interval TEXT NOT NULL,
            strategy TEXT NOT NULL,
            quality_status TEXT NOT NULL CHECK (quality_status IN ('APPROVED','WATCHLIST','RESEARCH','REJECTED','STALE')),
            quality_score NUMERIC NOT NULL DEFAULT 0,
            evidence_grade TEXT NOT NULL DEFAULT 'INSUFFICIENT',
            quality_reason TEXT,
            backtest_run_id BIGINT,
            last_backtest_at TIMESTAMPTZ,
            total_return NUMERIC,
            max_drawdown NUMERIC,
            sharpe NUMERIC,
            win_rate NUMERIC,
            profit_factor NUMERIC,
            trades_count INTEGER NOT NULL DEFAULT 0,
            expectancy NUMERIC,
            avg_trade_pnl NUMERIC,
            median_trade_pnl NUMERIC,
            last_30d_return NUMERIC,
            last_90d_return NUMERIC,
            walk_forward_pass_rate NUMERIC,
            walk_forward_windows INTEGER,
            walk_forward_summary JSONB,
            diagnostics JSONB,
            UNIQUE(category, symbol, interval, strategy)
        )
        """
    )
    for ddl in (
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS expectancy NUMERIC",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS avg_trade_pnl NUMERIC",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS median_trade_pnl NUMERIC",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS last_30d_return NUMERIC",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS last_90d_return NUMERIC",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS walk_forward_pass_rate NUMERIC",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS walk_forward_windows INTEGER",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS walk_forward_summary JSONB",
        "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS diagnostics JSONB",
    ):
        execute(ddl)
    execute(
        """
        DELETE FROM strategy_quality a
        USING strategy_quality b
        WHERE a.category=b.category
          AND a.symbol=b.symbol
          AND a.interval=b.interval
          AND a.strategy=b.strategy
          AND a.ctid < b.ctid
        """
    )
    execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_quality_key
        ON strategy_quality(category, symbol, interval, strategy)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_strategy_quality_status
        ON strategy_quality(category, interval, quality_status, quality_score DESC, updated_at DESC)
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_strategy_quality_symbol
        ON strategy_quality(category, symbol, interval, strategy, updated_at DESC)
        """
    )


def ensure_strategy_quality_storage() -> None:
    _ensure_strategy_quality_table()


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _windowed_trade_metrics(trades: list[dict[str, Any]], windows: int = 6) -> dict[str, Any]:
    if not trades:
        return {
            "expectancy": None,
            "avg_trade_pnl": None,
            "median_trade_pnl": None,
            "walk_forward_pass_rate": None,
            "walk_forward_windows": 0,
            "walk_forward_summary": [],
            "exit_reason_counts": {},
            "ambiguous_exit_count": 0,
            "ambiguous_exit_rate": 0.0,
        }
    ordered = sorted(trades, key=lambda t: _parse_time(t.get("exit_time")) or datetime.min.replace(tzinfo=timezone.utc))
    reason_counts: dict[str, int] = {}
    for trade in ordered:
        reason = str(trade.get("reason") or "unknown")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    ambiguous_exit_count = sum(
        count for reason, count in reason_counts.items()
        if reason == SAME_BAR_STOP_FIRST_REASON or "same_bar" in reason or "ambiguous" in reason
    )
    ambiguous_exit_rate = ambiguous_exit_count / len(ordered) if ordered else 0.0
    pnls = [_finite(t.get("pnl"), 0.0) or 0.0 for t in ordered]
    avg = statistics.fmean(pnls) if pnls else None
    median = statistics.median(pnls) if pnls else None
    losses = [abs(x) for x in pnls if x < 0]
    avg_loss = statistics.fmean(losses) if losses else None
    expectancy = None
    if avg is not None and avg_loss and avg_loss > 0:
        expectancy = avg / avg_loss

    window_count = max(1, min(int(windows), len(ordered)))
    chunk_size = max(1, math.ceil(len(ordered) / window_count))
    chunks: list[dict[str, Any]] = []
    passed = 0
    for idx in range(0, len(ordered), chunk_size):
        chunk = ordered[idx : idx + chunk_size]
        chunk_pnls = [_finite(t.get("pnl"), 0.0) or 0.0 for t in chunk]
        wins = [p for p in chunk_pnls if p > 0]
        losses_abs = abs(sum(p for p in chunk_pnls if p <= 0))
        gross_profit = sum(wins)
        pf = gross_profit / losses_abs if losses_abs > 0 else (None if gross_profit <= 0 else 99.0)
        pnl_sum = sum(chunk_pnls)
        win_rate = len(wins) / len(chunk_pnls) if chunk_pnls else None
        ok = pnl_sum > 0 and (pf is None or pf >= 1.0)
        passed += 1 if ok else 0
        chunks.append(
            {
                "window": len(chunks) + 1,
                "trades": len(chunk),
                "pnl": round(pnl_sum, 8),
                "profit_factor": None if pf is None else round(min(pf, 99.0), 6),
                "win_rate": win_rate,
                "passed": ok,
            }
        )
    pass_rate = passed / len(chunks) if chunks else None
    return {
        "expectancy": expectancy,
        "avg_trade_pnl": avg,
        "median_trade_pnl": median,
        "walk_forward_pass_rate": pass_rate,
        "walk_forward_windows": len(chunks),
        "walk_forward_summary": chunks,
        "exit_reason_counts": reason_counts,
        "ambiguous_exit_count": ambiguous_exit_count,
        "ambiguous_exit_rate": ambiguous_exit_rate,
    }


def _recent_equity_return(equity_curve: list[dict[str, Any]], days: int) -> float | None:
    if not equity_curve:
        return None
    parsed: list[tuple[datetime, float]] = []
    for point in equity_curve:
        ts = _parse_time(point.get("time"))
        equity = _finite(point.get("equity"))
        if ts is not None and equity is not None and equity > 0:
            parsed.append((ts, equity))
    if len(parsed) < 2:
        return None
    parsed.sort(key=lambda pair: pair[0])
    end_time, end_equity = parsed[-1]
    threshold = end_time.timestamp() - days * 86400
    start = next(((ts, eq) for ts, eq in parsed if ts.timestamp() >= threshold), parsed[0])
    if start[1] <= 0:
        return None
    return end_equity / start[1] - 1


def derive_backtest_run_metrics(run_id: int | None, run_row: dict[str, Any] | None = None) -> dict[str, Any]:
    if not run_id:
        return {}
    trades = fetch_all(
        """
        SELECT entry_time, exit_time, pnl, pnl_pct, reason
        FROM backtest_trades
        WHERE run_id=%s
        ORDER BY exit_time
        """,
        (run_id,),
    )
    metrics = _windowed_trade_metrics(trades, int(_safe_setting("strategy_walk_forward_windows", 6)))
    equity_curve = None
    if run_row and isinstance(run_row.get("equity_curve"), list):
        equity_curve = run_row.get("equity_curve")
    if equity_curve is None:
        row = fetch_one("SELECT equity_curve FROM backtest_runs WHERE id=%s", (run_id,))
        equity_curve = row.get("equity_curve") if row else None
    if isinstance(equity_curve, list):
        metrics["last_30d_return"] = _recent_equity_return(equity_curve, 30)
        metrics["last_90d_return"] = _recent_equity_return(equity_curve, 90)
    else:
        metrics["last_30d_return"] = None
        metrics["last_90d_return"] = None
    params = run_row.get("params") if isinstance(run_row, dict) else None
    if isinstance(params, dict):
        if not metrics.get("exit_reason_counts") and isinstance(params.get("exit_reason_counts"), dict):
            metrics["exit_reason_counts"] = params.get("exit_reason_counts")
        if not metrics.get("ambiguous_exit_count") and params.get("ambiguous_exit_count") is not None:
            metrics["ambiguous_exit_count"] = _int(params.get("ambiguous_exit_count"), 0)
        if (metrics.get("ambiguous_exit_rate") in (None, 0.0)) and params.get("ambiguous_exit_rate") is not None:
            metrics["ambiguous_exit_rate"] = _finite(params.get("ambiguous_exit_rate"), 0.0) or 0.0
    return metrics


def upsert_strategy_quality_from_run(row: dict[str, Any]) -> dict[str, Any] | None:
    """Пересчитывает и сохраняет quality row для уже выбранного backtest_run.

    В refresh-цикле это устраняет лишний SELECT backtest_runs на каждую стратегию.
    Тяжелая часть — чтение сделок для walk-forward — остается, но теперь она
    ограничивается внешним time budget и не блокирует UI HTTP-запрос.
    """
    run_id = int(row.get("backtest_run_id") or row.get("id") or 0)
    if not run_id:
        return None
    normalized = dict(row)
    normalized["backtest_run_id"] = run_id
    derived = derive_backtest_run_metrics(run_id, normalized)
    quality_input = {**normalized, **derived}
    quality = evaluate_strategy_quality(quality_input)
    execute(
        """
        INSERT INTO strategy_quality(category, symbol, interval, strategy, quality_status, quality_score, evidence_grade,
                                     quality_reason, backtest_run_id, last_backtest_at, total_return, max_drawdown,
                                     sharpe, win_rate, profit_factor, trades_count, expectancy, avg_trade_pnl,
                                     median_trade_pnl, last_30d_return, last_90d_return, walk_forward_pass_rate,
                                     walk_forward_windows, walk_forward_summary, diagnostics)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (category, symbol, interval, strategy)
        DO UPDATE SET updated_at=NOW(), quality_status=EXCLUDED.quality_status,
                      quality_score=EXCLUDED.quality_score, evidence_grade=EXCLUDED.evidence_grade,
                      quality_reason=EXCLUDED.quality_reason, backtest_run_id=EXCLUDED.backtest_run_id,
                      last_backtest_at=EXCLUDED.last_backtest_at, total_return=EXCLUDED.total_return,
                      max_drawdown=EXCLUDED.max_drawdown, sharpe=EXCLUDED.sharpe,
                      win_rate=EXCLUDED.win_rate, profit_factor=EXCLUDED.profit_factor,
                      trades_count=EXCLUDED.trades_count, expectancy=EXCLUDED.expectancy,
                      avg_trade_pnl=EXCLUDED.avg_trade_pnl, median_trade_pnl=EXCLUDED.median_trade_pnl,
                      last_30d_return=EXCLUDED.last_30d_return, last_90d_return=EXCLUDED.last_90d_return,
                      walk_forward_pass_rate=EXCLUDED.walk_forward_pass_rate,
                      walk_forward_windows=EXCLUDED.walk_forward_windows,
                      walk_forward_summary=EXCLUDED.walk_forward_summary,
                      diagnostics=EXCLUDED.diagnostics
        """,
        (
            normalized["category"],
            normalized["symbol"],
            normalized["interval"],
            normalized["strategy"],
            quality["quality_status"],
            quality["quality_score"],
            quality["evidence_grade"],
            quality["quality_reason"],
            normalized["backtest_run_id"],
            normalized.get("last_backtest_at"),
            normalized.get("total_return"),
            normalized.get("max_drawdown"),
            normalized.get("sharpe"),
            normalized.get("win_rate"),
            normalized.get("profit_factor"),
            normalized.get("trades_count") or 0,
            derived.get("expectancy"),
            derived.get("avg_trade_pnl"),
            derived.get("median_trade_pnl"),
            derived.get("last_30d_return"),
            derived.get("last_90d_return"),
            derived.get("walk_forward_pass_rate"),
            derived.get("walk_forward_windows"),
            derived.get("walk_forward_summary"),
            quality["quality_diagnostics"],
        ),
    )
    returned = {k: v for k, v in normalized.items() if k != "equity_curve"}
    return {**returned, **derived, **quality}


def upsert_strategy_quality_from_run_id(run_id: int | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    _ensure_strategy_quality_table()
    row = fetch_one(
        """
        SELECT id AS backtest_run_id, created_at AS last_backtest_at, category, symbol, interval, strategy,
               total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, equity_curve, params
        FROM backtest_runs
        WHERE id=%s
        """,
        (run_id,),
    )
    if not row:
        return None
    return upsert_strategy_quality_from_run(row)


def refresh_strategy_quality(limit: int = 500, time_budget_sec: float | None = None) -> dict[str, Any]:
    """Пересчитывает strategy_quality ограниченной пачкой и с soft time-budget.

    Раньше UI дергал этот расчет синхронно на 500 стратегий, что легко превышало
    45 секунд: на каждую стратегию читались сделки, equity curve и выполнялся upsert.
    Теперь функция умеет честно вернуть partial=True, а HTTP endpoint запускает ее в фоне.
    """
    started = time.monotonic()
    _ensure_strategy_quality_table()
    rows = fetch_all(
        """
        SELECT DISTINCT ON (category, symbol, interval, strategy)
               id AS backtest_run_id, created_at AS last_backtest_at, category, symbol, interval, strategy,
               total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count, equity_curve, params
        FROM backtest_runs
        ORDER BY category, symbol, interval, strategy, created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    updated = 0
    failed = 0
    partial = False
    errors: list[dict[str, Any]] = []
    statuses: dict[str, int] = {APPROVED: 0, WATCHLIST: 0, RESEARCH: 0, REJECTED: 0, STALE: 0}
    for index, row in enumerate(rows):
        elapsed = time.monotonic() - started
        if time_budget_sec is not None and elapsed >= max(0.0, float(time_budget_sec)):
            partial = True
            break
        try:
            quality = upsert_strategy_quality_from_run(row)
        except Exception as exc:
            failed += 1
            if len(errors) < 10:
                errors.append(
                    {
                        "backtest_run_id": row.get("backtest_run_id"),
                        "symbol": row.get("symbol"),
                        "interval": row.get("interval"),
                        "strategy": row.get("strategy"),
                        "error": str(exc)[:500],
                    }
                )
            continue
        if quality:
            updated += 1
            statuses[quality["quality_status"]] = statuses.get(quality["quality_status"], 0) + 1
    scanned = updated + failed
    return {
        "updated": updated,
        "failed": failed,
        "scanned": scanned,
        "available": len(rows),
        "limit": limit,
        "partial": partial,
        "duration_sec": round(time.monotonic() - started, 3),
        "time_budget_sec": time_budget_sec,
        "statuses": statuses,
        "errors": errors,
    }


def latest_strategy_quality(category: str = "linear", interval: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    _ensure_strategy_quality_table()
    if interval:
        return fetch_all(
            """
            SELECT * FROM strategy_quality
            WHERE category=%s AND interval=%s
            ORDER BY quality_score DESC, updated_at DESC
            LIMIT %s
            """,
            (category, interval, limit),
        )
    return fetch_all(
        """
        SELECT * FROM strategy_quality
        WHERE category=%s
        ORDER BY quality_score DESC, updated_at DESC
        LIMIT %s
        """,
        (category, limit),
    )


def quality_summary(category: str = "linear") -> dict[str, Any]:
    _ensure_strategy_quality_table()
    row = fetch_one(
        """
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE quality_status='APPROVED') AS approved,
               COUNT(*) FILTER (WHERE interval=%s AND quality_status='APPROVED') AS entry_interval_approved,
               COUNT(*) FILTER (WHERE interval<>%s AND quality_status='APPROVED') AS context_interval_approved,
               COUNT(*) FILTER (WHERE quality_status='WATCHLIST') AS watchlist,
               COUNT(*) FILTER (WHERE quality_status='RESEARCH') AS research,
               COUNT(*) FILTER (WHERE quality_status='REJECTED') AS rejected,
               COUNT(*) FILTER (WHERE quality_status='STALE') AS stale,
               MAX(updated_at) AS last_updated_at,
               AVG(quality_score) AS avg_quality_score,
               AVG(profit_factor) AS avg_profit_factor,
               AVG(walk_forward_pass_rate) AS avg_walk_forward_pass_rate
        FROM strategy_quality
        WHERE category=%s
        """,
        (str(settings.mtf_entry_interval).strip().upper(), str(settings.mtf_entry_interval).strip().upper(), category),
    )
    return row or {
        "total": 0,
        "approved": 0,
        "entry_interval_approved": 0,
        "context_interval_approved": 0,
        "watchlist": 0,
        "research": 0,
        "rejected": 0,
        "stale": 0,
        "last_updated_at": None,
        "avg_quality_score": None,
        "avg_profit_factor": None,
        "avg_walk_forward_pass_rate": None,
    }
