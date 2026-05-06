from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v57_assets_and_operator_decision_first_shell_are_enabled():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "operator-cockpit-v57" in html
    assert "styles.css?v=trading-cockpit-v57" in html
    assert "app.js?v=trading-cockpit-v57" in html
    assert "decisionBriefPanel" in html
    assert "Operator next action" in html
    assert "decisionDetailsDialog" in html
    assert "V57 operator decision-first cockpit" in css


def test_v57_frontend_has_decision_first_helpers_without_recalculating_trade_math():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function primaryNextActionFor" in js
    assert "function renderDecisionBriefPanel" in js
    assert "function renderDecisionDetailsDialog" in js
    assert "function openDecisionDetailsDialog" in js
    assert "frontend_may_recalculate === false" in js
    assert "setText('nextActionChip'" in js
    assert "contract.entry" in js
    assert "contract.stop_loss" in js
    assert "contract.take_profit" in js


def test_v57_backend_and_sql_expose_operator_ui_audit_contract():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    migration = (ROOT / "sql" / "migrations" / "20260506_v57_operator_decision_first_ui_contract.sql").read_text(encoding="utf-8")

    assert "v_operator_decision_first_ui_contract_v57" in api
    assert "CREATE OR REPLACE VIEW v_operator_decision_first_ui_contract_v57" in schema
    assert "operator_explanation_missing_v57" in migration
    assert "operator_next_action_missing_v57" in migration
    assert "operator_signal_breakdown_missing_v57" in migration

    assert "signal_score" not in migration
    assert "active IS TRUE" not in migration
    assert "recommendation_outcomes" in migration
