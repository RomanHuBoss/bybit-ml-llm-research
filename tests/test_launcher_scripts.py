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
