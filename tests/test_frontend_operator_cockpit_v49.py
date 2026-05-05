from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]


def test_operator_cockpit_html_has_valid_single_owner_regions():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    ids = [tag.get("id") for tag in soup.find_all(attrs={"id": True})]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})

    assert duplicates == []
    assert len(soup.select(".trade-ticket")) == 1
    assert len(soup.select("#operatorProtocol")) == 1
    assert soup.select_one("body.operator-cockpit-v49") is not None
    assert soup.select_one(".operator-grid .operator-left") is not None
    assert soup.select_one(".operator-grid .operator-center") is not None
    assert soup.select_one(".operator-grid .operator-right") is not None


def test_operator_cockpit_keeps_repeated_market_context_hidden_or_secondary():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    support_cards = soup.select(".support-card.support-grid")
    assert support_cards, "legacy news/sentiment mirror must stay hidden for JS compatibility"
    assert all(card.has_attr("hidden") for card in support_cards)

    technical = soup.select_one("details#technicalDetails")
    assert technical is not None
    assert technical.find("table", id="rawTable") is not None
    assert "Технические детали и журнал" in technical.get_text(" ")


def test_queue_card_is_compact_and_no_longer_duplicates_trade_levels():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    render_queue = js[js.index("function renderQueue") : js.index("function renderRawTable")]

    assert "candidate-metrics" in render_queue
    assert "R/R ${fmt(rr, 2)}" in render_queue
    assert "Conf ${escapeHtml(conf)}" in render_queue
    assert "TTL ${escapeHtml(expires)}" in render_queue
    assert "E ${priceFmt" not in render_queue
    assert "SL ${priceFmt" not in render_queue
    assert "TP ${priceFmt" not in render_queue


def test_operator_actions_include_advisory_paper_mark_without_auto_trading():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "data-operator-action=\"paper_opened\"" in js
    assert "Отметить paper-вход" in js
    assert "const allowedActions = new Set(['skip', 'wait_confirmation', 'manual_review', 'close_invalidated', 'paper_opened']);" in js
    assert "Система не отправляет ордера автоматически" in (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")


def test_frontend_references_required_runtime_ids():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    runtime_ids = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", js)) | set(re.findall(r"setText\(['\"]([^'\"]+)['\"]", js))

    assert sorted(runtime_ids - ids) == []
