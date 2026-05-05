from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_operator_v50_layout_repair_is_enabled():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "operator-cockpit-v50" in html
    assert "styles.css?v=trading-cockpit-v50" in html
    assert "app.js?v=trading-cockpit-v50" in html
    assert "V50 operator layout repair" in css


def test_operator_v50_removes_nested_sticky_offsets_that_shift_panels():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    required_fragments = [
        ".operator-cockpit-v49.operator-cockpit-v50 .operator-left,",
        ".operator-cockpit-v49.operator-cockpit-v50 .operator-right {",
        "position: static !important;",
        ".operator-cockpit-v49.operator-cockpit-v50 .queue-panel,",
        ".operator-cockpit-v49.operator-cockpit-v50 .context-card {",
        "position: relative !important;",
        "top: auto !important;",
    ]
    for fragment in required_fragments:
        assert fragment in css


def test_operator_v50_prevents_queue_card_text_overlap():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    required_fragments = [
        "grid-template-columns: repeat(auto-fit, minmax(74px, 1fr))",
        "grid-template-columns: minmax(0, 1fr) minmax(86px, 98px) 44px 16px !important",
        ".operator-cockpit-v49.operator-cockpit-v50 .candidate-star",
        "display: none !important;",
        ".operator-cockpit-v49.operator-cockpit-v50 .candidate-timeframe,",
        ".operator-cockpit-v49.operator-cockpit-v50 .candidate-metrics",
        "text-overflow: ellipsis;",
    ]
    for fragment in required_fragments:
        assert fragment in css


def test_operator_v50_has_responsive_breakpoints_for_two_and_one_column_modes():
    css = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")

    assert "@media (max-width: 1700px)" in css
    assert "@media (max-width: 1180px)" in css
    assert "@media (max-width: 720px)" in css
    assert "grid-template-columns: minmax(300px, 390px) minmax(0, 1fr);" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "overflow-wrap: anywhere;" in css
