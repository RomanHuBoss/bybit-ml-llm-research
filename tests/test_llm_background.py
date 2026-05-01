from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_payload_hash_is_stable_for_jsonable_payload():
    from app.llm_background import payload_hash

    left = {"symbol": "BTCUSDT", "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "score": 1}
    right = {"score": 1, "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc), "symbol": "BTCUSDT"}

    assert payload_hash(left) == payload_hash(right)


def test_candidates_needing_llm_skips_fresh_existing_evaluation(monkeypatch):
    import app.llm_background as bg

    payload = {
        "id": 10,
        "symbol": "BTCUSDT",
        "interval": "15",
        "strategy": "regime_adaptive_combo",
        "direction": "long",
        "confidence": 0.7,
    }
    current_hash = bg.payload_hash(bg._brief_payload(payload))
    fresh = {
        **payload,
        "llm_status": "ok",
        "llm_payload_hash": current_hash,
        "llm_updated_at": datetime.now(timezone.utc) - timedelta(minutes=5),
    }

    monkeypatch.setattr(bg, "rank_candidates_multi", lambda *_args, **_kwargs: [fresh])

    assert bg.candidates_needing_llm() == []


def test_candidates_needing_llm_selects_missing_or_stale_evaluation(monkeypatch):
    import app.llm_background as bg

    stale = {
        "id": 11,
        "symbol": "ETHUSDT",
        "interval": "15",
        "strategy": "regime_adaptive_combo",
        "direction": "short",
        "confidence": 0.7,
        "llm_status": "ok",
        "llm_payload_hash": "old-hash",
        "llm_updated_at": datetime.now(timezone.utc) - timedelta(days=1),
    }

    monkeypatch.setattr(bg, "rank_candidates_multi", lambda *_args, **_kwargs: [stale])

    selected = bg.candidates_needing_llm()

    assert len(selected) == 1
    assert selected[0]["id"] == 11
    assert "_llm_payload" in selected[0]
    assert "_llm_payload_hash" in selected[0]


def test_ensure_llm_schema_contains_upgrade_migrations():
    from pathlib import Path

    source = Path("app/llm_background.py").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS payload_hash" in source
    assert "ADD COLUMN IF NOT EXISTS interval" in source
    assert "ADD COLUMN IF NOT EXISTS symbol" in source
    assert "DELETE FROM llm_evaluations a" in source
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_llm_evaluations_signal_id" in source
