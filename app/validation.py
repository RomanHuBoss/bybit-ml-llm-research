from __future__ import annotations

import re

from .config import settings

VALID_CATEGORIES = {"linear", "inverse", "spot"}
VALID_INTERVALS = {"1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"}
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,30}$")


def normalize_category(category: str) -> str:
    value = (category or "").strip().lower()
    if value not in VALID_CATEGORIES:
        raise ValueError(f"Недопустимая категория Bybit: {category!r}")
    return value


def normalize_interval(interval: str) -> str:
    value = (interval or "").strip().upper()
    if value in {"1D", "DAY"}:
        value = "D"
    if value not in VALID_INTERVALS:
        raise ValueError(f"Недопустимый interval Bybit: {interval!r}")
    return value


def normalize_symbol(symbol: str) -> str:
    value = (symbol or "").strip().upper().replace("-", "")
    if not SYMBOL_RE.fullmatch(value):
        raise ValueError(f"Недопустимый символ: {symbol!r}")
    return value


def normalize_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for symbol in symbols:
        value = normalize_symbol(symbol)
        if value not in out:
            out.append(value)
    if not out:
        raise ValueError("Список symbols пуст")
    if len(out) > settings.max_symbols_per_request:
        raise ValueError(f"Слишком много symbols: {len(out)} > {settings.max_symbols_per_request}")
    return out


def bounded_int(value: int, name: str, minimum: int, maximum: int) -> int:
    value = int(value)
    if value < minimum or value > maximum:
        raise ValueError(f"{name} должен быть в диапазоне [{minimum}; {maximum}]")
    return value
