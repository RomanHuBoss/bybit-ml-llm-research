from app.indicators import add_indicators
import pandas as pd


def test_indicators_smoke():
    df = pd.DataFrame({
        "start_time": pd.date_range("2024-01-01", periods=250, freq="h"),
        "open": range(250),
        "high": [x + 2 for x in range(250)],
        "low": [x - 2 for x in range(250)],
        "close": [x + 1 for x in range(250)],
        "volume": [100 + x for x in range(250)],
        "turnover": [1000 + x for x in range(250)],
    })
    out = add_indicators(df)
    assert "rsi_14" in out.columns
    assert "atr_14" in out.columns
    assert "donchian_high" in out.columns
