from __future__ import annotations

from pathlib import Path

from app.trade_contract import RECOMMENDATION_CONTRACT_VERSION, enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]


def test_v35_contract_version_and_terminal_outcome_payload():
    item = enrich_recommendation_row(
        base_row(
            outcome_status="hit_take_profit",
            outcome_evaluated_at="2026-05-03T08:00:00+00:00",
            exit_time="2026-05-03T07:45:00+00:00",
            exit_price=112.0,
            realized_r=1.8,
            max_favorable_excursion_r=2.1,
            max_adverse_excursion_r=-0.3,
            outcome_notes={"source": "test"},
        )
    )
    contract = item["recommendation"]

    assert RECOMMENDATION_CONTRACT_VERSION == "recommendation_v37"
    assert contract["contract_version"] == "recommendation_v37"
    assert contract["outcome"]["status"] == "hit_take_profit"
    assert contract["outcome"]["is_terminal"] is True
    assert contract["outcome"]["realized_r"] == 1.8


def test_v35_active_sql_excludes_expired_and_terminal_outcomes():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "AND expires_at IS NOT NULL" in api
    assert "AND expires_at > NOW()" in api
    assert "FROM recommendation_outcomes ro" in api
    assert "ro.outcome_status <> 'open'" in api


def test_v35_quality_sql_uses_only_terminal_outcomes():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert api.count("AND o.outcome_status <> 'open'") >= 7
    assert "confidence_bucket" in api
    assert "by_symbol" in api
    assert "by_strategy" in api


def test_v35_schema_and_migration_publish_active_and_terminal_views():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260503_v35_active_recommendation_integrity.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "idx_recommendation_outcomes_terminal_v35" in source
        assert "idx_signals_active_contract_v35" in source
        assert "ck_recommendation_outcomes_terminal_price_v35" in source
        assert "v_active_recommendation_contract_v35" in source
        assert "v_recommendation_quality_terminal_v35" in source
        assert "s.expires_at > NOW()" in source
        assert "o.outcome_status <> 'open'" in source


def test_v35_initial_schema_has_no_duplicate_profit_factor_column():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    create_backtest = schema.split("CREATE TABLE IF NOT EXISTS backtest_runs", 1)[1].split(");", 1)[0]

    assert create_backtest.count("profit_factor NUMERIC") == 1


def test_v35_frontend_renders_outcome_contract():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "function outcomeContractHtml" in js
    assert "Исход рекомендации" in js
    assert "contract.outcome" in js
    assert ".outcome-contract" in css
