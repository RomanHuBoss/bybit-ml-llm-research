from __future__ import annotations

from pathlib import Path

from app.strategy_lab import build_strategy_lab_payload, strategy_lab_from_quality_export
from app.strategy_quality import evaluate_strategy_quality

ROOT = Path(__file__).resolve().parents[1]


def test_strategy_quality_uses_walk_forward_when_available():
    weak = evaluate_strategy_quality(
        {
            "trades_count": 80,
            "profit_factor": 1.35,
            "max_drawdown": 0.08,
            "total_return": 0.10,
            "walk_forward_pass_rate": 0.20,
            "walk_forward_windows": 6,
        }
    )
    assert weak["quality_status"] != "APPROVED"

    strong = evaluate_strategy_quality(
        {
            "trades_count": 80,
            "profit_factor": 1.35,
            "max_drawdown": 0.08,
            "total_return": 0.10,
            "walk_forward_pass_rate": 0.80,
            "walk_forward_windows": 6,
        }
    )
    assert strong["quality_status"] == "APPROVED"


def test_strategy_lab_payload_explains_approved_and_blockers():
    payload = build_strategy_lab_payload(
        [
            {"symbol": "APEUSDT", "interval": "15", "strategy": "oi", "quality_status": "APPROVED", "quality_score": 95, "trades_count": 47, "profit_factor": 2.2, "max_drawdown": 0.02},
            {"symbol": "TESTUSDT", "interval": "15", "strategy": "ema", "quality_status": "RESEARCH", "quality_score": 40, "trades_count": 7, "profit_factor": 1.5, "max_drawdown": 0.01},
        ]
    )

    assert payload["desk_status"] == "HAS_APPROVED"
    assert payload["summary"]["status_counts"]["APPROVED"] == 1
    assert payload["blocker_counts"]["sample_size"] == 1
    assert payload["trading_desk"][0]["symbol"] == "APEUSDT"


def test_quality_snapshot_can_drive_strategy_lab_regression():
    payload = strategy_lab_from_quality_export(ROOT / "docs" / "QUALITY_SNAPSHOT_2026-04-30.json")

    assert payload["summary"]["approved"] == 3
    assert payload["summary"]["watchlist"] == 3
    assert payload["summary"]["research"] == 32
    assert payload["summary"]["rejected"] == 18
    assert payload["desk_status"] == "HAS_APPROVED"
