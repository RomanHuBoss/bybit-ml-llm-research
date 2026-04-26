from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_sitecustomize_sets_loky_before_project_import() -> None:
    code = "import os; print(os.environ.get('LOKY_MAX_CPU_COUNT'))"
    env = os.environ.copy()
    env.pop("LOKY_MAX_CPU_COUNT", None)
    env.pop("ML_MAX_CPU_COUNT", None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip().isdigit()
    assert int(result.stdout.strip()) >= 1


def test_sitecustomize_suppresses_known_loky_warning() -> None:
    code = textwrap.dedent(
        r'''
        import warnings
        warnings.warn_explicit(
            "Could not find the number of physical cores for the following reason:\n[WinError 2] test",
            UserWarning,
            "joblib/externals/loky/backend/context.py",
            136,
            module="joblib.externals.loky.backend.context",
        )
        print("ok")
        '''
    )
    env = os.environ.copy()
    env.pop("LOKY_MAX_CPU_COUNT", None)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "ok"
    assert "Could not find the number of physical cores" not in result.stderr
