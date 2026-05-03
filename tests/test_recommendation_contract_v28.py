from __future__ import annotations

from pathlib import Path

from app.trade_contract import enrich_recommendation_row, validate_trade_levels

ROOT = Path(__file__).resolve().parents[1]


def base_row(**overrides):
    row = {
        "id": 42,
        "symbol": "BTCUSDT",
        "interval": "15",
        "strategy": "ema_pullback_trend",
        "direction": "long",
        "confidence": 0.67,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "atr": 1.5,
        "bar_time": "2026-05-02T00:00:00+00:00",
        "fresh": True,
        "operator_action": "REVIEW_ENTRY",
        "operator_label": "РУЧНАЯ ПРОВЕРКА ВХОДА",
        "operator_hard_reasons": [],
        "operator_warnings": [],
        "operator_evidence_notes": [{"code": "strategy_approved", "title": "Стратегия approved", "detail": "quality passed"}],
        "quality_status": "APPROVED",
        "quality_score": 88,
    }
    row.update(overrides)
    return row


def test_trade_level_validator_blocks_impossible_long_and_short():
    assert validate_trade_levels("long", 100, 101, 105)["reason"] == "long_levels_not_ordered"
    assert validate_trade_levels("short", 100, 99, 95)["reason"] == "short_levels_not_ordered"
    valid = validate_trade_levels("short", 100, 103, 94)
    assert valid["valid"] is True
    assert round(valid["risk_reward"], 2) == 2.0


def test_enriched_contract_contains_actionable_ticket_fields():
    item = enrich_recommendation_row(base_row())

    assert item["recommendation_status"] == "review_entry"
    assert item["trade_direction"] == "long"
    assert item["display_direction"] == "LONG"
    assert item["confidence_score"] == 67
    assert item["risk_pct"] == 0.02
    assert item["expected_reward_pct"] == 0.04
    assert item["risk_reward"] == 2.0
    assert item["expires_at"]
    assert "Entry 100" in item["recommendation_explanation"]
    assert "invalidation_condition" in item["recommendation"]
    assert item["signal_breakdown"]["risk"]["risk_reward"] == 2.0


def test_enriched_contract_turns_invalid_or_blocked_rows_into_no_trade():
    invalid = enrich_recommendation_row(base_row(stop_loss=101.0))
    assert invalid["recommendation_status"] == "invalid"
    assert invalid["trade_direction"] == "no_trade"
    assert invalid["is_actionable"] is False

    blocked = enrich_recommendation_row(base_row(operator_action="NO_TRADE", operator_hard_reasons=[{"code": "mtf", "title": "MTF veto", "detail": "conflict"}]))
    assert blocked["recommendation_status"] == "blocked"
    assert blocked["trade_direction"] == "no_trade"
    assert "NO_TRADE" in blocked["recommendation_explanation"]


def test_api_exposes_recommendation_oriented_contract_endpoints():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    required = [
        '"/instruments"',
        '"/quotes/latest"',
        '"/recommendations/active"',
        '"/recommendations/history"',
        '"/recommendations/quality"',
        '"/recommendations/recalculate"',
        '"/recommendations/{signal_id}"',
        '"/recommendations/{signal_id}/explanation"',
        '"/system/status"',
        '"/system/warnings"',
        "annotate_recommendations(rows)",
    ]
    for fragment in required:
        assert fragment in api


def test_schema_hardens_signal_math_and_persists_outcomes():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260502_v28_recommendation_contract.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "ck_signals_confidence_0_1" in source
        assert "ck_signals_level_side_matches_direction" in source
        assert "ck_signals_has_market_timestamp_for_trade" in source
        assert "CREATE TABLE IF NOT EXISTS recommendation_outcomes" in source
        assert "max_favorable_excursion_r" in source
        assert "max_adverse_excursion_r" in source
        assert "realized_r" in source


def test_frontend_renders_canonical_recommendation_contract_fields():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for fragment in [
        "const contract = contractFor(s)",
        "contract.trade_direction",
        "contract.recommended_action",
        "contract.expires_at",
        "contract.price_status",
        "contract.recommendation_explanation",
        "contract.invalidation_condition",
        "recommendation-contract",
    ]:
        assert fragment in js
    assert ".recommendation-contract" in css

from datetime import datetime, timezone
from app.recommendation_outcomes import evaluate_signal_outcome


def test_recommendation_outcome_evaluator_uses_stop_first_for_same_bar_ambiguity():
    signal = base_row(direction="long", entry=100.0, stop_loss=98.0, take_profit=104.0, bar_time="2026-05-02T00:00:00+00:00")
    candles = [{"start_time": "2026-05-02T00:15:00+00:00", "high": 105.0, "low": 97.5}]

    outcome = evaluate_signal_outcome(signal, candles, now=datetime(2026, 5, 2, 1, 0, tzinfo=timezone.utc))

    assert outcome["outcome_status"] == "hit_stop_loss"
    assert outcome["realized_r"] == -1.0
    assert outcome["notes"]["same_bar_stop_first"] is True


def test_recommendation_outcome_evaluator_records_take_profit_and_mfe_mae():
    signal = base_row(direction="short", entry=100.0, stop_loss=103.0, take_profit=94.0, bar_time="2026-05-02T00:00:00+00:00")
    candles = [
        {"start_time": "2026-05-02T00:15:00+00:00", "high": 101.0, "low": 97.0},
        {"start_time": "2026-05-02T00:30:00+00:00", "high": 100.0, "low": 93.5},
    ]

    outcome = evaluate_signal_outcome(signal, candles, now=datetime(2026, 5, 2, 1, 0, tzinfo=timezone.utc))

    assert outcome["outcome_status"] == "hit_take_profit"
    assert outcome["realized_r"] == 2.0
    assert outcome["max_favorable_excursion_r"] >= 2.0
    assert outcome["max_adverse_excursion_r"] < 0


def test_api_exposes_outcome_evaluation_endpoint():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    assert '"/recommendations/evaluate-outcomes"' in api
    assert "evaluate_due_recommendation_outcomes" in api
