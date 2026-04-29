from __future__ import annotations


def test_bybit_get_reports_non_numeric_ret_code_without_value_error(monkeypatch):
    from app.bybit_client import BybitAPIError, BybitClient

    class Response:
        status_code = 200
        text = "non numeric ret code"

        def raise_for_status(self):
            return None

        def json(self):
            return {"retCode": "gateway_error", "retMsg": "bad gateway body", "result": {}}

    monkeypatch.setattr("app.bybit_client.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.bybit_client.time.sleep", lambda *_args, **_kwargs: None)

    try:
        BybitClient(sleep_sec=0)._get("/v5/market/tickers", {"category": "linear"})
    except BybitAPIError as exc:
        assert "gateway_error" in str(exc)
    else:  # pragma: no cover - защитная ветка, если API-контракт внезапно изменится
        raise AssertionError("ожидалась BybitAPIError для нестандартного retCode")


def test_bybit_instruments_info_detects_cursor_loop():
    from app.bybit_client import BybitAPIError, BybitClient

    class LoopingCursorClient(BybitClient):
        def __init__(self):
            super().__init__(sleep_sec=0)
            self.calls = 0

        def _get(self, path, params):
            self.calls += 1
            return {"list": [{"symbol": f"BTC{self.calls}USDT"}], "nextPageCursor": "same-cursor"}

    client = LoopingCursorClient()
    try:
        client.get_instruments_info("linear")
    except BybitAPIError as exc:
        assert "cursor loop" in str(exc)
        assert client.calls == 2
    else:  # pragma: no cover
        raise AssertionError("ожидалась BybitAPIError при повторяющемся курсоре")


def test_bybit_market_list_endpoints_reject_non_list_payload(monkeypatch):
    from app.bybit_client import BybitAPIError, BybitClient

    class Response:
        status_code = 200
        text = "bad list"

        def raise_for_status(self):
            return None

        def json(self):
            return {"retCode": 0, "retMsg": "OK", "result": {"list": {"unexpected": "object"}}}

    monkeypatch.setattr("app.bybit_client.requests.get", lambda *args, **kwargs: Response())
    monkeypatch.setattr("app.bybit_client.time.sleep", lambda *_args, **_kwargs: None)

    try:
        BybitClient(sleep_sec=0).get_tickers("linear")
    except BybitAPIError as exc:
        assert "result.list has unexpected type" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ожидалась BybitAPIError для не-list payload")


def test_bybit_open_interest_paginates_cursor_and_preserves_params():
    from app.bybit_client import BybitClient

    class PagedOpenInterestClient(BybitClient):
        def __init__(self):
            super().__init__(sleep_sec=0)
            self.calls = []

        def _get(self, path, params):
            self.calls.append((path, dict(params)))
            if len(self.calls) == 1:
                return {"list": [{"timestamp": "1000", "openInterest": "1"}], "nextPageCursor": "page-2"}
            return {"list": [{"timestamp": "2000", "openInterest": "2"}], "nextPageCursor": ""}

    client = PagedOpenInterestClient()
    rows = client.get_open_interest("linear", "btcusdt", "15min", start_ms=1000, end_ms=2000, limit=200)

    assert rows == [
        {"timestamp": "1000", "openInterest": "1"},
        {"timestamp": "2000", "openInterest": "2"},
    ]
    assert client.calls[0][0] == "/v5/market/open-interest"
    assert client.calls[0][1]["symbol"] == "BTCUSDT"
    assert "cursor" not in client.calls[0][1]
    assert client.calls[1][1]["cursor"] == "page-2"
    assert client.calls[1][1]["startTime"] == 1000
    assert client.calls[1][1]["endTime"] == 2000


def test_bybit_open_interest_detects_cursor_loop():
    from app.bybit_client import BybitAPIError, BybitClient

    class LoopingOpenInterestClient(BybitClient):
        def __init__(self):
            super().__init__(sleep_sec=0)
            self.calls = 0

        def _get(self, path, params):
            self.calls += 1
            return {"list": [{"timestamp": str(self.calls), "openInterest": "1"}], "nextPageCursor": "same-cursor"}

    client = LoopingOpenInterestClient()
    try:
        client.get_open_interest("linear", "BTCUSDT", "15min")
    except BybitAPIError as exc:
        assert "open-interest cursor loop" in str(exc)
        assert client.calls == 2
    else:  # pragma: no cover
        raise AssertionError("ожидалась BybitAPIError при повторяющемся курсоре open-interest")
