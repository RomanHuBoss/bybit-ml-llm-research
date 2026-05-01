from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


def venv_python_path(venv_dir: Path) -> Path | None:
    """Ищет Python виртуального окружения без привязки к ОС."""
    candidates = []
    if sys.platform.startswith("win"):
        candidates.append(venv_dir / "Scripts" / "python.exe")
    else:
        candidates.append(venv_dir / "bin" / "python")
    candidates.extend([venv_dir / "Scripts" / "python.exe", venv_dir / "bin" / "python"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def runtime_python(no_venv: bool = False) -> str:
    if no_venv:
        return sys.executable
    py = venv_python_path(PROJECT_ROOT / ".venv")
    return str(py if py else sys.executable)


def parse_env_file(path: Path) -> dict[str, str]:
    """Минимальный dotenv-парсер для параметров запуска без импорта зависимостей проекта."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def env_value(key: str, default: str) -> str:
    file_values = parse_env_file(PROJECT_ROOT / ".env")
    return os.getenv(key) or file_values.get(key) or default



def _parse_positive_int(raw: str | None) -> int | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        value = int(raw.strip())
    except ValueError:
        return None
    return value if value > 0 else None


def safe_default_loky_cpu_count() -> str:
    """Возвращает дефолт, который не запускает wmic-проверку joblib/loky."""
    logical = max(1, os.cpu_count() or 1)
    if logical <= 1:
        return "1"
    return str(max(1, min(4, logical - 1)))


def subprocess_env() -> dict[str, str]:
    """Готовит окружение для дочерних процессов, включая uvicorn --reload."""
    env = os.environ.copy()
    file_values = parse_env_file(PROJECT_ROOT / ".env")
    configured = (
        _parse_positive_int(env.get("LOKY_MAX_CPU_COUNT"))
        or _parse_positive_int(file_values.get("LOKY_MAX_CPU_COUNT"))
        or _parse_positive_int(env.get("ML_MAX_CPU_COUNT"))
        or _parse_positive_int(file_values.get("ML_MAX_CPU_COUNT"))
    )
    env["LOKY_MAX_CPU_COUNT"] = str(configured) if configured else safe_default_loky_cpu_count()
    # Health-checks must work in archives/read-only checkouts too. Python bytecode
    # is not needed for diagnostics and can fail when __pycache__ is not writable.
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    # External pytest plugins from a global Python installation can slow down or
    # change this project's tests. Keep launcher diagnostics reproducible.
    env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    return env


def python_sources() -> list[Path]:
    """Возвращает проверяемые Python-файлы без записи __pycache__."""
    files: set[Path] = set()
    for root_name in ("app", "tests"):
        root = PROJECT_ROOT / root_name
        if root.exists():
            files.update(
                path
                for path in root.rglob("*.py")
                if "__pycache__" not in path.parts and ".pytest_cache" not in path.parts
            )
    for name in ("install.py", "run.py", "sitecustomize.py"):
        path = PROJECT_ROOT / name
        if path.exists():
            files.add(path)
    return sorted(files)


def syntax_check() -> int:
    """Проверяет синтаксис проекта без compileall и без записи в файловую систему."""
    failures: list[str] = []
    sources = python_sources()
    for path in sources:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(f"{path.relative_to(PROJECT_ROOT)}:{exc.lineno}:{exc.offset}: {exc.msg}")
        except OSError as exc:
            failures.append(f"{path.relative_to(PROJECT_ROOT)}: {exc}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        return 1
    print(f"Syntax OK: {len(sources)} Python files")
    return 0


def run_command(command: list[str]) -> int:
    printable = " ".join(command)
    print(f"\n$ {printable}")
    return subprocess.run(command, cwd=str(PROJECT_ROOT), check=False, env=subprocess_env()).returncode


def command_server(args: argparse.Namespace) -> int:
    host = args.host or env_value("APP_HOST", "127.0.0.1")
    port = str(args.port or env_value("APP_PORT", "8000"))
    command = [
        runtime_python(args.no_venv),
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        port,
    ]
    if args.reload:
        command.append("--reload")
    return run_command(command)


def command_init_db(args: argparse.Namespace) -> int:
    # Команда не создает саму PostgreSQL-базу; она применяет schema.sql к уже настроенной БД из .env.
    return run_command([runtime_python(args.no_venv), "-m", "app.init_db"])


def command_test(args: argparse.Namespace) -> int:
    return run_command([runtime_python(args.no_venv), "-m", "pytest", "-q", "-p", "no:cacheprovider"])


def command_check(args: argparse.Namespace) -> int:
    py = runtime_python(args.no_venv)
    first = syntax_check()
    if first != 0:
        return first
    return run_command([py, "-m", "pytest", "-q", "-p", "no:cacheprovider"])


def command_doctor(args: argparse.Namespace) -> int:
    py = runtime_python(args.no_venv)
    env_exists = (PROJECT_ROOT / ".env").exists()
    req_exists = (PROJECT_ROOT / "requirements.txt").exists()
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python: {py}")
    print(f".venv найден: {(PROJECT_ROOT / '.venv').exists()}")
    print(f"requirements.txt найден: {req_exists}")
    print(f".env найден: {env_exists}")
    print(f"APP_HOST: {env_value('APP_HOST', '127.0.0.1')}")
    print(f"APP_PORT: {env_value('APP_PORT', '8000')}")
    print(f"POSTGRES_HOST: {env_value('POSTGRES_HOST', 'localhost')}")
    print(f"POSTGRES_PORT: {env_value('POSTGRES_PORT', '5432')}")
    print(f"POSTGRES_DB: {env_value('POSTGRES_DB', 'bybit_lab')}")
    print(f"POSTGRES_USER: {env_value('POSTGRES_USER', 'bybit_lab_user')}")
    print(f"ML_MAX_CPU_COUNT: {env_value('ML_MAX_CPU_COUNT', 'auto') or 'auto'}")
    print(f"LOKY_MAX_CPU_COUNT: {os.getenv('LOKY_MAX_CPU_COUNT') or env_value('LOKY_MAX_CPU_COUNT', 'auto') or 'auto'}")
    if getattr(args, "db_check", False):
        return run_command([py, "-m", "app.db_check"])
    return 0


def command_db_check(args: argparse.Namespace) -> int:
    return run_command([runtime_python(args.no_venv), "-m", "app.db_check"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Кроссплатформенный запуск Bybit ML/LLM Research Lab."
    )
    subparsers = parser.add_subparsers(dest="command")

    def add_server_parser(name: str, help_text: str) -> argparse.ArgumentParser:
        parser_obj = subparsers.add_parser(name, help=help_text)
        parser_obj.add_argument("--host", help="Host. По умолчанию APP_HOST из .env или 127.0.0.1.")
        parser_obj.add_argument("--port", type=int, help="Port. По умолчанию APP_PORT из .env или 8000.")
        parser_obj.add_argument("--no-reload", dest="reload", action="store_false", help="Отключить auto-reload.")
        parser_obj.add_argument("--no-venv", action="store_true", help="Использовать текущий Python вместо .venv.")
        parser_obj.set_defaults(func=command_server, reload=True)
        return parser_obj

    add_server_parser("server", "Запустить FastAPI/Frontend сервер.")
    # Backward-compatible alias: README and early release docs used `python run.py app`.
    # Keeping it prevents a confusing CLI failure after updating only the source archive.
    add_server_parser("app", "Alias для server: запустить FastAPI/Frontend сервер.")

    init_db = subparsers.add_parser("init-db", help="Применить sql/schema.sql к PostgreSQL из .env.")
    init_db.add_argument("--no-venv", action="store_true", help="Использовать текущий Python вместо .venv.")
    init_db.set_defaults(func=command_init_db)

    test = subparsers.add_parser("test", help="Запустить pytest.")
    test.add_argument("--no-venv", action="store_true", help="Использовать текущий Python вместо .venv.")
    test.set_defaults(func=command_test)

    check = subparsers.add_parser("check", help="Проверить компиляцию и запустить тесты.")
    check.add_argument("--no-venv", action="store_true", help="Использовать текущий Python вместо .venv.")
    check.set_defaults(func=command_check)

    doctor = subparsers.add_parser("doctor", help="Показать диагностическую информацию запуска.")
    doctor.add_argument("--no-venv", action="store_true", help="Использовать текущий Python вместо .venv.")
    doctor.add_argument("--db-check", action="store_true", help="Дополнительно проверить подключение к PostgreSQL.")
    doctor.set_defaults(func=command_doctor)

    db_check = subparsers.add_parser("db-check", help="Проверить подключение к PostgreSQL из .env.")
    db_check.add_argument("--no-venv", action="store_true", help="Использовать текущий Python вместо .venv.")
    db_check.set_defaults(func=command_db_check)

    args = parser.parse_args()
    if args.command is None:
        args = parser.parse_args(["server"])
    return args


def main() -> int:
    args = parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
