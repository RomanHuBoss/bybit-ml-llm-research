from __future__ import annotations

from datetime import datetime, timedelta, timezone

import app.api as api


def test_v54_latest_quotes_use_interval_aware_freshness_contract(monkeypatch) -> None:
    old_bar_time = datetime.now(timezone.utc) - timedelta(hours=4)

    def fake_fetch_all(sql, params):
        assert "MAX_SIGNAL_AGE_HOURS" not in sql
        assert "start_time AS last_price_time" in sql
        return [
            {
                "category": "linear",
                "symbol": "BTCUSDT",
                "interval": "15",
                "last_price_time": old_bar_time,
                "bar_time": old_bar_time,
                "last_price": 100.0,
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "close": 100.0,
                "volume": 10.0,
                "turnover": 1000.0,
            }
        ]

    monkeypatch.setattr(api, "fetch_all", fake_fetch_all)

    rows = api._latest_quote_rows("linear", "15", ["BTCUSDT"])

    assert rows[0]["data_status"] == "stale"
    assert rows[0]["market_freshness"]["status"] == "stale"
    assert rows[0]["market_freshness"]["source"] == "last_price_time"
    assert rows[0]["max_age_seconds"] == 2100
    assert rows[0]["age_seconds"] > rows[0]["max_age_seconds"]


def test_v54_quality_drawdown_query_is_deterministic_for_equal_timestamps(monkeypatch) -> None:
    captured = {}

    def fake_fetch_one(sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return {"evaluated": 3, "max_drawdown_r": -1.5, "cumulative_r": 0.25, "expectancy_r": 0.083333}

    monkeypatch.setattr(api, "fetch_one", fake_fetch_one)

    payload = api._quality_drawdown_payload("linear", "15")

    assert payload["evaluated"] == 3
    assert payload["max_drawdown_r"] == -1.5
    assert captured["params"] == ("linear", "15")
    assert "SELECT o.signal_id, o.evaluated_at" in captured["sql"]
    assert "OVER (ORDER BY evaluated_at, signal_id) AS peak_r" in captured["sql"]
    assert captured["sql"].count("AS peak_r") == 1

from pathlib import Path

from app.trade_contract import OPERATOR_NEXT_ACTION_EXTENSION, enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]


def test_v54_actionable_contract_exposes_primary_next_action_without_auto_order() -> None:
    now = datetime(2026, 5, 5, 16, 0, tzinfo=timezone.utc)
    item = enrich_recommendation_row(
        base_row(
            operator_action="REVIEW_ENTRY",
            operator_quality_mode="provisional",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            atr=1.0,
            last_price=100.01,
            last_price_time="2026-05-05T15:55:00+00:00",
            bar_time="2026-05-05T15:45:00+00:00",
            created_at="2026-05-05T15:46:00+00:00",
            expires_at="2026-05-05T17:00:00+00:00",
            spread_pct=0.01,
            turnover_24h=50_000_000.0,
            open_interest_value=30_000_000.0,
            funding_rate=0.0001,
            rationale={"volume_zscore": 0.5, "votes": [{"name": "ema", "direction": "long", "impact": "positive"}]},
        ),
        now=now,
    )
    contract = item["recommendation"]

    assert OPERATOR_NEXT_ACTION_EXTENSION in contract["compatible_extensions"]
    assert contract["operator_next_action_extension"] == OPERATOR_NEXT_ACTION_EXTENSION
    assert contract["primary_next_action"]["action"] == "paper_opened"
    assert "не отправляет ордер" in contract["primary_next_action"]["detail"]
    assert any(action["action"] == "paper_opened" for action in contract["next_actions"])
    assert contract["contract_health"]["ok"] is True


def test_v54_metadata_frontend_and_sql_publish_quote_and_next_action_contracts() -> None:
    metadata = api._recommendation_contract_metadata()
    frontend = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260505_v54_quote_freshness_and_quality_drawdown.sql").read_text(encoding="utf-8")

    assert metadata["operator_next_action_extension"] == OPERATOR_NEXT_ACTION_EXTENSION
    assert metadata["quote_freshness_audit_view"] == "v_market_quote_freshness_audit_v54"
    assert metadata["recommendation_quality_drawdown_view"] == "v_recommendation_quality_drawdown_v54"
    assert "primary_next_action" in metadata["required_recommendation_fields"]
    assert "contract.primary_next_action?.label" in frontend
    assert "primary-next-action" in css
    for source in (schema, migration):
        assert "v_market_quote_freshness_audit_v54" in source
        assert "v_recommendation_quality_drawdown_v54" in source
        assert "ORDER BY evaluated_at, signal_id" in source
