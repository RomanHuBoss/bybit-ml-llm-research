from __future__ import annotations


class _Boom(Exception):
    pass


def _reset_gdelt(sentiment):
    with sentiment._GDELT_LOCK:
        sentiment._GDELT_CONSECUTIVE_FAILURES = 0
        sentiment._GDELT_DISABLED_UNTIL = 0.0


def test_gdelt_timeout_opens_circuit_and_suppresses_followup_requests(monkeypatch):
    from app import sentiment

    _reset_gdelt(sentiment)
    calls = {"n": 0}

    def broken_get_json(*args, **kwargs):
        calls["n"] += 1
        raise _Boom("timeout")

    monkeypatch.setattr(sentiment, "_safe_get_json", broken_get_json)
    monkeypatch.setattr(sentiment.settings, "gdelt_circuit_breaker_failures", 2)
    monkeypatch.setattr(sentiment.settings, "gdelt_failure_cooldown_sec", 300)

    assert sentiment.fetch_gdelt_news("BTCUSDT") == []
    assert sentiment.fetch_gdelt_news("ETHUSDT") == []
    assert sentiment.fetch_gdelt_news("SOLUSDT") == []

    status = sentiment._gdelt_circuit_status()
    assert status["enabled"] is False
    assert status["cooldown_remaining_sec"] > 0
    assert calls["n"] == 2

    _reset_gdelt(sentiment)


def test_gdelt_success_resets_consecutive_failures(monkeypatch):
    from app import sentiment

    _reset_gdelt(sentiment)
    with sentiment._GDELT_LOCK:
        sentiment._GDELT_CONSECUTIVE_FAILURES = 1

    monkeypatch.setattr(sentiment, "_safe_get_json", lambda *a, **k: {"articles": [{"title": "Bitcoin rallies"}]})

    rows = sentiment.fetch_gdelt_news("BTCUSDT")

    assert len(rows) == 1
    assert sentiment._gdelt_circuit_status()["consecutive_failures"] == 0

    _reset_gdelt(sentiment)
