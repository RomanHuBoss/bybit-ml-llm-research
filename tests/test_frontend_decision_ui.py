from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_has_operator_workstation_structure():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    required_ids = [
        "decisionBoard",
        "decisionBadge",
        "decisionTitle",
        "decisionScore",
        "ticketBody",
        "checklist",
        "reasonList",
        "operatorProtocol",
        "candidateQueue",
        "briefBtn",
        "llmStatusBox",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html

    assert "Рабочее место оператора" in html
    assert "Красный пункт = отмена" in html
    assert "Технические детали и журнал" in html
    assert "LIVE OFF" in html


def test_frontend_keeps_technical_data_secondary():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert '<details class="panel technical-details">' in html
    assert 'id="opsPanel"' in html
    assert 'id="opsToggleBtn"' in html
    assert 'id="opsBody"' in html
    assert "Операции с данными" in html
    assert "context-tab" in html
    assert "Review context" in html
    assert "right-rail" not in html


def test_frontend_logic_contains_operator_trade_guards():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    required_fragments = [
        "function checklistFor",
        "function decisionFor",
        "function riskReward",
        "function operatorProtocol",
        "function setContextTab",
        "Красных пунктов",
        "НЕТ ВХОДА",
        "К ПРОВЕРКЕ",
        "не создает бота автоматически",
        "refreshLlmStatus",
        "/api/llm/background/status",
        "/api/llm/background/run-now",
        "Фоновый LLM",
    ]
    for fragment in required_fragments:
        assert fragment in js


def test_status_api_exposes_signal_age_for_ui():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert '"max_signal_age_hours": settings.max_signal_age_hours' in api


def test_frontend_explains_background_llm_instead_of_manual_brief():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "LLM работает в фоне" in html
    assert "Обновить LLM сейчас" in html
    assert "LLM‑оценка появится автоматически" in html
    assert "market_brief" not in js
    assert "/api/llm/brief" not in js

def test_left_rail_keeps_data_operations_visible():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="opsToggleBtn"' in html
    assert 'aria-expanded="false"' in html
    assert 'id="opsBody" hidden' in html
    assert '<details class="ops-drawer">' not in html

    required_css_fragments = [
        ".left-rail",
        "display: flex",
        "flex-direction: column",
        "height: calc(100dvh - 82px)",
        "overflow: hidden",
        ".queue-panel",
        "flex: 1 1 0",
        "min-height: 128px",
        ".candidate-queue",
        "overflow-y: auto",
        "scrollbar-gutter: stable",
        ".ops-panel.open",
        "position: relative",
        "flex: 0 1 min(44dvh, 390px)",
        "max-height: min(44dvh, 390px)",
        ".ops-body",
        "flex: 1 1 auto",
        "overflow-y: auto",
        "overscroll-behavior: contain",
        "scrollbar-width: thin",
        "::-webkit-scrollbar-thumb",
    ]
    for fragment in required_css_fragments:
        assert fragment in css

    desktop_open_rule = css.split("@media (max-width: 980px)", 1)[0]
    assert "position: fixed" not in desktop_open_rule
    assert "bottom: 12px" not in desktop_open_rule
    assert "left: max" not in desktop_open_rule

    required_js_fragments = [
        "function setOpsPanelOpen",
        "function toggleOpsPanel",
        "body.hidden = !open",
        "aria-expanded",
        "opsToggleBtn",
        "Escape",
    ]
    for fragment in required_js_fragments:
        assert fragment in js

