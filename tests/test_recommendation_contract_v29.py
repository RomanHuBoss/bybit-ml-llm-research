from __future__ import annotations

from pathlib import Path

from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]


def test_price_moved_away_turns_review_entry_into_no_trade_contract():
    item = enrich_recommendation_row(base_row(last_price=110.0, last_price_time="2026-05-02T00:15:00+00:00"))

    assert item["recommendation_status"] == "missed_entry"
    assert item["trade_direction"] == "no_trade"
    assert item["display_direction"] == "NO_TRADE"
    assert item["price_status"] == "moved_away"
    assert item["is_actionable"] is False
    assert item["no_trade_reason"] == "price_moved_away"
    assert "Не догонять" in item["recommendation"]["recommended_action"]


def test_strategy_persistence_stores_recommendation_ttl():
    strategies = (ROOT / "app" / "strategies.py").read_text(encoding="utf-8")

    assert "def _signal_expires_at" in strategies
    assert "expires_at = _signal_expires_at(sig, interval)" in strategies
    assert "INSERT INTO signals(category, symbol, interval, strategy, direction, confidence, entry, stop_loss, take_profit, atr," in strategies
    assert "ml_probability, sentiment_score, rationale, bar_time, expires_at)" in strategies
    assert "expires_at=EXCLUDED.expires_at" in strategies


def test_latest_signal_api_joins_current_price_for_entry_drift_gate():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "latest_price AS" in api
    assert "p.last_price, p.last_price_time" in api
    assert "LEFT JOIN latest_price p ON p.category=s.category AND p.symbol=s.symbol AND p.interval=s.interval" in api
    assert "s.expires_at" in api
    assert "_recommendation_summary(recommendations)" in api
    assert "RECOMMENDATION_CONTRACT_VERSION" in api


def test_schema_v29_adds_market_data_and_ttl_constraints():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260502_v29_data_integrity_and_price_contract.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "ALTER TABLE signals ADD COLUMN IF NOT EXISTS expires_at" in source
        assert "ck_candles_positive_ohlcv" in source
        assert "ck_candles_valid_bybit_interval" in source
        assert "ck_liquidity_non_negative_metrics" in source
        assert "ck_strategy_quality_scores_ranges" in source
        assert "ck_signals_expires_after_bar" in source
        assert "idx_signals_expires_at" in source


def test_frontend_uses_server_contract_and_renders_full_queue_card():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "const contractStatus = String(contract.recommendation_status" in js
    assert "missed_entry: { level: 'reject', label: 'NO_TRADE · ENTRY УШЁЛ' }" in js
    assert "contract.recommendation_explanation" in js
    assert "candidate-metrics" in js
    assert "R/R ${fmt(rr, 2)}" in js
    assert ".candidate-metrics" in css
