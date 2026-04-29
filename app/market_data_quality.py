from __future__ import annotations

import math
from typing import Any, Mapping


def finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def validate_ohlcv_values(
    open_value: Any,
    high_value: Any,
    low_value: Any,
    close_value: Any,
    volume_value: Any | None = None,
    turnover_value: Any | None = None,
) -> tuple[bool, str | None, dict[str, float | None]]:
    """Проверяет физическую корректность свечи до записи или расчета индикаторов.

    Для trading-рекомендаций нельзя молча использовать битые бары: один high<low,
    отрицательный close или NaN-volume искажает ATR, стопы, R/R и confidence.
    Функция возвращает нормализованные float-значения, чтобы ingestion и feature-layer
    применяли одинаковую трактовку данных.
    """
    raw_volume_present = volume_value is not None
    raw_turnover_present = turnover_value is not None
    values: dict[str, float | None] = {
        "open": finite_float(open_value),
        "high": finite_float(high_value),
        "low": finite_float(low_value),
        "close": finite_float(close_value),
        "volume": finite_float(volume_value),
        "turnover": finite_float(turnover_value),
    }
    if values["volume"] is None and not raw_volume_present:
        values["volume"] = 0.0
    if values["turnover"] is None and not raw_turnover_present:
        values["turnover"] = None
    for key in ("open", "high", "low", "close"):
        value = values[key]
        if value is None:
            return False, f"non_finite_{key}", values
        if value <= 0:
            return False, f"non_positive_{key}", values

    volume = values["volume"]
    turnover = values["turnover"]
    if raw_volume_present and volume is None:
        return False, "non_finite_volume", values
    if raw_turnover_present and turnover is None:
        return False, "non_finite_turnover", values
    if volume is not None and volume < 0:
        return False, "negative_volume", values
    if turnover is not None and turnover < 0:
        return False, "negative_turnover", values

    open_v = values["open"] or 0.0
    high_v = values["high"] or 0.0
    low_v = values["low"] or 0.0
    close_v = values["close"] or 0.0
    eps = max(abs(open_v), abs(high_v), abs(low_v), abs(close_v), 1.0) * 1e-12
    if high_v + eps < low_v:
        return False, "high_below_low", values
    if high_v + eps < max(open_v, close_v):
        return False, "high_below_body", values
    if low_v - eps > min(open_v, close_v):
        return False, "low_above_body", values
    return True, None, values


def candle_problem(row: Mapping[str, Any]) -> str | None:
    ok, reason, _values = validate_ohlcv_values(
        row.get("open"),
        row.get("high"),
        row.get("low"),
        row.get("close"),
        row.get("volume"),
        row.get("turnover"),
    )
    return None if ok else reason


def clean_market_frame(frame: Any) -> Any:
    """Возвращает DataFrame только с валидными свечами.

    Импорт pandas выполняется лениво: модуль используется и в легком Bybit-клиенте,
    где нельзя тянуть аналитический стек на import-time.
    """
    import pandas as pd

    if frame is None or frame.empty:
        return frame
    out = frame.copy()
    required = ["start_time", "open", "high", "low", "close"]
    missing = [col for col in required if col not in out.columns]
    if missing:
        return out.iloc[0:0].copy()

    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    valid_mask = []
    for row in out.to_dict("records"):
        valid_mask.append(candle_problem(row) is None)
    out = out.loc[valid_mask].copy()
    if out.empty:
        return out
    out = out.dropna(subset=["start_time", "open", "high", "low", "close"])
    out = out.drop_duplicates(subset=["start_time"], keep="last")
    return out.sort_values("start_time").reset_index(drop=True)
