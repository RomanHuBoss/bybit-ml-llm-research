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

    assert '<details class="panel technical-details" id="technicalDetails">' in html
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
    assert 'id="decisionVerdict"' in html
    assert 'id="opsHelper"' in html
    assert 'id="refreshQueueBtn"' in html
    assert 'aria-expanded="true"' in html
    assert 'id="opsBody"' in html
    assert 'id="opsBody" hidden' not in html
    assert 'queue-header' in html
    assert 'Свернуть панель' in html

    required_css_fragments = [
        "color-scheme: light",
        "--page: #f4f2ee",
        "--surface: #ffffff",
        "--blue: #2456a6",
        ".app-frame",
        "grid-template-columns: 76px minmax(0, 1fr)",
        ".side-nav",
        ".topbar",
        "background: rgba(250,249,246",
        ".operation-toast",
        ".decision-board",
        ".support-grid",
        ".candidate",
        "grid-template-columns: 24px minmax(0,1fr) 112px 48px 20px",
        ".ops-panel:not(.open) .ops-body",
        ".ops-body",
        "grid-template-columns: minmax(220px,1.7fr)",
        "scrollbar-gutter: stable",
        ".tf-grid",
        ".help-dialog",
    ]
    for fragment in required_css_fragments:
        assert fragment in css

    assert "decisionBadge').className" in js
    assert "decisionVerdict" in js
    assert "opsHelper" in js
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
        "button[data-busy-lock=\"true\"]",
        "function showOperationStatus",
        "aria-busy",
        "document.body.classList.contains('is-busy')",
        "noopener noreferrer",
    ]
    for fragment in required_js_fragments:
        assert fragment in js

    assert 'id="candidateQueue"' in html
    assert 'aria-live="polite"' in html
    assert html.count('type="button"') >= 12


def test_frontend_all_visible_controls_are_bound_or_native():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    expected = [
        'id="navToggleBtn"',
        'data-nav-target="workspace"',
        'data-nav-target="equityCanvas"',
        'data-nav-target="operatorProtocol"',
        'data-nav-target="opsPanel"',
        'data-nav-target="settings"',
        'data-nav-target="help"',
        'id="operationToast"',
        'id="operationStatus"',
        'id="helpDialog"',
    ]
    for fragment in expected:
        assert fragment in html

    required_js = [
        "document.querySelectorAll('.nav-item[data-nav-target]')",
        "activateNav(button)",
        "openTechnicalDetails()",
        "setContextTab('protocol')",
        "setOpsPanelOpen(true)",
        "dialog?.showModal",
        "nav-collapsed",
        "button[data-busy-lock=\"true\"]",
        "showOperationStatus(`Ошибка:",
        "return null",
        "validateInputs({ requireSymbols: true })",
        "setAttribute('aria-selected'",
        "panel.hidden = !active",
    ]
    for fragment in required_js:
        assert fragment in js


def test_frontend_does_not_disable_navigation_during_long_operations():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "document.querySelectorAll('button').forEach" not in js
    assert "document.querySelectorAll('button[data-busy-lock=\"true\"]')" in js
    assert "if (document.body.classList.contains('is-busy')) return;" in js
