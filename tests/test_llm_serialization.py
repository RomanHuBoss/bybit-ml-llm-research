from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
from uuid import UUID

import numpy as np
import pandas as pd


def test_to_jsonable_handles_db_pandas_numpy_values():
    from app.serialization import to_jsonable

    payload = {
        "created_at": datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        "trade_date": date(2024, 1, 2),
        "trade_time": time(3, 4, 5),
        "price": Decimal("123.45"),
        "uid": UUID("12345678-1234-5678-1234-567812345678"),
        "np_float": np.float64(1.25),
        "np_int": np.int64(7),
        "np_array": np.array([1, 2]),
        "pd_timestamp": pd.Timestamp("2024-01-02T03:04:05Z"),
        "pd_na": pd.NA,
        "nested": [{"x": Decimal("1.5")}],
    }

    out = to_jsonable(payload)

    assert out["created_at"] == "2024-01-02T03:04:05+00:00"
    assert out["trade_date"] == "2024-01-02"
    assert out["trade_time"] == "03:04:05"
    assert out["price"] == 123.45
    assert out["uid"] == "12345678-1234-5678-1234-567812345678"
    assert out["np_float"] == 1.25
    assert out["np_int"] == 7
    assert out["np_array"] == [1, 2]
    assert out["pd_timestamp"].startswith("2024-01-02T03:04:05")
    assert out["pd_na"] is None
    assert out["nested"] == [{"x": 1.5}]


def test_market_brief_serializes_datetime_payload_before_prompt(monkeypatch):
    import app.llm as llm

    captured = {}

    def fake_generate(prompt: str, system: str | None = None, temperature: float = 0.1) -> str:
        captured["prompt"] = prompt
        return "brief-ok"

    monkeypatch.setattr(llm, "ollama_generate", fake_generate)

    result = llm.market_brief({"created_at": datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc), "score": Decimal("0.75")})

    assert result == "brief-ok"
    assert '"created_at": "2024-01-02T03:04:05+00:00"' in captured["prompt"]
    assert '"score": 0.75' in captured["prompt"]
