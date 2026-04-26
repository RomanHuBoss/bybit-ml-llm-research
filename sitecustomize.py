from __future__ import annotations

import os
import warnings
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _dotenv_value(key: str) -> str | None:
    """Минимально читает .env на самом раннем этапе запуска Python."""
    path = PROJECT_ROOT / ".env"
    if not path.exists():
        return None
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def _safe_default_loky_cpu_count() -> int:
    """
    Возвращает безопасный дефолт для joblib/loky на Windows.

    Важно: если LOKY_MAX_CPU_COUNT равен числу логических ядер, loky все равно
    может попытаться определить физические ядра через отсутствующий wmic. Поэтому
    автоматический дефолт намеренно меньше os.cpu_count(), но не больше 4, чтобы
    не создавать лишнюю нагрузку на локальный research-стенд.
    """
    logical = max(1, os.cpu_count() or 1)
    if logical <= 1:
        return 1
    return max(1, min(4, logical - 1))


def _configure_loky_cpu_count() -> None:
    """
    Защищает Windows-запуск от предупреждения joblib/loky об отсутствующем wmic.

    Python импортирует sitecustomize до запуска модулей проекта, поэтому это место
    срабатывает раньше sklearn/joblib даже при прямом запуске uvicorn.
    """
    if _parse_positive_int(os.environ.get("LOKY_MAX_CPU_COUNT")) is not None:
        return

    explicit = (
        _parse_positive_int(os.environ.get("ML_MAX_CPU_COUNT"))
        or _parse_positive_int(_dotenv_value("LOKY_MAX_CPU_COUNT"))
        or _parse_positive_int(_dotenv_value("ML_MAX_CPU_COUNT"))
    )
    os.environ["LOKY_MAX_CPU_COUNT"] = str(explicit or _safe_default_loky_cpu_count())


def _suppress_known_loky_warning() -> None:
    """
    Резервное подавление точечного предупреждения loky.

    В отдельных связках Windows/Python/joblib проверка физических ядер может
    запускаться даже при заданном LOKY_MAX_CPU_COUNT. Подавляем только известный
    диагностический warning loky, не скрывая остальные предупреждения проекта.
    """
    warnings.filterwarnings(
        "ignore",
        message=r"Could not find the number of physical cores.*",
        category=UserWarning,
        module=r"joblib\.externals\.loky\.backend\.context",
    )
    warnings.filterwarnings(
        "ignore",
        message=r"Could not find the number of physical cores.*",
        category=UserWarning,
    )


_configure_loky_cpu_count()
_suppress_known_loky_warning()
