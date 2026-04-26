from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID


def _is_nan_like(value: Any) -> bool:
    """Определяет только скалярные NaN/NaT/pd.NA без зависимости от формы объекта."""
    try:
        import pandas as pd

        result = pd.isna(value)
        if isinstance(result, bool):
            return result
        # Для массивов/Series/DataFrame pd.isna возвращает контейнер, а не скаляр.
        # Такие объекты нормализуются отдельными ветками to_jsonable().
        return False
    except Exception:
        pass
    try:
        result = value != value
        return bool(result) if isinstance(result, bool) else False
    except Exception:
        return False


def to_jsonable(value: Any) -> Any:
    """Рекурсивно приводит данные БД/pandas/numpy к безопасному JSON-виду.

    LLM-промпты и audit-поля не должны падать из-за datetime, Decimal,
    numpy scalar или pandas Timestamp. Неизвестные типы переводятся в строку:
    это безопаснее, чем 500 Internal Server Error в пользовательском API.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and _is_nan_like(value):
            return None
        return value
    if _is_nan_like(value):
        return None
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(to_jsonable(key)): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, set):
        # Сортировка по строковому представлению делает результат стабильнее для тестов и логов.
        return [to_jsonable(item) for item in sorted(value, key=lambda item: str(item))]
    try:
        import numpy as np

        if isinstance(value, np.generic):
            return to_jsonable(value.item())
        if isinstance(value, np.ndarray):
            return to_jsonable(value.tolist())
    except ModuleNotFoundError:
        pass
    try:
        import pandas as pd

        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        if isinstance(value, pd.Timedelta):
            return str(value)
        if isinstance(value, pd.Series):
            return to_jsonable(value.to_dict())
        if isinstance(value, pd.DataFrame):
            return to_jsonable(value.to_dict(orient="records"))
    except ModuleNotFoundError:
        pass
    return str(value)
