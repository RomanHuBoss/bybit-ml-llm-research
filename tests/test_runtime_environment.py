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
