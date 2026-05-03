from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v34_no_trade_decision_snapshot_is_explicit():
    from app.trade_contract import RECOMMENDATION_CONTRACT_VERSION, no_trade_decision_snapshot

    snap = no_trade_decision_snapshot(reason="Нет валидных сетапов", category="linear")

    assert snap["contract_version"] == RECOMMENDATION_CONTRACT_VERSION == "recommendation_v37"
    assert snap["trade_direction"] == "no_trade"
    assert snap["display_direction"] == "NO_TRADE"
    assert snap["is_actionable"] is False
    assert snap["risk_reward"] is None
    assert snap["next_actions"]
    assert "Нет валидных сетапов" in snap["recommendation_explanation"]


def test_v34_active_recommendations_returns_no_trade_snapshot_on_empty(monkeypatch):
    import app.api as api

    monkeypatch.setattr(api, "latest_signals", lambda **kwargs: {"ok": True, "category": "linear", "entry_interval": "15", "signals": []})

    payload = api.api_active_recommendations(category="linear", limit=10)

    assert payload["ok"] is True
    assert payload["recommendations"] == []
    assert payload["market_state"]["status"] == "no_trade"
    assert payload["decision_snapshot"]["contract_version"] == "recommendation_v37"
    assert payload["decision_snapshot"]["trade_direction"] == "no_trade"


def test_v34_quality_endpoint_exposes_drawdown_and_outcome_status_counts(monkeypatch):
    import app.api as api

    def fake_fetch_one(query, params=None):
        text = str(query)
        if "WITH ordered AS" in text:
            return {"evaluated": 3, "max_drawdown_r": -1.0, "cumulative_r": 1.2, "expectancy_r": 0.4}
        return {"evaluated": 3, "average_r": 0.4, "winrate": 0.66, "profit_factor": 2.2, "avg_mfe_r": 1.1, "avg_mae_r": -0.4}

    def fake_fetch_all(query, params=None):
        text = str(query)
        if "GROUP BY o.outcome_status" in text:
            return [{"outcome_status": "hit_take_profit", "count": 2}, {"outcome_status": "hit_stop_loss", "count": 1}]
        return []

    monkeypatch.setattr(api, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(api, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(api, "quality_summary", lambda category: {"total": 0})

    payload = api.api_recommendation_quality(category="linear")

    assert payload["ok"] is True
    assert payload["recommendation_drawdown"]["max_drawdown_r"] == -1.0
    assert payload["recommendation_drawdown"]["expectancy_r"] == 0.4
    assert payload["outcome_status_counts"][0]["outcome_status"] == "hit_take_profit"


def test_v34_frontend_renders_no_trade_contract_card():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for fragment in [
        "decisionSnapshot",
        "function noTradeSnapshotHtml",
        "NO_TRADE состояние",
        "data.decision_snapshot",
        "queue.innerHTML = noTradeSnapshotHtml()",
    ]:
        assert fragment in js
    for fragment in [
        ".no-trade-contract",
        ".no-trade-contract__grid",
        ".no-trade-contract__actions",
    ]:
        assert fragment in css


def test_v34_schema_and_migration_have_stale_write_guard_and_quality_view():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260503_v34_recommendation_decision_snapshot.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "NEW.expires_at <= NOW()" in source
        assert "v_recommendation_outcome_quality_v34" in source
        assert "max_drawdown_r" in source
        assert "idx_recommendation_outcomes_signal_time_v34" in source
