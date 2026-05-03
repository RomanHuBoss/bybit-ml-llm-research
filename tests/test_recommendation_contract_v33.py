from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v33_similar_history_endpoint_summarizes_matching_signal(monkeypatch):
    import app.api as api

    calls: list[tuple[str, object]] = []

    def fake_fetch_one(query, params=None):
        calls.append((str(query), params))
        if "FROM signals" in str(query) and "WHERE id=%s" in str(query):
            return {
                "id": 42,
                "category": "linear",
                "symbol": "BTCUSDT",
                "interval": "15",
                "strategy": "ema_pullback_trend",
                "direction": "long",
                "confidence": 0.67,
                "bar_time": "2026-05-02T00:00:00+00:00",
            }
        return {
            "evaluated": 18,
            "average_r": 0.23,
            "winrate": 0.56,
            "profit_factor": 1.34,
            "avg_mfe_r": 1.7,
            "avg_mae_r": -0.8,
            "last_evaluated_at": "2026-05-03T00:00:00+00:00",
        }

    def fake_fetch_all(query, params=None):
        calls.append((str(query), params))
        return [
            {
                "signal_id": 11,
                "outcome_status": "hit_take_profit",
                "realized_r": 2.0,
                "max_favorable_excursion_r": 2.1,
                "max_adverse_excursion_r": -0.2,
                "confidence": 0.64,
            }
        ]

    monkeypatch.setattr(api, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(api, "fetch_all", fake_fetch_all)

    payload = api._similar_recommendation_history(42, "linear", 30)

    assert payload["ok"] is True
    assert payload["match"] == {
        "symbol": "BTCUSDT",
        "interval": "15",
        "strategy": "ema_pullback_trend",
        "direction": "long",
    }
    assert payload["summary"]["statistical_confidence"] == "low"
    assert "18" in payload["summary"]["explanation"]
    assert payload["items"][0]["outcome_status"] == "hit_take_profit"
    assert any("o.outcome_status <> 'open'" in query for query, _ in calls)


def test_v33_similar_history_api_and_frontend_contract_are_present():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for fragment in [
        '"/recommendations/{signal_id}/similar-history"',
        "_similar_recommendation_history",
        "statistical_confidence",
    ]:
        assert fragment in api
    for fragment in [
        "function similarHistoryHtml(history, signalId)",
        "async function refreshSimilarHistoryForCandidate",
        "История похожих сигналов",
        "/similar-history?category=",
    ]:
        assert fragment in js
    assert ".similar-history-table" in css


def test_v33_schema_has_operator_action_status_constraint_and_similarity_view():
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260503_v32_similar_history_and_operator_contract.sql").read_text(encoding="utf-8")

    for source in (schema, migration):
        assert "ck_recommendation_operator_actions_status_v32" in source
        assert "idx_signals_similarity_lookup_v32" in source
        assert "idx_recommendation_outcomes_terminal_v32" in source
        assert "v_recommendation_similar_history" in source
        assert "outcome_status <> 'open'" in source
