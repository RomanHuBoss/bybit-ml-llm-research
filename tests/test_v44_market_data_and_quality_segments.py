from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.recommendation_outcomes import evaluate_signal_outcome
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)


def test_v44_outcome_evaluator_skips_invalid_ohlc_and_marks_notes() -> None:
    signal = base_row(
        direction="long",
        entry=100.0,
        stop_loss=96.0,
        take_profit=108.0,
        bar_time="2026-05-05T10:00:00+00:00",
        expires_at="2026-05-05T13:00:00+00:00",
    )
    candles = [
        {"start_time": "2026-05-05T10:15:00+00:00", "open": 100.0, "high": 94.0, "low": 101.0, "close": 100.5},
        {"start_time": "2026-05-05T10:30:00+00:00", "open": 100.0, "high": 109.0, "low": 99.0, "close": 108.5},
    ]

    outcome = evaluate_signal_outcome(signal, candles, now=NOW)

    assert outcome["outcome_status"] == "hit_take_profit"
    assert outcome["bars_observed"] == 1
    assert outcome["notes"]["data_quality_issue"] is True
    assert outcome["notes"]["skipped_invalid_candles"] == 1
    assert outcome["notes"]["data_quality_reason"] == "invalid_ohlc_candles_skipped"


def test_v44_outcome_expiry_without_valid_bars_is_explicit_data_quality_issue() -> None:
    signal = base_row(
        direction="short",
        entry=100.0,
        stop_loss=105.0,
        take_profit=90.0,
        bar_time="2026-05-05T08:00:00+00:00",
        expires_at="2026-05-05T09:00:00+00:00",
    )
    candles = [
        {"start_time": "2026-05-05T08:15:00+00:00", "open": 100.0, "high": 0.0, "low": 98.0, "close": 99.0},
        {"start_time": "2026-05-05T08:30:00+00:00", "open": 100.0, "high": 97.0, "low": 101.0, "close": 99.0},
    ]

    outcome = evaluate_signal_outcome(signal, candles, now=NOW)

    assert outcome["outcome_status"] == "expired"
    assert outcome["bars_observed"] == 0
    assert outcome["notes"]["data_quality_issue"] is True
    assert outcome["notes"]["no_valid_bars_after_signal"] is True


def test_v44_quality_api_exposes_operator_segments_and_sample_context() -> None:
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    for fragment in [
        '"by_timeframe"',
        '"by_direction"',
        '"by_signal_type"',
        '"sample_confidence"',
        '"sample_warning"',
        'operator_guidance',
    ]:
        assert fragment in api


def test_v44_frontend_renders_quality_segments_without_recomputing_trade() -> None:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'id="qualitySegmentsPanel"' in html
    assert 'id="qualitySegmentsBody"' in html
    assert 'refreshRecommendationQuality' in js
    assert '/api/recommendations/quality' in js
    assert 'renderQualitySegmentRows' in js
    assert '.quality-segment-card' in css
    assert 'return String(value ?? \'\')\n  return String(value ?? \'\')' not in js


def test_v44_migration_adds_market_data_integrity_audit_views() -> None:
    migration = (ROOT / "sql" / "migrations" / "20260505_v44_market_data_integrity_and_quality_segments.sql").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")

    for source in (migration, schema):
        assert "ck_candles_ohlc_integrity_v44" in source
        assert "ck_liquidity_snapshot_prices_v44" in source
        assert "v_recommendation_quality_segments_v44" in source
        assert "v_recommendation_integrity_audit_v44" in source
