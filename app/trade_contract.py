from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import settings

DIRECTION_LONG = "long"
DIRECTION_SHORT = "short"
DIRECTION_NO_TRADE = "no_trade"
RECOMMENDATION_CONTRACT_VERSION = "recommendation_v40"
DECISION_SOURCE = "server_enriched_contract_v40"
INTRABAR_EXECUTION_MODEL = "conservative_ohlc_stop_loss_first"
SAME_BAR_STOP_FIRST_REASON = "stop_loss_same_bar_ambiguous"
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


def utc_now(value: datetime | None = None) -> datetime:
    # Единая точка времени для enrichment: TTL, price gate и health-check
    # должны считаться относительно одного timestamp, иначе пограничные
    # рекомендации могут получить разные статусы в соседних полях JSON.
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def ttl_state(expires_at: datetime | None, *, now: datetime | None = None) -> dict[str, Any]:
    current = utc_now(now)
    if expires_at is None:
        return {"status": "missing", "seconds_left": None, "is_expired": False, "checked_at": to_iso(current)}
    expiry = utc_now(expires_at)
    seconds_left = int((expiry - current).total_seconds())
    if seconds_left <= 0:
        status = "expired"
    elif seconds_left <= 15 * 60:
        status = "expiring_soon"
    else:
        status = "active"
    return {"status": status, "seconds_left": seconds_left, "is_expired": seconds_left <= 0, "checked_at": to_iso(current)}


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
    # Приоритет: сохраненный contract TTL в БД, затем rationale, затем расчет от bar_time.
    # Это позволяет API, outcome evaluator и UI видеть один и тот же срок жизни
    # рекомендации без повторной бизнес-логики на клиенте.
    stored = parse_datetime(row.get("expires_at") or row.get("valid_until"))
    if stored is not None:
        return stored
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
    if expires_at is not None and expires_at <= now:
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


