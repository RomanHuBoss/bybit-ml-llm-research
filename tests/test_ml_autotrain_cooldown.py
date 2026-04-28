from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ml_autotrain_has_vm_safe_throttles_without_importing_sklearn():
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    ml = (ROOT / "app" / "ml.py").read_text(encoding="utf-8")
    signal_background = (ROOT / "app" / "signal_background.py").read_text(encoding="utf-8")

    assert 'ML_AUTO_TRAIN_MAX_MODELS_PER_CYCLE", 2' in config
    assert 'ML_AUTO_TRAIN_FAILURE_COOLDOWN_HOURS", 6' in config
    assert "_AUTO_TRAIN_FAILURES" in ml
    assert "skipped_failure_cooldown" in ml
    assert "failure_cooldown_hours" in ml
    assert "failure_cooldown_hours=settings.ml_auto_train_failure_cooldown_hours" in signal_background
