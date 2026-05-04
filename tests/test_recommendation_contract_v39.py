from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.api import _recommendation_contract_metadata
from app.trade_contract import enrich_recommendation_row
from tests.test_recommendation_contract_v28 import base_row

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)


def test_v39_contract_has_single_clock_ttl_fields_and_boundary_expiry():
    item = enrich_recommendation_row(
        base_row(
            bar_time="2026-05-04T11:45:00+00:00",
            expires_at="2026-05-04T12:00:00+00:00",
            last_price=100.0,
        ),
        now=NOW,
    )
    contract = item["recommendation"]

    assert contract["checked_at"] == "2026-05-04T12:00:00+00:00"
    assert contract["ttl_status"] == "expired"
    assert contract["ttl_seconds_left"] == 0
    assert contract["is_expired"] is True
    assert contract["recommendation_status"] == "expired"
    assert contract["price_actionability"]["reason"] == "expired"
    assert "expired" in contract["price_actionability"]["reasons"]


def test_v39_hard_no_trade_reason_is_not_hidden_by_expired_ttl():
    item = enrich_recommendation_row(
        base_row(
            operator_action="NO_TRADE",
            operator_hard_reasons=[{"code": "mtf", "title": "MTF veto", "detail": "60m против входа"}],
            expires_at="2026-05-04T11:00:00+00:00",
            last_price=100.0,
        ),
        now=NOW,
    )

    assert item["recommendation_status"] == "blocked"
    assert item["trade_direction"] == "no_trade"
    assert item["ttl_status"] == "expired"
    assert "60m против входа" in item["recommendation_explanation"]


def test_v39_contract_metadata_and_frontend_expose_ttl_state():
    metadata = _recommendation_contract_metadata()
    required = set(metadata["required_recommendation_fields"])
    assert {"checked_at", "ttl_status", "ttl_seconds_left"}.issubset(required)

    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "function ttlText(contract)" in js
    assert "function ttlTone(contract)" in js
    assert "contract.checked_at" in js
    assert "ttl-state" in js
    assert ".ttl-state.expired" in css
    assert "trading-cockpit-v39" in html
