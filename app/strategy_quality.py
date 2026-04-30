from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .config import settings
from .db import execute, fetch_all, fetch_one

APPROVED = "APPROVED"
WATCHLIST = "WATCHLIST"
RESEARCH = "RESEARCH"
REJECTED = "REJECTED"
STALE = "STALE"
QUALITY_STATUSES = {APPROVED, WATCHLIST, RESEARCH, REJECTED, STALE}


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


def _normalize_status(value: Any) -> str | None:
    if value in (None, ""):
        return None
    status = str(value).strip().upper()
    return status if status in QUALITY_STATUSES else None


def evaluate_strategy_quality(metrics: dict[str, Any]) -> dict[str, Any]:
    """Classify symbol+interval+strategy quality from persisted research evidence.

    This is intentionally stricter than a single live signal. A signal can exist as a
    research candidate, but only an approved strategy-quality row may become an
    operator review setup.
    """
    trades = _int(metrics.get("trades_count"), 0)
    pf = _finite(metrics.get("profit_factor"))
    dd = _finite(metrics.get("max_drawdown"))
    total_return = _finite(metrics.get("total_return"))
    sharpe = _finite(metrics.get("sharpe"))
    win_rate = _finite(metrics.get("win_rate"))

    min_trades = int(settings.strategy_approval_min_trades)
    min_pf = float(settings.strategy_approval_min_profit_factor)
    max_dd = float(settings.strategy_approval_max_drawdown)
    min_return = float(settings.strategy_approval_min_total_return)
    watch_trades = max(10, min_trades // 2)
    watch_pf = max(1.01, min_pf - 0.10)

    diagnostics = {
        "min_trades": min_trades,
        "min_profit_factor": min_pf,
        "max_drawdown": max_dd,
        "min_total_return": min_return,
        "watch_trades": watch_trades,
        "watch_profit_factor": watch_pf,
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
    score = int(round(100 * (0.30 * sample_factor + 0.25 * pf_factor + 0.18 * dd_factor + 0.12 * return_factor + 0.10 * sharpe_factor + 0.05 * win_factor)))

    negative_enough = trades >= watch_trades and (
        (pf is not None and pf < 1.0)
        or (dd is not None and dd > max(max_dd * 1.5, max_dd + 0.12))
        or (total_return is not None and total_return < -0.05)
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
    if trades >= min_trades and pf_ok and dd_ok and ret_ok:
        return {
            "quality_status": APPROVED,
            "quality_score": max(score, 70),
            "evidence_grade": "APPROVED",
            "quality_reason": f"Стратегия допущена: сделок {trades}, PF {pf:.2f}, DD {dd:.2%}.",
            "quality_diagnostics": diagnostics,
        }

    if trades >= watch_trades and pf is not None and pf >= watch_pf and (dd is None or dd <= max(max_dd * 1.25, max_dd + 0.05)):
        return {
            "quality_status": WATCHLIST,
            "quality_score": max(score, 45),
            "evidence_grade": "WATCHLIST",
            "quality_reason": f"Стратегия в наблюдении: evidence близок к допуску, но фильтр approval еще не пройден.",
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
        return {
            "quality_status": explicit_status,
            "quality_score": _int(row.get("quality_score"), 0),
            "evidence_grade": str(row.get("evidence_grade") or explicit_status),
            "quality_reason": str(row.get("quality_reason") or "Strategy-quality row supplied by backend."),
            "quality_diagnostics": row.get("quality_diagnostics") if isinstance(row.get("quality_diagnostics"), dict) else {},
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
            diagnostics JSONB,
            UNIQUE(category, symbol, interval, strategy)
        )
        """
    )
    execute(
        """
        CREATE INDEX IF NOT EXISTS idx_strategy_quality_status
        ON strategy_quality(category, interval, quality_status, quality_score DESC, updated_at DESC)
        """
    )


def ensure_strategy_quality_storage() -> None:
    _ensure_strategy_quality_table()


def upsert_strategy_quality_from_run_id(run_id: int | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    _ensure_strategy_quality_table()
    row = fetch_one(
        """
        SELECT id AS backtest_run_id, created_at AS last_backtest_at, category, symbol, interval, strategy,
               total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count
        FROM backtest_runs
        WHERE id=%s
        """,
        (run_id,),
    )
    if not row:
        return None
    quality = evaluate_strategy_quality(row)
    execute(
        """
        INSERT INTO strategy_quality(category, symbol, interval, strategy, quality_status, quality_score, evidence_grade,
                                     quality_reason, backtest_run_id, last_backtest_at, total_return, max_drawdown,
                                     sharpe, win_rate, profit_factor, trades_count, diagnostics)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (category, symbol, interval, strategy)
        DO UPDATE SET updated_at=NOW(), quality_status=EXCLUDED.quality_status,
                      quality_score=EXCLUDED.quality_score, evidence_grade=EXCLUDED.evidence_grade,
                      quality_reason=EXCLUDED.quality_reason, backtest_run_id=EXCLUDED.backtest_run_id,
                      last_backtest_at=EXCLUDED.last_backtest_at, total_return=EXCLUDED.total_return,
                      max_drawdown=EXCLUDED.max_drawdown, sharpe=EXCLUDED.sharpe,
                      win_rate=EXCLUDED.win_rate, profit_factor=EXCLUDED.profit_factor,
                      trades_count=EXCLUDED.trades_count, diagnostics=EXCLUDED.diagnostics
        """,
        (
            row["category"],
            row["symbol"],
            row["interval"],
            row["strategy"],
            quality["quality_status"],
            quality["quality_score"],
            quality["evidence_grade"],
            quality["quality_reason"],
            row["backtest_run_id"],
            row["last_backtest_at"],
            row.get("total_return"),
            row.get("max_drawdown"),
            row.get("sharpe"),
            row.get("win_rate"),
            row.get("profit_factor"),
            row.get("trades_count") or 0,
            quality["quality_diagnostics"],
        ),
    )
    return {**row, **quality}


def refresh_strategy_quality(limit: int = 500) -> dict[str, Any]:
    _ensure_strategy_quality_table()
    rows = fetch_all(
        """
        SELECT DISTINCT ON (category, symbol, interval, strategy)
               id AS backtest_run_id, created_at AS last_backtest_at, category, symbol, interval, strategy,
               total_return, max_drawdown, sharpe, win_rate, profit_factor, trades_count
        FROM backtest_runs
        ORDER BY category, symbol, interval, strategy, created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    updated = 0
    statuses: dict[str, int] = {APPROVED: 0, WATCHLIST: 0, RESEARCH: 0, REJECTED: 0, STALE: 0}
    for row in rows:
        quality = upsert_strategy_quality_from_run_id(int(row["backtest_run_id"]))
        if quality:
            updated += 1
            statuses[quality["quality_status"]] = statuses.get(quality["quality_status"], 0) + 1
    return {"updated": updated, "statuses": statuses}


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
               COUNT(*) FILTER (WHERE quality_status='WATCHLIST') AS watchlist,
               COUNT(*) FILTER (WHERE quality_status='RESEARCH') AS research,
               COUNT(*) FILTER (WHERE quality_status='REJECTED') AS rejected,
               MAX(updated_at) AS last_updated_at
        FROM strategy_quality
        WHERE category=%s
        """,
        (category,),
    )
    return row or {"total": 0, "approved": 0, "watchlist": 0, "research": 0, "rejected": 0, "last_updated_at": None}
