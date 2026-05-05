from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .db import execute_many_values, fetch_all
from .trade_contract import finite, interval_to_timedelta, recommendation_expires_at, validate_trade_levels

SAME_BAR_STOP_FIRST_REASON = "stop_loss_same_bar_ambiguous"
INTRABAR_EXECUTION_MODEL = "conservative_ohlc_stop_loss_first"


def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _outcome_payload(status: str, *, exit_price: float | None, exit_time: Any, realized_r: float | None, mfe: float, mae: float, bars: int, notes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "outcome_status": status,
        "exit_price": exit_price,
        "exit_time": exit_time,
        "realized_r": realized_r,
        "max_favorable_excursion_r": max(0.0, mfe),
        "max_adverse_excursion_r": min(0.0, mae),
        "bars_observed": max(0, bars),
        "notes": notes or {},
    }




def _valid_candle_range(candle: dict[str, Any]) -> tuple[float, float] | None:
    """Вернуть high/low только для математически валидной OHLC-свечи.

    Outcome evaluator не имеет права строить качество рекомендаций на битых
    свечах: high ниже low, нулевые цены или NaN/Infinity должны быть явно
    исключены и отражены в notes результата, а не молча искажать R-метрики.
    """
    open_f = finite(candle.get("open"))
    high_f = finite(candle.get("high"))
    low_f = finite(candle.get("low"))
    close_f = finite(candle.get("close"))
    values = [v for v in (open_f, high_f, low_f, close_f) if v is not None]
    if high_f is None or low_f is None or high_f <= 0 or low_f <= 0 or high_f < low_f:
        return None
    if any(v <= 0 for v in values):
        return None
    if open_f is not None and not (low_f <= open_f <= high_f):
        return None
    if close_f is not None and not (low_f <= close_f <= high_f):
        return None
    return high_f, low_f


def _with_data_quality_notes(payload: dict[str, Any], *, skipped_invalid_candles: int, valid_bars: int) -> dict[str, Any]:
    notes = dict(payload.get("notes") or {})
    if skipped_invalid_candles:
        notes["data_quality_issue"] = True
        notes["skipped_invalid_candles"] = skipped_invalid_candles
        notes.setdefault("data_quality_reason", "invalid_ohlc_candles_skipped")
    if valid_bars == 0 and payload.get("outcome_status") in {"expired", "open"}:
        notes["data_quality_issue"] = True
        notes["no_valid_bars_after_signal"] = True
        notes.setdefault("data_quality_reason", "no_valid_ohlc_after_signal")
    return {**payload, "notes": notes}


def _ambiguous_stop_notes(direction: str) -> dict[str, Any]:
    # Same-bar SL/TP — не обычный стоп. Это методологически неоднозначная свеча,
    # поэтому outcome хранит отдельный флаг для quality dashboards и интерфейса.
    return {
        "same_bar_stop_first": True,
        "ambiguous_exit": True,
        "both_sl_tp_touched": True,
        "exit_reason": SAME_BAR_STOP_FIRST_REASON,
        "intrabar_execution_model": INTRABAR_EXECUTION_MODEL,
        "direction": direction,
    }


