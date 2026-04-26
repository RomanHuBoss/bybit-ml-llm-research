from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


MIN_PYTHON = (3, 10)


def project_root() -> Path:
    return Path(__file__).resolve().parent


def venv_python_path(venv_dir: Path) -> Path:
    """Возвращает путь к Python внутри venv с учетом различий Windows/Linux."""
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def run_command(command: list[str], cwd: Path) -> None:
    printable = " ".join(command)
    print(f"\n$ {printable}")
    subprocess.run(command, cwd=str(cwd), check=True)


def ensure_supported_python(python_exe: str) -> None:
    code = (
        "import sys; "
        f"raise SystemExit(0 if sys.version_info >= {MIN_PYTHON!r} else 1)"
    )
    result = subprocess.run([python_exe, "-c", code], check=False)
    if result.returncode != 0:
        raise SystemExit(
            f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+; "
            f"выбранный интерпретатор не подходит: {python_exe}"
        )


def ensure_env_file(root: Path) -> None:
    example = root / ".env.example"
    target = root / ".env"
    if target.exists() or not example.exists():
        return
    shutil.copyfile(example, target)
    print("Создан .env из .env.example. Перед инициализацией БД проверьте параметры PostgreSQL.")


def create_venv(root: Path, python_exe: str, venv_dir: Path) -> Path:
    if not venv_dir.exists():
        run_command([python_exe, "-m", "venv", str(venv_dir)], root)
    py = venv_python_path(venv_dir)
    if not py.exists():
        raise SystemExit(f"Виртуальное окружение создано некорректно: не найден {py}")
    return py


def install_requirements(root: Path, python_exe: Path | str, upgrade_pip: bool) -> None:
    requirements = root / "requirements.txt"
    if not requirements.exists():
        raise SystemExit("Не найден requirements.txt")
    py = str(python_exe)
    if upgrade_pip:
        run_command([py, "-m", "pip", "install", "--upgrade", "pip"], root)
    run_command([py, "-m", "pip", "install", "-r", str(requirements)], root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Кроссплатформенная установка Bybit ML/LLM Research Lab."
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Интерпретатор Python для создания .venv. По умолчанию используется текущий Python.",
    )
    parser.add_argument(
        "--venv-dir",
        default=".venv",
        help="Каталог виртуального окружения. По умолчанию .venv.",
    )
    parser.add_argument(
        "--no-venv",
        action="store_true",
        help="Не создавать .venv и ставить зависимости в текущий интерпретатор.",
    )
    parser.add_argument(
        "--no-upgrade-pip",
        action="store_true",
        help="Не обновлять pip перед установкой зависимостей.",
    )
    parser.add_argument(
        "--no-env-copy",
        action="store_true",
        help="Не создавать .env из .env.example.",
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="После установки выполнить python -m app.init_db. Нужен доступный PostgreSQL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = project_root()
    python_exe = args.python

    ensure_supported_python(python_exe)

    if args.no_venv:
        runtime_python: Path | str = python_exe
    else:
        runtime_python = create_venv(root, python_exe, root / args.venv_dir)

    install_requirements(root, runtime_python, upgrade_pip=not args.no_upgrade_pip)

    if not args.no_env_copy:
        ensure_env_file(root)

    if args.init_db:
        # Инициализация БД намеренно отдельная: при неверном .env ошибка должна быть явной.
        run_command([str(runtime_python), "-m", "app.init_db"], root)

    print("\nУстановка завершена.")
    print("Дальше: проверьте .env, затем выполните: python run.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
