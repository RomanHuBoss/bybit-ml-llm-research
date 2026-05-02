from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import settings

DIRECTION_LONG = "long"
DIRECTION_SHORT = "short"
DIRECTION_NO_TRADE = "no_trade"
REVIEW_ACTIONS = {"REVIEW_ENTRY"}
NON_ENTRY_ACTIONS = {"NO_TRADE", "WAIT"}


def finite(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def clamp(value: Any, low: float = 0.0, high: float = 1.0, default: float = 0.0) -> float:
    parsed = finite(value, default)
    if parsed is None:
        parsed = default
    return max(low, min(high, parsed))


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def interval_to_timedelta(interval: str | None) -> timedelta:
    value = str(interval or "").strip().upper()
    if value.isdigit():
        return timedelta(minutes=int(value))
    if value == "D":
        return timedelta(days=1)
    if value == "W":
        return timedelta(days=7)
    if value == "M":
        return timedelta(days=31)
    return timedelta(hours=1)


def recommendation_expires_at(row: dict[str, Any], *, now: datetime | None = None) -> datetime | None:
    explicit = parse_datetime((row.get("rationale") or {}).get("expires_at") if isinstance(row.get("rationale"), dict) else None)
    if explicit is not None:
        return explicit
    bar_time = parse_datetime(row.get("bar_time") or row.get("created_at"))
    if bar_time is None:
        return None
    return bar_time + interval_to_timedelta(str(row.get("interval") or "")) + timedelta(hours=max(1, int(settings.max_signal_age_hours)))


def validate_trade_levels(direction: str | None, entry: Any, stop_loss: Any, take_profit: Any) -> dict[str, Any]:
    direction = str(direction or "").strip().lower()
    entry_f = finite(entry)
    stop_f = finite(stop_loss)
    take_f = finite(take_profit)
    base = {
        "valid": False,
        "direction": direction,
        "entry": entry_f,
        "stop_loss": stop_f,
        "take_profit": take_f,
        "risk_pct": None,
        "expected_reward_pct": None,
        "risk_reward": None,
        "reason": None,
    }
    if direction not in {DIRECTION_LONG, DIRECTION_SHORT}:
        return {**base, "reason": "invalid_direction"}
    if entry_f is None or stop_f is None or take_f is None:
        return {**base, "reason": "missing_levels"}
    if entry_f <= 0 or stop_f <= 0 or take_f <= 0:
        return {**base, "reason": "non_positive_levels"}
    if direction == DIRECTION_LONG and not (stop_f < entry_f < take_f):
        return {**base, "reason": "long_levels_not_ordered"}
    if direction == DIRECTION_SHORT and not (take_f < entry_f < stop_f):
        return {**base, "reason": "short_levels_not_ordered"}
    risk = abs(entry_f - stop_f)
    reward = abs(take_f - entry_f)
    if risk <= 0 or reward <= 0:
        return {**base, "reason": "zero_risk_or_reward"}
    rr = reward / risk
    if not math.isfinite(rr) or rr <= 0:
        return {**base, "reason": "invalid_risk_reward"}
    return {
        **base,
        "valid": True,
        "risk_pct": risk / entry_f,
        "expected_reward_pct": reward / entry_f,
        "risk_reward": rr,
        "reason": None,
    }


def price_freshness(row: dict[str, Any], expires_at: datetime | None, levels: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if expires_at is not None and expires_at < now:
        stale = True
    else:
        stale = str(row.get("data_status") or row.get("freshness_status") or "").lower() in {"stale", "expired"} or row.get("fresh") is False

    entry = finite(levels.get("entry"))
    last_price = finite(row.get("last_price"), finite(row.get("current_price"), finite(row.get("close"))))
    atr = finite(row.get("atr"))
    entry_zone_pct = 0.0025
    if entry and atr and atr > 0:
        entry_zone_pct = max(0.0015, min(0.018, (atr / entry) * 0.35))
    drift_pct = abs(last_price - entry) / entry if entry and last_price else None
    if stale:
        status = "stale"
    elif drift_pct is None:
        status = "unknown"
    elif drift_pct <= entry_zone_pct:
        status = "entry_zone"
    elif drift_pct <= entry_zone_pct * 2.0:
        status = "extended"
    else:
        status = "moved_away"
    return {
        "last_price": last_price,
        "last_price_time": row.get("last_price_time") or row.get("bar_time"),
        "price_status": status,
        "price_drift_pct": drift_pct,
        "entry_zone_pct": entry_zone_pct,
        "is_stale": stale,
    }


def invalidation_condition(direction: str, levels: dict[str, Any], expires_at: datetime | None) -> str:
    entry = levels.get("entry")
    stop = levels.get("stop_loss")
    target = levels.get("take_profit")
    ttl = to_iso(expires_at) or "срок актуальности неизвестен"
    if direction == DIRECTION_LONG:
        return f"LONG отменяется при цене <= {stop:.8g}, уходе далеко выше entry без ретеста или после {ttl}. Цель сценария: {target:.8g}."
    if direction == DIRECTION_SHORT:
        return f"SHORT отменяется при цене >= {stop:.8g}, уходе далеко ниже entry без ретеста или после {ttl}. Цель сценария: {target:.8g}."
    return f"Вход запрещён до появления валидного направления, свежей цены, SL/TP и срока актуальности; текущий TTL: {ttl}."


def _reason_text(items: Any, fallback: str) -> str:
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            return str(first.get("detail") or first.get("title") or fallback)
        return str(first)
    return fallback


def recommendation_status(row: dict[str, Any], levels: dict[str, Any], price: dict[str, Any]) -> str:
    action = str(row.get("operator_action") or "WAIT").upper()
    if not levels.get("valid"):
        return "invalid"
    if price.get("is_stale"):
        return "expired"
    if action == "NO_TRADE":
        return "blocked"
    if action == "REVIEW_ENTRY":
        return "review_entry"
    if action == "RESEARCH_CANDIDATE":
        return "research_candidate"
    return "wait"


def user_trade_direction(row: dict[str, Any], status: str) -> str:
    raw = str(row.get("direction") or "").strip().lower()
    if status in {"review_entry", "research_candidate"} and raw in {DIRECTION_LONG, DIRECTION_SHORT}:
        return raw
    return DIRECTION_NO_TRADE


def explanation(row: dict[str, Any], status: str, trade_direction: str, levels: dict[str, Any], price: dict[str, Any]) -> str:
    symbol = row.get("symbol") or "инструмент"
    interval = row.get("interval") or "TF"
    strategy = row.get("strategy") or "стратегия"
    confidence = clamp(row.get("confidence"))
    rr = levels.get("risk_reward")
    hard = row.get("operator_hard_reasons") or []
    warnings = row.get("operator_warnings") or []
    evidence = row.get("operator_evidence_notes") or []
    quality = str(row.get("quality_status") or "RESEARCH").upper()
    price_status = price.get("price_status")

    if status == "invalid":
        return f"{symbol}: вход запрещён, потому что торговые уровни невалидны ({levels.get('reason')}). Система не должна показывать LONG/SHORT без математически корректных entry, stop-loss и take-profit."
    if status == "expired":
        return f"{symbol}: сетап просрочен или построен на устаревшей свече. Перед любым решением нужно пересчитать рынок и получить свежий сигнал."
    if status == "blocked":
        return f"{symbol}: NO_TRADE. Главная причина: {_reason_text(hard, 'есть hard veto')}. Entry/SL/TP оставлены только для аудита расчёта, открывать сделку нельзя."
    if trade_direction in {DIRECTION_LONG, DIRECTION_SHORT}:
        side = "LONG" if trade_direction == DIRECTION_LONG else "SHORT"
        base = f"{symbol} {interval}: {side}-сценарий по {strategy}. Entry {levels['entry']:.8g}, SL {levels['stop_loss']:.8g}, TP {levels['take_profit']:.8g}, R/R {rr:.2f}."
        conf = f" Confidence {confidence:.0%} — это инженерный скоринг качества сетапа, не точная вероятность прибыли."
        qual = f" Strategy quality: {quality}."
        px = f" Статус цены: {price_status}."
        if status == "review_entry":
            return base + conf + qual + px + " Допустима только ручная проверка входа после контроля spread, проскальзывания и актуальности цены."
        return base + conf + qual + px + f" Это исследовательский кандидат: {_reason_text(evidence or warnings, 'quality/backtest evidence недостаточен для полноценного входа')}."
    return f"{symbol}: WAIT/NO_TRADE. Система не нашла достаточного сочетания свежести, MTF, ликвидности, R/R, confidence и качества стратегии для практического входа."


def _factor_items(row: dict[str, Any], key: str) -> list[dict[str, str]]:
    raw = row.get(key) or []
    out: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw[:8]:
            if isinstance(item, dict):
                out.append({
                    "code": str(item.get("code") or item.get("title") or "factor"),
                    "title": str(item.get("title") or item.get("code") or "factor"),
                    "detail": str(item.get("detail") or item.get("text") or ""),
                })
            else:
                out.append({"code": "factor", "title": str(item), "detail": ""})
    return out


def signal_breakdown(row: dict[str, Any], levels: dict[str, Any], price: dict[str, Any]) -> dict[str, Any]:
    rationale = row.get("rationale") if isinstance(row.get("rationale"), dict) else {}
    return {
        "strategy": row.get("strategy"),
        "timeframe": row.get("interval"),
        "bar_time": row.get("bar_time"),
        "raw_direction": row.get("direction"),
        "confidence": clamp(row.get("confidence")),
        "risk": {
            "entry": levels.get("entry"),
            "stop_loss": levels.get("stop_loss"),
            "take_profit": levels.get("take_profit"),
            "risk_pct": levels.get("risk_pct"),
            "expected_reward_pct": levels.get("expected_reward_pct"),
            "risk_reward": levels.get("risk_reward"),
        },
        "price": price,
        "market": {
            "spread_pct": finite(row.get("spread_pct")),
            "liquidity_score": finite(row.get("liquidity_score")),
            "liquidity_status": row.get("liquidity_status"),
            "turnover_24h": finite(row.get("turnover_24h")),
        },
        "quality": {
            "status": row.get("quality_status"),
            "score": finite(row.get("quality_score")),
            "reason": row.get("quality_reason"),
            "trades_count": finite(row.get("trades_count")),
            "profit_factor": finite(row.get("profit_factor")),
            "win_rate": finite(row.get("win_rate")),
            "max_drawdown": finite(row.get("max_drawdown")),
            "expectancy": finite(row.get("expectancy")),
            "walk_forward_pass_rate": finite(row.get("walk_forward_pass_rate")),
        },
        "raw_indicators": {k: v for k, v in rationale.items() if k not in {"votes", "signal_breakdown"}},
        "votes": rationale.get("votes") if isinstance(rationale.get("votes"), list) else [],
    }


def enrich_recommendation_row(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    levels = validate_trade_levels(row.get("direction"), row.get("entry"), row.get("stop_loss"), row.get("take_profit"))
    expires_at = recommendation_expires_at(row, now=now)
    price = price_freshness(row, expires_at, levels, now=now)
    status = recommendation_status(row, levels, price)
    trade_direction = user_trade_direction(row, status)
    action_map = {
        "review_entry": f"Проверить ручной {trade_direction.upper()}-вход",
        "research_candidate": f"Изучить {trade_direction.upper()} без входа",
        "wait": "Ждать подтверждения",
        "blocked": "Пропустить",
        "expired": "Пересчитать рекомендацию",
        "invalid": "Исправить данные/уровни",
    }
    factors_for = _factor_items(row, "operator_evidence_notes")
    factors_against = _factor_items(row, "operator_hard_reasons") + _factor_items(row, "operator_warnings")
    explanation_text = explanation(row, status, trade_direction, levels, price)
    invalidation = invalidation_condition(trade_direction, levels, expires_at) if levels.get("valid") else "Вход запрещён: уровни сделки не прошли серверную проверку."
    contract = {
        "recommendation_id": row.get("id"),
        "recommendation_status": status,
        "recommended_action": action_map.get(status, "Ждать"),
        "trade_direction": trade_direction,
        "display_direction": trade_direction.upper() if trade_direction != DIRECTION_NO_TRADE else "NO_TRADE",
        "confidence_score": int(round(clamp(row.get("confidence")) * 100)),
        "expires_at": to_iso(expires_at),
        "valid_until": to_iso(expires_at),
        "risk_pct": levels.get("risk_pct"),
        "expected_reward_pct": levels.get("expected_reward_pct"),
        "risk_reward": levels.get("risk_reward"),
        "level_validation": {"valid": levels.get("valid"), "reason": levels.get("reason")},
        "price_status": price.get("price_status"),
        "price_drift_pct": price.get("price_drift_pct"),
        "entry_zone_pct": price.get("entry_zone_pct"),
        "last_price": price.get("last_price"),
        "last_price_time": price.get("last_price_time"),
        "invalidation_condition": invalidation,
        "recommendation_explanation": explanation_text,
        "factors_for": factors_for,
        "factors_against": factors_against,
        "signal_breakdown": signal_breakdown(row, levels, price),
        "is_actionable": status == "review_entry" and trade_direction in {DIRECTION_LONG, DIRECTION_SHORT} and price.get("price_status") in {"entry_zone", "extended", "unknown"},
    }
    return {**row, **contract, "recommendation": contract}
