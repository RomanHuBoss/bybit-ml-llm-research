from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .config import settings
from .strategy_quality import APPROVED, REJECTED, RESEARCH, STALE, WATCHLIST, latest_strategy_quality, quality_summary

STATUS_ORDER = {APPROVED: 0, WATCHLIST: 1, RESEARCH: 2, REJECTED: 3, STALE: 4}


def _finite(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def _int(value: Any, default: int = 0) -> int:
    parsed = _finite(value)
    return default if parsed is None else int(parsed)


def _status(value: Any) -> str:
    text = str(value or RESEARCH).strip().upper()
    return text if text in STATUS_ORDER else RESEARCH


def _thresholds() -> dict[str, Any]:
    return {
        "min_trades": int(settings.strategy_approval_min_trades),
        "min_profit_factor": float(settings.strategy_approval_min_profit_factor),
        "max_drawdown": float(settings.strategy_approval_max_drawdown),
        "min_total_return": float(settings.strategy_approval_min_total_return),
        "walk_forward_min_pass_rate": float(getattr(settings, "strategy_walk_forward_min_pass_rate", 0.55)),
        "walk_forward_min_windows": int(getattr(settings, "strategy_walk_forward_min_windows", 3)),
    }


def _missing_reasons(row: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    reasons: list[dict[str, Any]] = []
    trades = _int(row.get("trades_count"), 0)
    pf = _finite(row.get("profit_factor"))
    dd = _finite(row.get("max_drawdown"))
    total_return = _finite(row.get("total_return"))
    wf_rate = _finite(row.get("walk_forward_pass_rate"))
    wf_windows = _int(row.get("walk_forward_windows"), 0)

    if trades < thresholds["min_trades"]:
        reasons.append({"code": "sample_size", "title": "Мало сделок", "detail": f"{trades}/{thresholds['min_trades']} сделок"})
    if pf is None:
        reasons.append({"code": "pf_missing", "title": "PF не рассчитан", "detail": "Нет достаточных прибыльных/убыточных сделок для PF"})
    elif pf < thresholds["min_profit_factor"]:
        reasons.append({"code": "profit_factor", "title": "PF ниже допуска", "detail": f"PF {pf:.2f} < {thresholds['min_profit_factor']:.2f}"})
    if dd is not None and dd > thresholds["max_drawdown"]:
        reasons.append({"code": "drawdown", "title": "Drawdown выше допуска", "detail": f"DD {dd:.2%} > {thresholds['max_drawdown']:.2%}"})
    if total_return is not None and total_return < thresholds["min_total_return"]:
        reasons.append({"code": "return", "title": "Доходность ниже допуска", "detail": f"return {total_return:.2%} < {thresholds['min_total_return']:.2%}"})
    if wf_rate is not None and wf_windows >= thresholds["walk_forward_min_windows"] and wf_rate < thresholds["walk_forward_min_pass_rate"]:
        reasons.append({"code": "walk_forward", "title": "Нестабильный walk-forward", "detail": f"WF pass {wf_rate:.0%} < {thresholds['walk_forward_min_pass_rate']:.0%}"})
    if _status(row.get("quality_status")) == REJECTED and not reasons:
        reasons.append({"code": "rejected", "title": "Стратегия отклонена", "detail": row.get("quality_reason") or "Evidence не прошёл допуск"})
    if _status(row.get("quality_status")) == STALE:
        reasons.append({"code": "stale", "title": "Evidence устарел", "detail": "Нужен повторный бэктест"})
    return reasons


def _lab_row(row: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    reasons = _missing_reasons(row, thresholds)
    status = _status(row.get("quality_status"))
    return {
        **row,
        "quality_status": status,
        "approval_blockers": reasons,
        "trading_desk_eligible": status == APPROVED,
        "near_approval": status in {WATCHLIST, RESEARCH} and len(reasons) <= 2 and _int(row.get("trades_count"), 0) >= thresholds["min_trades"] // 2,
    }


def build_strategy_lab_payload(rows: list[dict[str, Any]], summary: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = _thresholds()
    lab_rows = [_lab_row(row, thresholds) for row in rows]
    lab_rows.sort(key=lambda r: (STATUS_ORDER.get(_status(r.get("quality_status")), 9), -(_finite(r.get("quality_score"), 0) or 0), str(r.get("symbol") or "")))

    status_counts = {APPROVED: 0, WATCHLIST: 0, RESEARCH: 0, REJECTED: 0, STALE: 0}
    blocker_counts: dict[str, int] = {}
    for row in lab_rows:
        status_counts[_status(row.get("quality_status"))] = status_counts.get(_status(row.get("quality_status")), 0) + 1
        for reason in row.get("approval_blockers") or []:
            code = str(reason.get("code") or "unknown")
            blocker_counts[code] = blocker_counts.get(code, 0) + 1

    if summary is None:
        summary = {
            "total": len(lab_rows),
            "approved": status_counts[APPROVED],
            "watchlist": status_counts[WATCHLIST],
            "research": status_counts[RESEARCH],
            "rejected": status_counts[REJECTED],
            "stale": status_counts[STALE],
        }

    trading_desk = [row for row in lab_rows if row["trading_desk_eligible"]]
    near_approval = [row for row in lab_rows if row["near_approval"] and row["quality_status"] != APPROVED]
    rejected = [row for row in lab_rows if row["quality_status"] == REJECTED]

    if trading_desk:
        headline = f"Trading Desk допускает {len(trading_desk)} стратегий. Остальные остаются в Strategy Lab."
        desk_status = "HAS_APPROVED"
    else:
        headline = "Торговых рекомендаций нет: ни одна стратегия не прошла quality gate."
        desk_status = "NO_APPROVED"

    return {
        "summary": {**summary, "status_counts": status_counts},
        "thresholds": thresholds,
        "desk_status": desk_status,
        "headline": headline,
        "blocker_counts": blocker_counts,
        "trading_desk": trading_desk[:25],
        "near_approval": near_approval[:25],
        "rejected": rejected[:25],
        "items": lab_rows,
    }


def strategy_lab_snapshot(category: str = "linear", interval: str | None = None, limit: int = 200) -> dict[str, Any]:
    rows = latest_strategy_quality(category, interval, limit)
    return build_strategy_lab_payload(rows, quality_summary(category))


def strategy_lab_from_quality_export(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("quality export must contain an items list")
    summary = payload.get("summary") if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else None
    return build_strategy_lab_payload(rows, summary)


def trading_desk_diagnostics(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    by_action: dict[str, int] = {}
    by_quality: dict[str, int] = {}
    blockers: dict[str, int] = {}
    for item in items:
        action = str(item.get("operator_action") or "UNKNOWN")
        by_action[action] = by_action.get(action, 0) + 1
        quality = _status(item.get("quality_status"))
        by_quality[quality] = by_quality.get(quality, 0) + 1
        for bucket in ("operator_hard_reasons", "operator_warnings", "operator_evidence_notes"):
            for reason in item.get(bucket) or []:
                code = str(reason.get("code") or "unknown")
                blockers[code] = blockers.get(code, 0) + 1
    review = by_action.get("REVIEW_ENTRY", 0)
    return {
        "total_candidates": total,
        "review_entries": review,
        "desk_status": "HAS_REVIEW" if review else "NO_REVIEW",
        "headline": f"Trading Desk: {review} кандидатов на ручную проверку из {total}." if review else "Trading Desk пуст: все свежие сетапы остановлены quality/risk gate или отправлены в Research/Watch.",
        "by_action": by_action,
        "by_quality": by_quality,
        "blockers": blockers,
    }