def price_actionability(
    price: dict[str, Any],
    status: str,
    levels: dict[str, Any],
    expires_at: datetime | None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Server-side gate that tells the UI whether the current price is still usable.

    The frontend must not infer tradability from raw direction/entry/SL/TP.  This
    payload is the canonical actionability decision: valid levels, non-expired
    TTL and current price inside the server-defined entry window are required.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    entry = finite(levels.get("entry"))
    last_price = finite(price.get("last_price"))
    zone_pct = finite(price.get("entry_zone_pct"), 0.0025) or 0.0025
    entry_window = None
    if entry is not None and entry > 0:
        entry_window = {
            "low": entry * (1.0 - zone_pct),
            "high": entry * (1.0 + zone_pct),
            "pct": zone_pct,
        }

    reasons: list[str] = []
    if not levels.get("valid"):
        reasons.append(str(levels.get("reason") or "invalid_levels"))
    if expires_at is None:
        reasons.append("missing_expiry")
    elif expires_at <= now:
        reasons.append("expired")
    if price.get("is_stale"):
        reasons.append("stale_data")
    price_status = str(price.get("price_status") or "unknown")
    if price_status == "unknown":
        reasons.append("price_unknown")
    elif price_status == "moved_away":
        reasons.append("price_moved_away")
    elif price_status == "extended":
        reasons.append("price_extended_wait_retest")
    elif price_status != "entry_zone":
        reasons.append(f"price_{price_status}")
    if status != "review_entry":
        reasons.append(f"status_{status}")

    is_actionable = not reasons
    return {
        "status": "actionable" if is_actionable else "blocked",
        "is_price_actionable": is_actionable,
        "reason": None if is_actionable else reasons[0],
        "reasons": reasons,
        "last_price": last_price,
        "price_status": price_status,
        "price_drift_pct": price.get("price_drift_pct"),
        "entry_window": entry_window,
        "expires_at": to_iso(expires_at),
        "checked_at": to_iso(now),
    }


def execution_plan(levels: dict[str, Any]) -> dict[str, Any]:
    """Position-sizing helper for advisory UI.

    It never sends orders and intentionally caps notional by settings. The result
    is a deterministic display contract so frontend does not reimplement risk
    arithmetic with different rounding or hidden assumptions.
    """
    entry = finite(levels.get("entry"))
    risk_pct = finite(levels.get("risk_pct"))
    reward_pct = finite(levels.get("expected_reward_pct"))
    risk_amount = max(0.0, float(settings.start_equity_usdt) * float(settings.risk_per_trade))
    fee_drag_pct = max(0.0, 2.0 * float(settings.fee_rate) + 2.0 * float(settings.slippage_rate))
    if entry is None or entry <= 0 or risk_pct is None or risk_pct <= 0:
        return {
            "risk_amount_usdt": risk_amount,
            "position_notional_usdt": None,
            "estimated_quantity": None,
            "margin_at_max_leverage_usdt": None,
            "max_leverage": float(settings.max_leverage),
            "fee_slippage_roundtrip_pct": fee_drag_pct,
            "net_expected_reward_pct": None,
            "net_risk_reward": None,
            "sizing_status": "invalid_levels",
        }
    raw_notional = risk_amount / risk_pct
    cap = min(float(settings.max_position_notional_usdt), float(settings.start_equity_usdt) * float(settings.max_leverage))
    notional = max(0.0, min(raw_notional, cap))
    quantity = notional / entry if notional > 0 else None
    net_reward = (reward_pct - fee_drag_pct) if reward_pct is not None else None
    net_rr = (net_reward / risk_pct) if net_reward is not None and risk_pct > 0 else None
    sizing_status = "capped" if notional < raw_notional else "risk_based"
    if net_rr is not None and net_rr <= 1.0:
        sizing_status = "fee_adjusted_unattractive"
    return {
        "risk_amount_usdt": risk_amount,
        "position_notional_usdt": notional,
        "estimated_quantity": quantity,
        "margin_at_max_leverage_usdt": notional / float(settings.max_leverage) if settings.max_leverage > 0 else None,
        "max_leverage": float(settings.max_leverage),
        "fee_slippage_roundtrip_pct": fee_drag_pct,
        "net_expected_reward_pct": net_reward,
        "net_risk_reward": net_rr,
        "sizing_status": sizing_status,
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
    if action == "NO_TRADE":
        # Hard-veto должен оставаться видимым даже после истечения TTL: иначе
        # оператор увидит только "expired" и потеряет исходную причину запрета.
        return "blocked"
    if price.get("is_stale"):
        return "expired"
    price_status = str(price.get("price_status") or "unknown")
    if price_status in {"extended", "moved_away"} and action in {"REVIEW_ENTRY", "RESEARCH_CANDIDATE"}:
        # REVIEW_ENTRY допустим только внутри серверного entry-window. Состояние
        # extended раньше оставляло статус review_entry при заблокированном
        # price_actionability, из-за чего UI одновременно показывал ручной вход
        # и красный price gate. Теперь любой выход из entry_zone демотируется в
        # missed_entry/NO_TRADE: оператор должен ждать ретест или пересчет.
        return "missed_entry"
    if price_status == "unknown" and action in {"REVIEW_ENTRY", "RESEARCH_CANDIDATE"}:
        # Если нет проверяемой текущей цены, нельзя оставлять directional review.
        # Это не missed entry, а WAIT/NO_TRADE до восстановления quote feed.
        return "wait"
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


def outcome_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Canonical completed-recommendation state for history/detail views.

    Active recommendation endpoints exclude terminal outcomes; history and detail
    still need to show exactly why a prior recommendation is no longer tradable.
    """
    status = str(row.get("outcome_status") or "").strip().lower()
    terminal = status in {"hit_take_profit", "hit_stop_loss", "expired", "invalidated", "closed_manual"}
    notes = row.get("outcome_notes") if isinstance(row.get("outcome_notes"), dict) else {}
    ambiguous = bool(notes.get("ambiguous_exit") or notes.get("same_bar_stop_first") or notes.get("exit_reason") == SAME_BAR_STOP_FIRST_REASON)
    return {
        "status": status or None,
        "is_terminal": terminal,
        "evaluated_at": to_iso(parse_datetime(row.get("outcome_evaluated_at"))),
        "exit_time": to_iso(parse_datetime(row.get("exit_time"))),
        "exit_price": finite(row.get("exit_price")),
        "realized_r": finite(row.get("realized_r")),
        "max_favorable_excursion_r": finite(row.get("max_favorable_excursion_r")),
        "max_adverse_excursion_r": finite(row.get("max_adverse_excursion_r")),
        "notes": notes,
        "is_ambiguous_intrabar_exit": ambiguous,
        "intrabar_execution_model": (notes.get("intrabar_execution_model") or INTRABAR_EXECUTION_MODEL) if status else None,
    }


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
    if status == "missed_entry":
        reason = "цена вышла из точной entry-зоны"
        if price_status == "moved_away":
            reason = "цена ушла далеко от entry-зоны"
        elif price_status == "extended":
            reason = "цена находится в расширенной зоне, где вход без ретеста запрещён"
        drift = finite(price.get("price_drift_pct"))
        zone = finite(price.get("entry_zone_pct"))
        drift_text = "н/д" if drift is None else f"{drift:.2%}"
        zone_text = "н/д" if zone is None else f"{zone:.2%}"
        return f"{symbol}: NO_TRADE. {reason}; drift {drift_text} при допустимом окне {zone_text}. Не догонять рынок: ждать ретеста или пересчитать рекомендацию."
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
        "execution_model": {
            "intrabar": INTRABAR_EXECUTION_MODEL,
            "same_bar_policy": "SL-first when SL and TP are touched inside one OHLC candle",
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
        "outcome_quality": {
            "recent_outcomes_count": finite(row.get("recent_outcomes_count"), 0.0),
            "recent_loss_count": finite(row.get("recent_loss_count"), 0.0),
            "recent_loss_rate": finite(row.get("recent_loss_rate")),
            "recent_average_r": finite(row.get("recent_average_r")),
            "recent_profit_factor": finite(row.get("recent_profit_factor")),
            "recent_consecutive_losses": finite(row.get("recent_consecutive_losses"), 0.0),
            "recent_last_evaluated_at": row.get("recent_last_evaluated_at"),
            "quarantine_rules": {
                "min_trades": settings.recommendation_loss_quarantine_min_trades,
                "max_loss_rate": settings.recommendation_loss_quarantine_max_loss_rate,
                "min_expectancy_r": settings.recommendation_loss_quarantine_min_expectancy_r,
                "consecutive_losses": settings.recommendation_loss_quarantine_consecutive_losses,
            },
        },
        "raw_indicators": {k: v for k, v in rationale.items() if k not in {"votes", "signal_breakdown"}},
        "votes": rationale.get("votes") if isinstance(rationale.get("votes"), list) else [],
    }




def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def statistics_confidence(row: dict[str, Any]) -> dict[str, Any]:
    trades = finite(row.get("trades_count"), 0.0) or 0.0
    wf_windows = finite(row.get("walk_forward_windows"), 0.0) or 0.0
    quality = str(row.get("quality_status") or "RESEARCH").upper()
    if trades >= 100 and wf_windows >= 3 and quality == "APPROVED":
        level = "high"
    elif trades >= 30 and quality in {"APPROVED", "WATCHLIST"}:
        level = "medium"
    elif trades > 0:
        level = "low"
    else:
        level = "none"
    if level in {"none", "low"}:
        explanation = f"Историческая выборка по похожим сигналам мала: {int(trades)} сделок. Это снижает статистическую уверенность и не должно маскироваться фразой 'бэктест слабый'."
    elif level == "medium":
        explanation = f"Историческая выборка умеренная: {int(trades)} сделок; качество стратегии и качество конкретного сигнала учитываются раздельно."
    else:
        explanation = f"Историческая выборка достаточная для рабочего контроля: {int(trades)} сделок и walk-forward окон {int(wf_windows)}."
    return {
        "level": level,
        "trades_count": int(trades),
        "walk_forward_windows": int(wf_windows),
        "profit_factor": finite(row.get("profit_factor")),
        "win_rate": finite(row.get("win_rate")),
        "expectancy": finite(row.get("expectancy")),
        "max_drawdown": finite(row.get("max_drawdown")),
        "recent_outcomes_count": int(finite(row.get("recent_outcomes_count"), 0.0) or 0),
        "recent_average_r": finite(row.get("recent_average_r")),
        "recent_loss_rate": finite(row.get("recent_loss_rate")),
        "recent_consecutive_losses": int(finite(row.get("recent_consecutive_losses"), 0.0) or 0),
        "explanation": explanation,
    }


def timeframes_used(row: dict[str, Any]) -> list[dict[str, Any]]:
    rationale = row.get("rationale") if isinstance(row.get("rationale"), dict) else {}
    raw = _as_list(rationale.get("timeframes_used") or rationale.get("timeframes") or row.get("timeframes_used"))
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            tf = str(item.get("interval") or item.get("timeframe") or "").strip()
            if tf:
                out.append({"interval": tf, "role": str(item.get("role") or "context"), "status": str(item.get("status") or "used")})
        else:
            tf = str(item).strip()
            if tf:
                out.append({"interval": tf, "role": "context", "status": "used"})
    current = str(row.get("interval") or "").strip()
    if current and not any(item.get("interval") == current for item in out):
        out.insert(0, {"interval": current, "role": "entry", "status": "used"})
    for key, role in (("mtf_bias_interval", "bias"), ("mtf_regime_interval", "regime")):
        value = row.get(key) or rationale.get(key)
        if value and not any(item.get("interval") == str(value) for item in out):
            out.append({"interval": str(value), "role": role, "status": "used"})
    return out


def indicator_values(row: dict[str, Any]) -> dict[str, Any]:
    rationale = row.get("rationale") if isinstance(row.get("rationale"), dict) else {}
    source = rationale.get("indicators") if isinstance(rationale.get("indicators"), dict) else rationale
    allowed = (
        "rsi", "ema_fast", "ema_slow", "ema_20", "ema_50", "ema_200", "atr", "adx",
        "bb_width", "bb_position", "funding_rate", "open_interest", "volume_zscore",
        "trend_score", "volatility_score", "sentiment_score", "ml_probability",
    )
    out: dict[str, Any] = {}
    for key in allowed:
        value = row.get(key, source.get(key) if isinstance(source, dict) else None)
        parsed = finite(value)
        if parsed is not None:
            out[key] = parsed
    if finite(row.get("atr")) is not None:
        out.setdefault("atr", finite(row.get("atr")))
    if finite(row.get("sentiment_score")) is not None:
        out.setdefault("sentiment_score", finite(row.get("sentiment_score")))
    if finite(row.get("ml_probability")) is not None:
        out.setdefault("ml_probability", finite(row.get("ml_probability")))
    return out


def trading_signals(row: dict[str, Any]) -> list[dict[str, str]]:
    rationale = row.get("rationale") if isinstance(row.get("rationale"), dict) else {}
    raw = rationale.get("signal_breakdown") or rationale.get("votes") or row.get("trading_signals") or []
    out: list[dict[str, str]] = []
    if isinstance(raw, dict):
        raw = raw.items()
    for item in list(raw)[:12] if isinstance(raw, list) else list(raw)[:12]:
        if isinstance(item, dict):
            out.append({
                "name": str(item.get("name") or item.get("code") or item.get("title") or "signal"),
                "direction": str(item.get("direction") or row.get("direction") or "flat"),
                "timeframe": str(item.get("timeframe") or item.get("interval") or row.get("interval") or ""),
                "impact": str(item.get("impact") or item.get("weight") or item.get("score") or ""),
                "explanation": str(item.get("explanation") or item.get("detail") or item.get("text") or ""),
            })
        elif isinstance(item, tuple) and len(item) == 2:
            out.append({"name": str(item[0]), "direction": str(row.get("direction") or "flat"), "timeframe": str(row.get("interval") or ""), "impact": str(item[1]), "explanation": ""})
        else:
            out.append({"name": str(item), "direction": str(row.get("direction") or "flat"), "timeframe": str(row.get("interval") or ""), "impact": "", "explanation": ""})
    if not out:
        out.append({"name": str(row.get("strategy") or "strategy"), "direction": str(row.get("direction") or "flat"), "timeframe": str(row.get("interval") or ""), "impact": str(row.get("confidence") or ""), "explanation": "Финальная рекомендация собрана из серверной стратегии, MTF, качества данных и risk gate."})
    return out


def next_actions(status: str, trade_direction: str, price: dict[str, Any]) -> list[dict[str, str]]:
    if status == "review_entry" and trade_direction in {DIRECTION_LONG, DIRECTION_SHORT}:
        if str(price.get("price_status") or "unknown") != "entry_zone":
            return [
                {"action": "wait_confirmation", "label": "Ждать ретест entry-зоны", "detail": "Цена уже не в точной зоне входа; не догонять рынок, дождаться возврата к entry или пересчитать."},
                {"action": "close_invalidated", "label": "Закрыть как неактуальную", "detail": "Использовать, если цена не возвращается в допустимое окно до истечения TTL."},
                {"action": "skip", "label": "Пропустить", "detail": "Пропуск безопаснее входа вне серверного price gate."},
            ]
        return [
            {"action": "manual_review", "label": "Открыть ручной разбор", "detail": "Проверить стакан, spread, актуальность entry и размер позиции до любой сделки."},
            {"action": "wait_confirmation", "label": "Ждать подтверждения", "detail": "Использовать при неполном MTF/сомнительной цене; рекомендация остается advisory-only."},
            {"action": "close_invalidated", "label": "Закрыть как неактуальную", "detail": "Использовать при уходе цены, hard veto или истечении TTL."},
        ]
    if status == "missed_entry":
        return [{"action": "wait_confirmation", "label": "Не догонять цену", "detail": "Ждать ретеста entry-зоны или пересчитать рекомендации."}]
    if status in {"expired", "invalid"}:
        return [{"action": "recalculate", "label": "Пересчитать", "detail": "Старый/невалидный контракт нельзя использовать для входа."}]
    return [{"action": "skip", "label": "Пропустить", "detail": "NO_TRADE является нормальным защитным состоянием системы."}]


def enrich_recommendation_row(row: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    as_of = utc_now(now)
    levels = validate_trade_levels(row.get("direction"), row.get("entry"), row.get("stop_loss"), row.get("take_profit"))
    expires_at = recommendation_expires_at(row, now=as_of)
    ttl = ttl_state(expires_at, now=as_of)
    price = price_freshness(row, expires_at, levels, now=as_of)
    status = recommendation_status(row, levels, price)
    trade_direction = user_trade_direction(row, status)
    action_map = {
        "review_entry": f"Проверить ручной {trade_direction.upper()}-вход",
        "research_candidate": f"Изучить {trade_direction.upper()} без входа",
        "wait": "Ждать подтверждения",
        "blocked": "Пропустить",
        "expired": "Пересчитать рекомендацию",
        "invalid": "Исправить данные/уровни",
        "missed_entry": "Не догонять цену; ждать ретест",
    }
    factors_for = _factor_items(row, "operator_evidence_notes")
    factors_against = _factor_items(row, "operator_hard_reasons") + _factor_items(row, "operator_warnings")
    explanation_text = explanation(row, status, trade_direction, levels, price)
    invalidation = invalidation_condition(trade_direction, levels, expires_at) if levels.get("valid") else "Вход запрещён: уровни сделки не прошли серверную проверку."
    sizing = execution_plan(levels)
    price_gate = price_actionability(price, status, levels, expires_at, now=as_of)
    contract = {
        "contract_version": RECOMMENDATION_CONTRACT_VERSION,
        "recommendation_id": row.get("id"),
        "recommendation_status": status,
        "recommended_action": action_map.get(status, "Ждать"),
        "trade_direction": trade_direction,
        "display_direction": trade_direction.upper() if trade_direction != DIRECTION_NO_TRADE else "NO_TRADE",
        "confidence_score": int(round(clamp(row.get("confidence")) * 100)),
        "expires_at": to_iso(expires_at),
        "valid_until": to_iso(expires_at),
        "checked_at": ttl.get("checked_at"),
        "ttl_status": ttl.get("status"),
        "ttl_seconds_left": ttl.get("seconds_left"),
        "is_expired": ttl.get("is_expired"),
        "entry": levels.get("entry"),
        "stop_loss": levels.get("stop_loss"),
        "take_profit": levels.get("take_profit"),
        "risk_pct": levels.get("risk_pct"),
        "expected_reward_pct": levels.get("expected_reward_pct"),
        "risk_reward": levels.get("risk_reward"),
        "net_risk_reward": sizing.get("net_risk_reward"),
        "fee_slippage_roundtrip_pct": sizing.get("fee_slippage_roundtrip_pct"),
        "intrabar_execution_model": INTRABAR_EXECUTION_MODEL,
        "same_bar_stop_first_reason": SAME_BAR_STOP_FIRST_REASON,
        "compatible_extensions": ["market_data_integrity_v44", "quality_segments_v44", "nested_trade_levels_v45", "server_actionability_v46"],
        "position_sizing": sizing,
        "level_validation": {"valid": levels.get("valid"), "reason": levels.get("reason")},
        "price_status": price.get("price_status"),
        "price_drift_pct": price.get("price_drift_pct"),
        "entry_zone_pct": price.get("entry_zone_pct"),
        "last_price": price.get("last_price"),
        "last_price_time": price.get("last_price_time"),
        "price_actionability": price_gate,
        "entry_window": price_gate.get("entry_window"),
        "confidence_semantics": "engineering_score_not_win_probability",
        "decision_source": DECISION_SOURCE,
        "frontend_may_recalculate": False,
        "invalidation_condition": invalidation,
        "recommendation_explanation": explanation_text,
        "factors_for": factors_for,
        "factors_against": factors_against,
        "statistics_confidence": statistics_confidence(row),
        "outcome": outcome_payload(row),
        "timeframes_used": timeframes_used(row),
        "indicator_values": indicator_values(row),
        "trading_signals": trading_signals(row),
        "next_actions": next_actions(status, trade_direction, price),
        "signal_breakdown": {**signal_breakdown(row, levels, price), "position_sizing": sizing},
        "is_actionable": status == "review_entry" and trade_direction in {DIRECTION_LONG, DIRECTION_SHORT} and price_gate.get("is_price_actionable") is True and (sizing.get("net_risk_reward") is None or sizing.get("net_risk_reward") > 1.0),
        "no_trade_reason": ((price_gate.get("reason") or "price_not_in_entry_zone") if status == "missed_entry" else levels.get("reason") if status == "invalid" else None),
    }
    health = contract_health(contract)
    contract["contract_health"] = health
    if health.get("level") == "error" and contract.get("recommendation_status") == "review_entry":
        contract["is_actionable"] = False
        contract["recommended_action"] = "Ждать / не входить до устранения contract guardrail"
    return {**row, **contract, "recommendation": contract}



def contract_health(contract: dict[str, Any]) -> dict[str, Any]:
    """Machine-readable integrity report for the outbound recommendation contract.

    This is intentionally calculated after enrichment, right before the API/UI boundary.
    It catches drift between database rows, backend calculations and frontend rendering
    without letting the browser infer missing guardrails by itself.
    """
    required = (
        "recommendation_id", "recommendation_status", "trade_direction", "confidence_score",
        "entry", "stop_loss", "take_profit", "expires_at",
        "risk_pct", "expected_reward_pct", "risk_reward",
        "recommendation_explanation", "price_actionability", "signal_breakdown",
    )
    problems: list[dict[str, str]] = []
    status = str(contract.get("recommendation_status") or "").lower()
    direction = str(contract.get("trade_direction") or "").lower()
    for key in required:
        if contract.get(key) in (None, "") and status in {"review_entry", "research_candidate"}:
            problems.append({"code": f"missing_{key}", "level": "error", "message": f"Contract field {key} is required for directional recommendations."})
    confidence = finite(contract.get("confidence_score"))
    if confidence is None or confidence < 0 or confidence > 100:
        problems.append({"code": "confidence_score_range", "level": "error", "message": "confidence_score must be in [0,100] and is not a win probability."})
    rr = finite(contract.get("risk_reward"))
    net_rr = finite(contract.get("net_risk_reward"))
    levels = validate_trade_levels(direction, contract.get("entry"), contract.get("stop_loss"), contract.get("take_profit"))
    if status in {"review_entry", "research_candidate"}:
        # Вложенный recommendation contract обязан сам содержать уровни сделки.
        # Иначе detail/explanation endpoints и frontend могут показать top-level
        # fallback и скрыть рассинхрон между БД и серверным контрактом.
        if direction not in {DIRECTION_LONG, DIRECTION_SHORT}:
            problems.append({"code": "directional_status_without_direction", "level": "error", "message": "Directional recommendation status requires long/short trade_direction."})
        if not levels.get("valid"):
            problems.append({"code": str(levels.get("reason") or "invalid_levels"), "level": "error", "message": "Directional recommendation contract must contain ordered entry/SL/TP levels."})
        if rr is None or rr <= 0:
            problems.append({"code": "invalid_risk_reward", "level": "error", "message": "Directional recommendation requires positive risk_reward."})
    if status == "review_entry" and direction in {DIRECTION_LONG, DIRECTION_SHORT}:
        if net_rr is None:
            problems.append({"code": "missing_net_risk_reward", "level": "warn", "message": "Net R/R after fee and slippage is unavailable."})
        elif net_rr <= 1.0:
            problems.append({"code": "net_risk_reward_low", "level": "error", "message": "Net R/R after fee and slippage is not attractive enough for review entry."})
        price_gate = contract.get("price_actionability") if isinstance(contract.get("price_actionability"), dict) else {}
        if price_gate.get("is_price_actionable") is not True:
            problems.append({"code": str(price_gate.get("reason") or "price_gate_blocked"), "level": "error", "message": "Review entry is not actionable unless server price gate is green."})
    if direction == DIRECTION_NO_TRADE and contract.get("is_actionable") is True:
        problems.append({"code": "no_trade_marked_actionable", "level": "error", "message": "NO_TRADE cannot be actionable."})
    if status in {"blocked", "wait", "expired", "invalid", "missed_entry"} and direction in {DIRECTION_LONG, DIRECTION_SHORT}:
        problems.append({"code": "non_entry_status_exposes_direction", "level": "error", "message": "Blocked/wait/expired recommendations must expose trade_direction=no_trade to the operator."})
    if contract.get("frontend_may_recalculate") is not False:
        problems.append({"code": "frontend_recalculation_allowed", "level": "error", "message": "Frontend must render the server-enriched recommendation contract and must not recompute trade math."})
    if contract.get("decision_source") != DECISION_SOURCE:
        problems.append({"code": "missing_server_decision_source", "level": "warn", "message": "Contract should explicitly identify the server as the only decision source."})
    if status in {"review_entry", "research_candidate", "blocked", "wait"}:
        factors_for = contract.get("factors_for")
        factors_against = contract.get("factors_against")
        if not isinstance(factors_for, list) or not isinstance(factors_against, list):
            problems.append({"code": "factor_arrays_missing", "level": "error", "message": "Recommendation explanation factors must be structured arrays."})
    price_gate = contract.get("price_actionability") if isinstance(contract.get("price_actionability"), dict) else {}
    if contract.get("is_actionable") is True and price_gate.get("is_price_actionable") is not True:
        problems.append({"code": "top_level_actionable_without_price_gate", "level": "error", "message": "Top-level is_actionable cannot be true while price gate is blocked."})
    level = "error" if any(p["level"] == "error" for p in problems) else "warn" if problems else "ok"
    return {
        "level": level,
        "ok": level != "error",
        "problems": problems,
        "checked_version": RECOMMENDATION_CONTRACT_VERSION,
    }


def no_trade_decision_snapshot(*, reason: str, category: str | None = None, as_of: datetime | None = None) -> dict[str, Any]:
    """Canonical empty-state recommendation contract for the UI.

    It is not persisted as a signal because there is no instrument/entry/SL/TP to
    evaluate. The point is to make NO_TRADE explicit instead of forcing the
    frontend to infer it from an empty array.
    """
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    contract = {
        "contract_version": RECOMMENDATION_CONTRACT_VERSION,
        "recommendation_id": None,
        "category": category or settings.default_category,
        "recommendation_status": "blocked",
        "recommended_action": "Пропустить / ждать новый расчёт",
        "trade_direction": DIRECTION_NO_TRADE,
        "display_direction": "NO_TRADE",
        "confidence_score": 0,
        "expires_at": None,
        "valid_until": None,
        "checked_at": to_iso(as_of),
        "ttl_status": "no_setup",
        "ttl_seconds_left": None,
        "is_expired": False,
        "entry": None,
        "stop_loss": None,
        "take_profit": None,
        "risk_pct": None,
        "expected_reward_pct": None,
        "risk_reward": None,
        "net_risk_reward": None,
        "intrabar_execution_model": INTRABAR_EXECUTION_MODEL,
        "same_bar_stop_first_reason": SAME_BAR_STOP_FIRST_REASON,
        "compatible_extensions": ["market_data_integrity_v44", "quality_segments_v44", "nested_trade_levels_v45", "server_actionability_v46"],
        "price_status": "no_setup",
        "last_price": None,
        "last_price_time": None,
        "price_actionability": {
            "status": "blocked",
            "is_price_actionable": False,
            "reason": "no_active_recommendation",
            "reasons": ["no_active_recommendation"],
            "last_price": None,
            "price_status": "no_setup",
            "price_drift_pct": None,
            "entry_window": None,
            "expires_at": None,
            "checked_at": to_iso(as_of),
        },
        "entry_window": None,
        "confidence_semantics": "engineering_score_not_win_probability",
        "decision_source": DECISION_SOURCE,
        "frontend_may_recalculate": False,
        "invalidation_condition": "Нет валидного торгового сетапа: вход запрещён до появления свежей рекомендации с entry, SL, TP и сроком актуальности.",
        "recommendation_explanation": reason,
        "factors_for": [],
        "factors_against": [
            {"code": "no_active_recommendation", "title": "Нет активной рекомендации", "detail": reason}
        ],
        "statistics_confidence": {
            "level": "none",
            "trades_count": 0,
            "walk_forward_windows": 0,
            "profit_factor": None,
            "win_rate": None,
            "expectancy": None,
            "max_drawdown": None,
            "explanation": "NO_TRADE не оценивается как сделка; статистика появится после завершённых рекомендаций.",
        },
        "timeframes_used": [],
        "indicator_values": {},
        "trading_signals": [],
        "next_actions": [
            {"action": "recalculate", "label": "Пересчитать рекомендации", "detail": "Синхронизировать рынок и построить сигналы заново."},
            {"action": "skip", "label": "Не открывать сделку", "detail": "Пустой список рекомендаций является защитным состоянием, а не ошибкой UI."},
        ],
        "signal_breakdown": {
            "raw_indicators": {},
            "trading_signal": "NO_TRADE",
            "final_gate": "blocked",
            "execution_model": {
                "intrabar": INTRABAR_EXECUTION_MODEL,
                "same_bar_policy": "SL-first when SL and TP are touched inside one OHLC candle",
            },
            "price": {"price_status": "no_setup"},
            "quality": {"quality_status": "NO_ACTIVE_RECOMMENDATION"},
        },
        "is_actionable": False,
        "no_trade_reason": "no_active_recommendation",
        "as_of": to_iso(as_of),
    }
    contract["contract_health"] = contract_health(contract)
    return contract
