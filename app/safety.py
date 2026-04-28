from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import settings


def interval_to_timedelta(interval: Any) -> timedelta:
    value = str(interval or "").strip().upper()
    if value.isdigit():
        return timedelta(minutes=max(1, int(value)))
    return {"D": timedelta(days=1), "W": timedelta(days=7), "M": timedelta(days=31)}.get(value, timedelta(hours=1))


def parse_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    return out if math.isfinite(out) else default


def signal_freshness(bar_time: Any, interval: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Возвращает freshness-статус сигнала по времени рыночной свечи, а не created_at.

    Для советующей торговой системы свежий `created_at` сам по себе небезопасен:
    рекомендацию можно пересчитать сегодня на последней свече недельной давности.
    Поэтому UI/API подавляют stale/no_bar_time сигналы до оператора.
    """
    parsed = parse_utc_datetime(bar_time)
    if parsed is None:
        return {"fresh": False, "data_status": "no_bar_time", "bar_closed_at": None, "signal_age_minutes": None}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    interval_delta = interval_to_timedelta(interval)
    closed_at = parsed + interval_delta
    if closed_at > now:
        return {"fresh": False, "data_status": "unclosed_bar", "bar_closed_at": closed_at.isoformat(), "signal_age_minutes": None}
    max_lag = min(
        timedelta(hours=max(1, int(settings.max_signal_age_hours))),
        max(interval_delta + timedelta(minutes=15), timedelta(hours=1)),
    )
    age = now - closed_at
    fresh = age <= max_lag
    return {
        "fresh": fresh,
        "data_status": "fresh" if fresh else "stale",
        "bar_closed_at": closed_at.isoformat(),
        "signal_age_minutes": round(age.total_seconds() / 60, 2),
        "max_allowed_lag_minutes": round(max_lag.total_seconds() / 60, 2),
    }


def risk_reward(entry: Any, stop_loss: Any, take_profit: Any) -> float | None:
    entry_v = finite_float(entry)
    stop_v = finite_float(stop_loss)
    take_v = finite_float(take_profit)
    if entry_v is None or stop_v is None or take_v is None:
        return None
    risk = abs(entry_v - stop_v)
    reward = abs(take_v - entry_v)
    if risk <= 0 or reward <= 0:
        return None
    return round(reward / risk, 6)


def annotate_signal_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    freshness = signal_freshness(out.get("bar_time"), out.get("interval"))
    out.update(freshness)
    out["risk_reward"] = risk_reward(out.get("entry"), out.get("stop_loss"), out.get("take_profit"))
    return out


def annotate_and_filter_fresh_signals(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated = [annotate_signal_row(row) for row in rows]
    return [row for row in annotated if row.get("fresh") is True]
