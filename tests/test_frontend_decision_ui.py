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
        "РУЧНАЯ ПРОВЕРКА ВХОДА",
        "не отправляет ордера автоматически",
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


def test_frontend_has_dark_trading_terminal_redesign_and_sidebar():
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
    assert 'dark-mode' in html
    assert 'LIVE OFF' in html

    required_css_fragments = [
        "color-scheme: dark",
        "--page: #070a12",
        "--surface: rgba(14, 22, 40",
        "--green: #00e38c",
        "--red: #ff4d6d",
        ".app-frame",
        "grid-template-columns: var(--nav) minmax(0, 1fr)",
        ".side-nav",
        ".topbar",
        ".operation-toast",
        ".decision-board",
        ".support-grid",
        ".candidate",
        "grid-template-columns: 24px minmax(116px,1fr) minmax(88px,112px) 48px 20px",
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


def test_frontend_equalizes_main_operator_panels_and_deduplicates_queue():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    required_css = [
        ".queue-panel, .ticket, .mtf-panel",
        "height: clamp(430px, 45vh, 560px)",
        ".ticket-body, .mtf-matrix",
        "overflow-y: auto",
        "grid-template-columns: 24px minmax(116px,1fr) minmax(88px,112px) 48px 20px",
    ]
    for fragment in required_css:
        assert fragment in css

    required_js = [
        "function dedupeCandidatesByMarket",
        "function compareCandidates",
        "variant_count",
        "Уникальные рынки",
        "скрыто дублей",
        "const unique = dedupeCandidatesByMarket(mapped)",
    ]
    for fragment in required_js:
        assert fragment in js


def test_frontend_uses_extended_timeout_for_market_sync():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "function marketSyncTimeoutMs" in js
    assert "LONG_OPERATION_TIMEOUT_MS" in js
    assert "}, timeoutMs);" in js
    assert "Загрузка рынка" in js
    assert "уменьшите символы, интервалы или дни истории" in js
    assert 'value="30" min="1" max="730"' in html


def test_market_sync_multi_interval_does_not_repeat_funding_per_interval():
    api = (ROOT / "app" / "api.py").read_text(encoding="utf-8")

    assert "def _sync_market_bundle_multi" in api
    assert "funding_rows = sync_funding(category, symbol, days)" in api
    assert "result[symbol] = _sync_market_bundle_multi(category, symbol, intervals, days)" in api


def test_frontend_does_not_expose_manual_ml_launch_controls():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert 'id="trainBtn"' not in html
    assert 'id="predictBtn"' not in html
    assert 'Обучить ML' not in html
    assert 'ML‑прогноз' not in html
    assert "$('trainBtn')" not in js
    assert "$('predictBtn')" not in js
    assert "/api/ml/train" not in js
    assert "/api/ml/predict/latest" not in js


def test_frontend_uses_compact_badges_without_clipping_full_operator_label():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "const DECISION_COMPACT_LABELS" in js
    assert "review: 'ПРОВЕРКА'" in js
    assert "compactDecisionLabel(s.decision)" in js
    assert 'title="${label}" aria-label="${label}"' in js
    assert "const MTF_ACTION_COMPACT_LABELS" in js
    assert "compactMtfActionLabel(s)" in js
    assert "NO_TRADE_ENTRY_CONFLICT" in js
    assert "styles.css?v=trading-cockpit-v14" in html
    assert "v13 trading UI hardening" in css
    assert ".candidate .badge" in css
    assert "text-overflow: ellipsis" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(78px, 96px) 34px 12px" in css


def test_frontend_latest_signals_request_is_category_scoped():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "/api/signals/latest?category=" in js
    assert "encodeURIComponent($('category').value)" in js


def test_frontend_raw_signal_table_is_sortable():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert 'data-sort="score"' in html
    assert 'data-sort="rr"' in html
    assert "rawSort: { key: 'score', dir: 'desc' }" in js
    assert "function sortedRawRows" in js
    assert "function bindRawTableSorting" in js
    assert "aria-sort" in js
    assert "th[data-sort]" in css

def test_frontend_unknown_spread_is_not_rendered_as_zero_risk():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function riskFromSpread" in js
    assert "if (spread === null) return 18" in js
    assert "+ riskFromSpread(s)" in js
    assert "num(s.spread_pct, 0) > 0.15" not in js



def test_frontend_has_strategy_lab_and_desk_diagnostics_panel():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for fragment in [
        'id="strategyLabPanel"',
        'id="strategyLabBody"',
        'id="tradingDeskDiagnostics"',
        'id="qualityRefreshBtn"',
        'id="kpiApprovedStrategies"',
        'id="kpiReviewEntries"',
    ]:
        assert fragment in html

    for fragment in [
        "function refreshStrategyLab",
        "/api/strategies/lab",
        "/api/trading-desk/diagnostics",
        "Trading Desk пуст",
        "walk_forward_pass_rate",
    ]:
        assert fragment in js

    for fragment in [".strategy-lab-panel", ".strategy-lab-table", ".quality-pill"]:
        assert fragment in css


def test_frontend_has_institutional_decision_telemetry_panel():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    for fragment in [
        'id="decisionTelemetry"',
        'id="telemetryPrice"',
        'id="telemetryEntry"',
        'id="telemetryStop"',
        'id="telemetryTake"',
        'id="telemetryFreshness"',
        'id="telemetryVeto"',
    ]:
        assert fragment in html

    for fragment in [
        "function volumeFmt",
        "function pnlFmt",
        "function scoreFmt",
        "function riskRewardFmt",
        "function currentPrice",
        "function expectedMoveText",
        "function hardVetoSummary",
        "function renderDecisionTelemetry",
        "renderDecisionTelemetry(s, d)",
    ]:
        assert fragment in js

    for fragment in [
        "v21 institutional decision cockpit",
        ".decision-telemetry",
        ".execution-map",
        "prefers-reduced-motion",
        "loading-skeleton",
    ]:
        assert fragment in css


def test_frontend_uses_extended_timeout_for_signal_build():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function signalBuildTimeoutMs" in js
    assert "symbol×interval job" in js
    assert "}, signalBuildTimeoutMs());" in js
    assert "45 секунд превращали нормальный тяжелый пересчет" in js


def test_frontend_surfaces_missing_strategy_quality_contract_as_error():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    assert "function hasStrategyQualityContract" in js
    assert "Strategy quality не пришел из API" in js
    assert "API не передал quality_status/quality_score" in js



def test_frontend_renders_provisional_quality_mode_and_entry_approved_kpi():
    js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "Strategy quality PROVISIONAL" in js
    assert "operator_quality_mode" in js
    assert "entry_interval_approved" in js
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    assert "Approved 15m/all" in html
