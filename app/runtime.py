from __future__ import annotations

import os
import warnings
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]


def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def _dotenv_value(key: str) -> str | None:
    """Читает отдельное значение из .env без импорта тяжелых зависимостей проекта."""
    path = BASE_DIR / ".env"
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
    Возвращает дефолт, который не провоцирует loky на вызов отсутствующего wmic.

    Если значение равно числу логических ядер, часть версий joblib/loky все равно
    пытается определить физические ядра через wmic. Поэтому автоматический дефолт
    намеренно меньше числа логических ядер и ограничен 4 потоками.
    """
    logical = max(1, os.cpu_count() or 1)
    if logical <= 1:
        return 1
    return max(1, min(4, logical - 1))


def _suppress_known_loky_warning() -> None:
    """Подавляет только известный warning loky об отсутствующем wmic на Windows."""
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


def configure_runtime_environment() -> None:
    """
    Настраивает безопасные переменные окружения до импорта sklearn/joblib.

    На современных Windows wmic часто отсутствует. joblib/loky при попытке
    определить физические ядра вызывает wmic и пишет шумный warning, хотя затем
    все равно использует число логических ядер. Поэтому мы явно задаем
    LOKY_MAX_CPU_COUNT заранее и дополнительно ставим точечный фильтр warning.
    Пользовательское значение из окружения или .env имеет приоритет.
    """
    _suppress_known_loky_warning()

    if _parse_positive_int(os.environ.get("LOKY_MAX_CPU_COUNT")) is not None:
        return

    explicit = (
        _parse_positive_int(os.environ.get("ML_MAX_CPU_COUNT"))
        or _parse_positive_int(_dotenv_value("LOKY_MAX_CPU_COUNT"))
        or _parse_positive_int(_dotenv_value("ML_MAX_CPU_COUNT"))
    )
    cpu_count = explicit or _safe_default_loky_cpu_count()
    os.environ["LOKY_MAX_CPU_COUNT"] = str(cpu_count)
