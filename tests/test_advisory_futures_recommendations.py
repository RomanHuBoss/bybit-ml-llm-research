from __future__ import annotations

import pandas as pd

from app.recommendation import classify_operator_action
from app.strategies import bollinger_rsi_reversion, trend_continuation_setup, validate_signal


def _trend_row(**overrides):
    row = {
        "close": 105.0,
        "atr_14": 1.2,
        "atr_pct": 1.2 / 105.0,
        "ema_20": 103.0,
        "ema_50": 100.0,
        "ema_200": 95.0,
        "rsi_14": 58.0,
        "ret_3": 0.012,
        "ret_12": 0.020,
        "volume_z": 0.2,
        "funding_rate": 0.0001,
        "bb_position": 0.62,
        "spread_pct": 0.01,
        "liquidity_score": 8.0,
        "is_eligible": True,
    }
    row.update(overrides)
    return pd.Series(row)


def test_trend_continuation_builds_futures_entry_levels_with_unknown_liquidity_snapshot():
    signal = trend_continuation_setup(
        _trend_row(spread_pct=999.0, liquidity_score=0.0, is_eligible=False, liquidity_state="unknown")
    )

    assert signal is not None
    assert signal.strategy == "trend_continuation_setup"
    assert signal.direction == "long"
    assert signal.stop_loss < signal.entry < signal.take_profit
    assert signal.rationale["liquidity_state"] == "unknown"
    assert signal.rationale["is_eligible"] is None
    assert validate_signal(signal) == (True, None)


def test_trend_continuation_blocks_known_non_eligible_liquidity():
    signal = trend_continuation_setup(_trend_row(is_eligible=False, liquidity_score=1.0, spread_pct=0.01))

    assert signal is None


def test_operator_action_keeps_unknown_liquidity_in_wait_with_manual_warning():
    decision = classify_operator_action(
        {
            "symbol": "BTCUSDT",
            "interval": "15",
            "direction": "long",
            "confidence": 0.68,
            "entry": 105.0,
            "stop_loss": 103.26,
            "take_profit": 108.12,
            "fresh": True,
            "data_status": "fresh",
            "mtf_status": "aligned_bias",
            "mtf_score": 0.82,
            "mtf_veto": False,
            "higher_tf_conflict": False,
            "is_eligible": None,
            "spread_pct": None,
            "research_score": 0.45,
            "trades_count": None,
            "profit_factor": None,
            "roc_auc": None,
            "ml_probability": None,
        }
    )

    assert decision["operator_action"] == "WAIT"
    assert any(item["code"] == "liquidity_unknown" for item in decision["operator_warnings"])
    assert any(item["code"] == "spread_unknown" for item in decision["operator_warnings"])
    assert decision["operator_hard_reasons"] == []


def test_bollinger_reversion_respects_zero_bb_position():
    signal = bollinger_rsi_reversion(
        _trend_row(
            close=100.0,
            atr_14=1.0,
            atr_pct=0.01,
            ema_20=100.0,
            ema_50=100.0,
            ema_200=99.5,
            rsi_14=25.0,
            bb_position=0.0,
            ema20_50_gap=0.0,
            is_eligible=True,
            liquidity_score=8.0,
            spread_pct=0.01,
        )
    )

    assert signal is not None
    assert signal.strategy == "bollinger_rsi_reversion"
    assert signal.direction == "long"
    assert signal.rationale["bb_position"] == 0.0
    assert signal.stop_loss < signal.entry < signal.take_profit

