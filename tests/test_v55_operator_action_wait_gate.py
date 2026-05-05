from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]


def test_v55_wait_contract_does_not_offer_paper_opened_next_action() -> None:
    """WAIT/NO_TRADE не должен предлагать оператору paper-вход."""
    now = datetime(2026, 5, 5, 16, 0, tzinfo=timezone.utc)
    item = enrich_recommendation_row(
        base_row(
            operator_action="WAIT",
            direction="long",
            entry=100.0,
            stop_loss=97.0,
            take_profit=106.0,
            last_price=100.0,
            spread_pct=0.01,
            turnover_24h=50_000_000.0,
            open_interest_value=30_000_000.0,
            funding_rate=0.0001,
            last_price_time="2026-05-05T15:55:00+00:00",
            bar_time="2026-05-05T15:45:00+00:00",
            created_at="2026-05-05T15:46:00+00:00",
            expires_at="2026-05-05T17:00:00+00:00",
        ),
        now=now,
    )
    contract = item["recommendation"]

    assert contract["recommendation_status"] == "wait"
    assert contract["is_actionable"] is False
    assert contract["primary_next_action"]["action"] != "paper_opened"
    assert all(action["action"] != "paper_opened" for action in contract["next_actions"])


def test_v55_frontend_renders_operator_buttons_from_server_next_actions_only() -> None:
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function operatorActionButtonsHtml(contract)" in js
    assert "const paperGateOk = paperGateState(contract).ok;" in js
    assert "if (action === 'paper_opened' && !paperGateOk) return;" in js
    assert "${operatorActionButtonsHtml(contract)}" in js
    assert "button.disabled" in js


def test_v55_frontend_no_longer_renders_unconditional_paper_button() -> None:
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "${contract.is_actionable ? '' : 'disabled" not in js
    assert "Paper-отметка доступна только при зелёном server price gate" not in js
