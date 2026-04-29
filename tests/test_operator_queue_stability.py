from __future__ import annotations

from app.operator_queue import consolidate_operator_queue
from app.recommendation import classify_operator_action


def row(**overrides):
    base = {
        "category": "linear",
        "symbol": "BTCUSDT",
        "interval": "15",
        "bar_time": "2026-04-29T10:00:00+00:00",
        "strategy": "ema_pullback_trend",
        "direction": "long",
        "confidence": 0.66,
        "entry": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "fresh": True,
        "data_status": "fresh",
        "mtf_status": "aligned_bias",
        "mtf_score": 0.82,
        "mtf_veto": False,
        "higher_tf_conflict": False,
        "is_eligible": True,
        "spread_pct": 0.02,
        "research_score": 0.5,
    }
    base.update(overrides)
    base.update(classify_operator_action(base))
    return base


def test_consolidates_duplicate_strategies_to_one_market_decision():
    rows = [
        row(id=1, strategy="ema_pullback_trend", confidence=0.64, research_score=0.45),
        row(id=2, strategy="oi_trend_confirmation", confidence=0.68, research_score=0.52),
    ]

    queue = consolidate_operator_queue(rows)

    assert len(queue) == 1
    assert queue[0]["strategy"] == "oi_trend_confirmation"
    assert queue[0]["operator_variant_count"] == 2
    assert queue[0]["direction_conflict"] is False


def test_blocks_material_long_short_conflict_instead_of_flipping_recommendation():
    rows = [
        row(id=1, direction="long", strategy="ema_pullback_trend", confidence=0.66, research_score=0.50),
        row(id=2, direction="short", strategy="funding_extreme_contrarian", confidence=0.65, research_score=0.50, stop_loss=102.0, take_profit=96.0),
    ]

    queue = consolidate_operator_queue(rows)

    assert len(queue) == 1
    assert queue[0]["operator_action"] == "NO_TRADE"
    assert queue[0]["operator_label"] == "КОНФЛИКТ СИГНАЛОВ"
    assert queue[0]["direction_conflict"] is True
    assert any(reason["code"] == "direction_conflict" for reason in queue[0]["operator_hard_reasons"])


def test_weak_direction_dominance_downgrades_review_to_wait():
    weak = row(id=1, direction="long", confidence=0.59, research_score=0.36)
    opposite_reject = row(
        id=2,
        direction="short",
        confidence=0.57,
        research_score=0.35,
        stop_loss=102.0,
        take_profit=96.0,
        mtf_veto=True,
        higher_tf_conflict=True,
        mtf_status="no_trade_conflict",
    )

    queue = consolidate_operator_queue([weak, opposite_reject])

    assert queue[0]["operator_level"] in {"watch", "reject"}
    assert "operator_stability_score" in queue[0]