def evaluate_signal_outcome(signal: dict[str, Any], candles: list[dict[str, Any]], *, now: datetime | None = None) -> dict[str, Any]:
    """Evaluate one recommendation after the signal bar using conservative OHLC rules.

    If SL and TP are touched inside the same candle, stop-loss wins. This is an
    intentionally pessimistic assumption: without tick/order-book sequence data,
    assuming TP first would inflate quality metrics.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    levels = validate_trade_levels(signal.get("direction"), signal.get("entry"), signal.get("stop_loss"), signal.get("take_profit"))
    if not levels.get("valid"):
        return _outcome_payload("invalidated", exit_price=None, exit_time=None, realized_r=0.0, mfe=0.0, mae=0.0, bars=0, notes={"reason": levels.get("reason")})

    direction = str(signal.get("direction") or "").lower()
    entry = float(levels["entry"])
    stop = float(levels["stop_loss"])
    target = float(levels["take_profit"])
    risk = abs(entry - stop)
    reward_r = abs(target - entry) / risk
    expires_at = recommendation_expires_at(signal, now=now)
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    mfe = 0.0
    mae = 0.0
    bars = 0
    skipped_invalid_candles = 0
    for candle in candles:
        ts = _parse_dt(candle.get("start_time") or candle.get("ts") or candle.get("time"))
        if expires_at is not None and ts is not None and ts > expires_at:
            break
        candle_range = _valid_candle_range(candle)
        if candle_range is None:
            skipped_invalid_candles += 1
            continue
        high, low = candle_range
        bars += 1
        if direction == "long":
            mfe = max(mfe, (high - entry) / risk)
            mae = min(mae, (low - entry) / risk)
            stop_hit = low <= stop
            target_hit = high >= target
            if stop_hit and target_hit:
                return _with_data_quality_notes(_outcome_payload("hit_stop_loss", exit_price=stop, exit_time=ts, realized_r=-1.0, mfe=mfe, mae=mae, bars=bars, notes=_ambiguous_stop_notes(direction)), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)
            if stop_hit:
                return _with_data_quality_notes(_outcome_payload("hit_stop_loss", exit_price=stop, exit_time=ts, realized_r=-1.0, mfe=mfe, mae=mae, bars=bars, notes={"exit_reason": "stop_loss", "intrabar_execution_model": INTRABAR_EXECUTION_MODEL}), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)
            if target_hit:
                return _with_data_quality_notes(_outcome_payload("hit_take_profit", exit_price=target, exit_time=ts, realized_r=reward_r, mfe=mfe, mae=mae, bars=bars, notes={"exit_reason": "take_profit", "intrabar_execution_model": INTRABAR_EXECUTION_MODEL}), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)
        else:
            mfe = max(mfe, (entry - low) / risk)
            mae = min(mae, (entry - high) / risk)
            stop_hit = high >= stop
            target_hit = low <= target
            if stop_hit and target_hit:
                return _with_data_quality_notes(_outcome_payload("hit_stop_loss", exit_price=stop, exit_time=ts, realized_r=-1.0, mfe=mfe, mae=mae, bars=bars, notes=_ambiguous_stop_notes(direction)), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)
            if stop_hit:
                return _with_data_quality_notes(_outcome_payload("hit_stop_loss", exit_price=stop, exit_time=ts, realized_r=-1.0, mfe=mfe, mae=mae, bars=bars, notes={"exit_reason": "stop_loss", "intrabar_execution_model": INTRABAR_EXECUTION_MODEL}), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)
            if target_hit:
                return _with_data_quality_notes(_outcome_payload("hit_take_profit", exit_price=target, exit_time=ts, realized_r=reward_r, mfe=mfe, mae=mae, bars=bars, notes={"exit_reason": "take_profit", "intrabar_execution_model": INTRABAR_EXECUTION_MODEL}), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)

    if expires_at is not None and now >= expires_at:
        return _with_data_quality_notes(_outcome_payload("expired", exit_price=None, exit_time=expires_at, realized_r=0.0, mfe=mfe, mae=mae, bars=bars), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)
    return _with_data_quality_notes(_outcome_payload("open", exit_price=None, exit_time=None, realized_r=None, mfe=mfe, mae=mae, bars=bars), skipped_invalid_candles=skipped_invalid_candles, valid_bars=bars)


def _due_signals(category: str, limit: int) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT s.id, s.created_at, s.bar_time, s.expires_at, s.category, s.symbol, s.interval, s.strategy,
               s.direction, s.confidence, s.entry, s.stop_loss, s.take_profit, s.atr, s.rationale
        FROM signals s
        LEFT JOIN recommendation_outcomes o ON o.signal_id=s.id
        WHERE s.category=%s
          AND s.direction IN ('long','short')
          AND s.bar_time IS NOT NULL
          AND (o.signal_id IS NULL OR o.outcome_status='open')
          AND s.bar_time < NOW()
        ORDER BY s.created_at DESC
        LIMIT %s
        """,
        (category, limit),
    )


def _candles_after_signal(signal: dict[str, Any]) -> list[dict[str, Any]]:
    start = _parse_dt(signal.get("bar_time"))
    if start is None:
        return []
    start = start + interval_to_timedelta(str(signal.get("interval") or ""))
    expires_at = recommendation_expires_at(signal)
    return fetch_all(
        """
        SELECT start_time, open, high, low, close, volume
        FROM candles
        WHERE category=%s AND symbol=%s AND interval=%s
          AND start_time >= %s
          AND (%s::timestamptz IS NULL OR start_time <= %s)
        ORDER BY start_time ASC
        LIMIT 500
        """,
        (signal.get("category"), signal.get("symbol"), signal.get("interval"), start, expires_at, expires_at),
    )


def evaluate_due_recommendation_outcomes(category: str = "linear", limit: int = 250) -> dict[str, Any]:
    signals = _due_signals(category, limit)
    rows: list[tuple[Any, ...]] = []
    for signal in signals:
        outcome = evaluate_signal_outcome(signal, _candles_after_signal(signal))
        rows.append(
            (
                signal["id"],
                outcome["outcome_status"],
                outcome["exit_time"],
                outcome["exit_price"],
                outcome["realized_r"],
                outcome["max_favorable_excursion_r"],
                outcome["max_adverse_excursion_r"],
                outcome["bars_observed"],
                outcome["notes"],
            )
        )
    inserted = execute_many_values(
        """
        INSERT INTO recommendation_outcomes(signal_id, outcome_status, exit_time, exit_price, realized_r,
                                            max_favorable_excursion_r, max_adverse_excursion_r, bars_observed, notes)
        VALUES %s
        ON CONFLICT(signal_id) DO UPDATE SET evaluated_at=NOW(), outcome_status=EXCLUDED.outcome_status,
            exit_time=EXCLUDED.exit_time, exit_price=EXCLUDED.exit_price, realized_r=EXCLUDED.realized_r,
            max_favorable_excursion_r=EXCLUDED.max_favorable_excursion_r,
            max_adverse_excursion_r=EXCLUDED.max_adverse_excursion_r,
            bars_observed=EXCLUDED.bars_observed, notes=EXCLUDED.notes
        """,
        rows,
    )
    return {"evaluated": len(signals), "upserted": inserted}
