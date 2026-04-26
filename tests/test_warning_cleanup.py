from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import warnings

import pandas as pd


def test_query_df_uses_dbapi_cursor_without_pandas_sql_warning(monkeypatch):
    import app.db as db

    executed = {}

    class FakeCursor:
        description = [("id",), ("name",)]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            executed["sql"] = sql
            executed["params"] = params

        def fetchall(self):
            return [(1, "BTCUSDT"), (2, "ETHUSDT")]

    class FakeConnection:
        def cursor(self):
            return FakeCursor()

    @contextmanager
    def fake_get_conn():
        yield FakeConnection()

    def forbidden_read_sql_query(*_args, **_kwargs):  # pragma: no cover - должен остаться невызванным
        raise AssertionError("query_df не должен использовать pandas.read_sql_query с raw psycopg2 connection")

    monkeypatch.setattr(db, "get_conn", fake_get_conn)
    monkeypatch.setattr(pd, "read_sql_query", forbidden_read_sql_query)

    out = db.query_df("select id, name from symbols where id=%s", (1,))

    assert executed == {"sql": "select id, name from symbols where id=%s", "params": (1,)}
    assert list(out.columns) == ["id", "name"]
    assert out.to_dict("records") == [{"id": 1, "name": "BTCUSDT"}, {"id": 2, "name": "ETHUSDT"}]


def test_market_frame_liquidity_eligibility_no_future_warning(monkeypatch):
    import app.features as features

    n = 80
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    candles = pd.DataFrame(
        {
            "start_time": [start + timedelta(hours=i) for i in range(n)],
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.5 + i * 0.1 for i in range(n)],
            "volume": [1000.0 + i for i in range(n)],
            "turnover": [100000.0 + i for i in range(n)],
        }
    )
    liquidity = pd.DataFrame(
        {
            "start_time": [start + timedelta(hours=10), start + timedelta(hours=40)],
            "liquidity_score": [7.5, 8.0],
            "spread_pct": [0.02, 0.01],
            "is_eligible": pd.Series([None, True], dtype=object),
        }
    )

    calls = iter([candles, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), liquidity])
    monkeypatch.setattr(features, "query_df", lambda *_args, **_kwargs: next(calls).copy())

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", FutureWarning)
        out = features.load_market_frame("linear", "BTCUSDT", "60")

    assert not [w for w in caught if issubclass(w.category, FutureWarning)]
    assert out["is_eligible"].dtype == bool
    assert out["is_eligible"].iloc[0] is False or bool(out["is_eligible"].iloc[0]) is False
    assert bool(out["is_eligible"].iloc[-1]) is True
