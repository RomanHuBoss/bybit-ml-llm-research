from __future__ import annotations


def row(symbol: str, interval: str, direction: str, confidence: float, score: float = 0.5) -> dict:
    return {
        "id": hash((symbol, interval, direction, confidence)) % 100000,
        "symbol": symbol,
        "interval": interval,
        "strategy": "unit_strategy",
        "direction": direction,
        "confidence": confidence,
        "research_score": score,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def test_mtf_consensus_accepts_aligned_intraday_entry():
    from app.mtf import apply_mtf_consensus

    rows = [
        row("BTCUSDT", "15", "long", 0.70),
        row("BTCUSDT", "60", "long", 0.66),
        row("BTCUSDT", "240", "long", 0.58),
    ]

    out = apply_mtf_consensus(rows)
    entry = next(item for item in out if item["interval"] == "15")

    assert entry["mtf_status"] == "aligned_intraday"
    assert entry["mtf_action_class"] == "HIGH_CONVICTION_INTRADAY"
    assert entry["mtf_veto"] is False
    assert entry["higher_tf_conflict"] is False
    assert entry["mtf_score"] == 1.0
    assert entry["research_score"] > entry["research_score_base"]


def test_mtf_consensus_vetoes_entry_against_higher_timeframe():
    from app.mtf import apply_mtf_consensus

    rows = [
        row("ETHUSDT", "15", "long", 0.72),
        row("ETHUSDT", "60", "short", 0.68),
        row("ETHUSDT", "240", "short", 0.60),
    ]

    out = apply_mtf_consensus(rows)
    entry = next(item for item in out if item["interval"] == "15")

    assert entry["mtf_status"] == "no_trade_conflict"
    assert entry["mtf_action_class"] == "NO_TRADE_CONFLICT"
    assert entry["mtf_veto"] is True
    assert entry["higher_tf_conflict"] is True
    assert entry["research_score"] < entry["research_score_base"]


def test_mtf_consensus_marks_60m_as_context_not_entry():
    from app.mtf import apply_mtf_consensus

    rows = [
        row("SOLUSDT", "15", "long", 0.55),
        row("SOLUSDT", "60", "long", 0.78),
        row("SOLUSDT", "240", "neutral", 0.10),
    ]

    out = apply_mtf_consensus(rows)
    bias = next(item for item in out if item["interval"] == "60")

    assert bias["mtf_status"] == "context_only"
    assert bias["mtf_action_class"] == "CONTEXT_ONLY"
    assert bias["mtf_veto"] is True
    assert bias["mtf_is_entry_candidate"] is False
