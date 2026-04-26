from __future__ import annotations

from datetime import datetime, timezone


def test_synthetic_news_url_is_stable_across_calls():
    from app.sentiment import _stable_synthetic_url

    published = datetime(2024, 1, 1, tzinfo=timezone.utc)
    first = _stable_synthetic_url("rss:Test", "BTC rallies", published)
    second = _stable_synthetic_url("rss:Test", "BTC rallies", published)

    assert first == second
    assert first.startswith("synthetic://news/")


def test_news_url_keeps_real_url_and_falls_back_to_stable_key():
    from app.sentiment import _news_url

    assert _news_url("gdelt", "Title", "https://example.com/a") == "https://example.com/a"
    assert _news_url("gdelt", "Title", None) == _news_url("gdelt", "Title", "")
