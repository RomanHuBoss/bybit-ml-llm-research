from __future__ import annotations

import sys
from pathlib import Path


def test_install_venv_python_path_is_platform_aware(tmp_path):
    import install

    py = install.venv_python_path(tmp_path / ".venv")
    if sys.platform.startswith("win"):
        assert py == tmp_path / ".venv" / "Scripts" / "python.exe"
    else:
        assert py == tmp_path / ".venv" / "bin" / "python"


def test_run_parse_env_file_handles_comments_and_quotes(tmp_path):
    import run

    env_file = tmp_path / ".env"
    env_file.write_text(
        """
# comment
APP_HOST='0.0.0.0'
APP_PORT="8010"
EMPTY=
BROKEN_LINE
POSTGRES_DB=bybit_lab
""".strip(),
        encoding="utf-8",
    )

    parsed = run.parse_env_file(env_file)

    assert parsed["APP_HOST"] == "0.0.0.0"
    assert parsed["APP_PORT"] == "8010"
    assert parsed["EMPTY"] == ""
    assert parsed["POSTGRES_DB"] == "bybit_lab"
    assert "BROKEN_LINE" not in parsed


def test_run_venv_python_path_detects_linux_layout(tmp_path):
    import run

    bin_dir = tmp_path / ".venv" / "bin"
    bin_dir.mkdir(parents=True)
    python_file = bin_dir / "python"
    python_file.write_text("", encoding="utf-8")

    assert run.venv_python_path(tmp_path / ".venv") == python_file


def test_run_db_check_command_uses_app_module(monkeypatch):
    import argparse
    import run

    captured: list[list[str]] = []

    def fake_run_command(command: list[str]) -> int:
        captured.append(command)
        return 0

    monkeypatch.setattr(run, "run_command", fake_run_command)
    monkeypatch.setattr(run, "runtime_python", lambda no_venv=False: "python")

    rc = run.command_db_check(argparse.Namespace(no_venv=False))

    assert rc == 0
    assert captured == [["python", "-m", "app.db_check"]]


def test_run_subprocess_env_sets_safe_loky_default(monkeypatch):
    import run

    monkeypatch.delenv("LOKY_MAX_CPU_COUNT", raising=False)
    monkeypatch.delenv("ML_MAX_CPU_COUNT", raising=False)
    monkeypatch.setattr(run, "parse_env_file", lambda _path: {})
    monkeypatch.setattr(run.os, "cpu_count", lambda: 8)

    env = run.subprocess_env()

    assert env["LOKY_MAX_CPU_COUNT"] == "4"


def test_run_subprocess_env_uses_ml_max_cpu_count(monkeypatch):
    import run

    monkeypatch.delenv("LOKY_MAX_CPU_COUNT", raising=False)
    monkeypatch.setenv("ML_MAX_CPU_COUNT", "2")
    monkeypatch.setattr(run, "parse_env_file", lambda _path: {})

    env = run.subprocess_env()

    assert env["LOKY_MAX_CPU_COUNT"] == "2"


def test_run_check_uses_syntax_parser_and_pytest_without_cache(monkeypatch):
    import argparse
    import run

    calls: list[list[str]] = []

    monkeypatch.setattr(run, "runtime_python", lambda no_venv=False: "python")
    monkeypatch.setattr(run, "syntax_check", lambda: 0)
    monkeypatch.setattr(run, "run_command", lambda command: calls.append(command) or 0)

    rc = run.command_check(argparse.Namespace(no_venv=False))

    assert rc == 0
    assert calls == [["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]]


def test_run_subprocess_env_disables_bytecode_cache(monkeypatch):
    import run

    monkeypatch.delenv("LOKY_MAX_CPU_COUNT", raising=False)
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr(run, "parse_env_file", lambda _path: {})
    monkeypatch.setattr(run.os, "cpu_count", lambda: 4)

    env = run.subprocess_env()

    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
