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
    assert "15m рекомендации" in html
    assert "15m setups" in html
    assert "MTF контур" in html
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
    assert "Risk & evidence" in html
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
        "function isEntryRecommendation",
        "entry_only=true",
        "context_only",
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


def test_frontend_has_light_fintech_redesign_and_sidebar():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'class="app-frame"' in html
    assert 'class="side-nav"' in html
    assert 'class="side-logo"' in html
    assert 'class="support-grid"' in html
    assert 'class="protocol-mini"' in html
    assert 'aria-expanded="true"' in html
    assert 'id="opsBody"' in html
    assert 'id="opsBody" hidden' not in html

    required_css_fragments = [
        "color-scheme: light",
        "--page: #f5f7fb",
        ".app-frame",
        "grid-template-columns: 78px minmax(0, 1fr)",
        ".side-nav",
        ".topbar",
        "background: rgba(255, 255, 255",
        ".decision-board",
        ".support-grid",
        ".candidate",
        "grid-template-columns: 24px minmax(0, 1fr) auto 24px",
        ".ops-panel.open",
        "position: relative",
        "flex: 0 1 min(48dvh, 420px)",
        ".ops-body",
        "overflow-y: auto",
        "overscroll-behavior: contain",
        "scrollbar-width: thin",
        "::-webkit-scrollbar-thumb",
    ]
    for fragment in required_css_fragments:
        assert fragment in css

    assert "decisionBadge').className" in js
    assert 'role="button" tabindex="0"' in js
    assert "event.key === 'Enter'" in js
    assert "event.key === ' '" in js


def test_frontend_has_fetch_timeout_busy_guard_and_safe_links():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    required_js_fragments = [
        "function cssToken",
        "function safeExternalUrl",
        "new URL(String(value), window.location.origin)",
        "['http:', 'https:'].includes(url.protocol)",
        "AbortController",
        "API timeout after",
        "function setBusy",
        "aria-busy",
        "document.body.classList.contains('is-busy')",
        "noopener noreferrer",
    ]
    for fragment in required_js_fragments:
        assert fragment in js

    assert 'id="candidateQueue"' in html
    assert 'aria-live="polite"' in html
    assert html.count('type="button"') >= 12
