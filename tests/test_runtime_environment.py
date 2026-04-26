from __future__ import annotations


def test_runtime_sets_loky_cpu_count_when_missing(monkeypatch):
    import app.runtime as runtime

    monkeypatch.delenv("LOKY_MAX_CPU_COUNT", raising=False)
    monkeypatch.delenv("ML_MAX_CPU_COUNT", raising=False)
    monkeypatch.setattr(runtime, "_dotenv_value", lambda _key: None)
    monkeypatch.setattr(runtime.os, "cpu_count", lambda: 8)

    runtime.configure_runtime_environment()

    assert runtime.os.environ["LOKY_MAX_CPU_COUNT"] == "4"


def test_runtime_preserves_explicit_loky_cpu_count(monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("LOKY_MAX_CPU_COUNT", "3")
    monkeypatch.setenv("ML_MAX_CPU_COUNT", "8")

    runtime.configure_runtime_environment()

    assert runtime.os.environ["LOKY_MAX_CPU_COUNT"] == "3"


def test_runtime_uses_ml_max_cpu_count_fallback(monkeypatch):
    import app.runtime as runtime

    monkeypatch.delenv("LOKY_MAX_CPU_COUNT", raising=False)
    monkeypatch.setenv("ML_MAX_CPU_COUNT", "4")
    monkeypatch.setattr(runtime, "_dotenv_value", lambda _key: None)

    runtime.configure_runtime_environment()

    assert runtime.os.environ["LOKY_MAX_CPU_COUNT"] == "4"


def test_runtime_sets_numeric_thread_limits_when_missing(monkeypatch):
    import app.runtime as runtime

    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runtime.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(runtime, "_dotenv_value", lambda _key: None)
    monkeypatch.delenv("LOKY_MAX_CPU_COUNT", raising=False)
    monkeypatch.delenv("ML_MAX_CPU_COUNT", raising=False)

    runtime.configure_runtime_environment()

    assert runtime.os.environ["OPENBLAS_NUM_THREADS"] == "4"
    assert runtime.os.environ["OMP_NUM_THREADS"] == "4"
    assert runtime.os.environ["MKL_NUM_THREADS"] == "4"
    assert runtime.os.environ["NUMEXPR_NUM_THREADS"] == "4"


def test_runtime_preserves_explicit_numeric_thread_limits(monkeypatch):
    import app.runtime as runtime

    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "2")
    monkeypatch.setenv("OMP_NUM_THREADS", "3")
    monkeypatch.setenv("MKL_NUM_THREADS", "5")
    monkeypatch.setenv("NUMEXPR_NUM_THREADS", "7")
    monkeypatch.setattr(runtime.os, "cpu_count", lambda: 16)

    runtime.configure_runtime_environment()

    assert runtime.os.environ["OPENBLAS_NUM_THREADS"] == "2"
    assert runtime.os.environ["OMP_NUM_THREADS"] == "3"
    assert runtime.os.environ["MKL_NUM_THREADS"] == "5"
    assert runtime.os.environ["NUMEXPR_NUM_THREADS"] == "7"
