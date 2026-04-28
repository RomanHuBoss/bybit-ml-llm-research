from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
except ModuleNotFoundError:  # pragma: no cover - fallback only for minimal test environments.
    class SentimentIntensityAnalyzer:  # type: ignore[no-redef]
        POSITIVE = {"gain", "gains", "bull", "bullish", "surge", "rally", "growth", "record", "positive"}
        NEGATIVE = {"loss", "losses", "bear", "bearish", "crash", "hack", "lawsuit", "negative", "drop"}

        def polarity_scores(self, text: str) -> dict[str, float]:
            words = {w.strip(".,:;!?()[]{}\"'").lower() for w in text.split()}
            score = 0.0
            score += 0.2 * len(words & self.POSITIVE)
            score -= 0.2 * len(words & self.NEGATIVE)
            return {"compound": max(-1.0, min(1.0, score))}

from .config import settings
from .db import execute_many_values, fetch_all
from .features import load_market_frame
from .llm import classify_news_with_llm

logger = logging.getLogger(__name__)
_analyzer = SentimentIntensityAnalyzer()

_GDELT_LOCK = threading.Lock()
_GDELT_CONSECUTIVE_FAILURES = 0
_GDELT_DISABLED_UNTIL = 0.0


def _gdelt_circuit_status(now: float | None = None) -> dict[str, Any]:
    """Возвращает состояние circuit breaker для GDELT.

    GDELT — внешний бесплатный источник новостей, поэтому он не должен быть
    hard dependency для торгового цикла. При серии таймаутов временно
    пропускаем этот источник, чтобы не блокировать sentiment sync по каждому
    символу и не засорять журнал однотипными ошибками.
    """
    moment = time.monotonic() if now is None else now
    with _GDELT_LOCK:
        return {
            "enabled": moment >= _GDELT_DISABLED_UNTIL,
            "disabled_until": _GDELT_DISABLED_UNTIL,
            "cooldown_remaining_sec": max(0.0, _GDELT_DISABLED_UNTIL - moment),
            "consecutive_failures": _GDELT_CONSECUTIVE_FAILURES,
        }


def _record_gdelt_success() -> None:
    global _GDELT_CONSECUTIVE_FAILURES, _GDELT_DISABLED_UNTIL
    with _GDELT_LOCK:
        _GDELT_CONSECUTIVE_FAILURES = 0
        _GDELT_DISABLED_UNTIL = 0.0


def _record_gdelt_failure(symbol: str, exc: Exception) -> None:
    global _GDELT_CONSECUTIVE_FAILURES, _GDELT_DISABLED_UNTIL
    with _GDELT_LOCK:
        _GDELT_CONSECUTIVE_FAILURES += 1
        threshold = max(1, int(settings.gdelt_circuit_breaker_failures))
        if _GDELT_CONSECUTIVE_FAILURES >= threshold:
            cooldown = max(10, int(settings.gdelt_failure_cooldown_sec))
            _GDELT_DISABLED_UNTIL = time.monotonic() + cooldown
            logger.warning(
                "GDELT temporarily disabled for %ss after %s consecutive failures; last symbol=%s; error=%s",
                cooldown,
                _GDELT_CONSECUTIVE_FAILURES,
                symbol,
                exc,
            )
        else:
            logger.warning(
                "GDELT sync failed for %s (%s/%s before cooldown): %s",
                symbol,
                _GDELT_CONSECUTIVE_FAILURES,
                threshold,
                exc,
            )


SYMBOL_ALIASES: dict[str, str] = {
    "BTC": "bitcoin OR BTC",
    "ETH": "ethereum OR ETH",
    "SOL": "solana OR SOL",
    "XRP": "ripple OR XRP",
    "DOGE": "dogecoin OR DOGE",
    "BNB": "bnb OR binance coin",
    "ADA": "cardano OR ADA",
    "SUI": "sui blockchain OR SUI",
    "AAVE": "aave OR AAVE",
    "LINK": "chainlink OR LINK",
    "AVAX": "avalanche crypto OR AVAX",
    "LTC": "litecoin OR LTC",
    "NEAR": "near protocol OR NEAR",
    "PEPE": "pepe coin OR PEPE",
    "HYPE": "hyperliquid OR HYPE",
}



def _stable_synthetic_url(source: str, title: str, published_at: datetime | None = None) -> str:
    """Создает детерминированный ключ новости, если источник не дал URL.

    Нельзя использовать встроенный hash(): он рандомизирован между процессами Python,
    из-за чего одинаковая RSS-новость после перезапуска вставляется повторно.
    """
    ts = published_at.isoformat() if published_at else "unknown_time"
    digest = hashlib.sha256(f"{source}|{ts}|{title}".encode("utf-8")).hexdigest()[:24]
    return f"synthetic://news/{digest}"


def _news_url(source: str, title: str, url: str | None, published_at: datetime | None = None) -> str:
    value = (url or "").strip()
    return value or _stable_synthetic_url(source, title, published_at)


def _safe_get_json(url: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
    request_timeout = timeout if timeout is not None else settings.sentiment_http_timeout_sec
    response = requests.get(url, params=params, timeout=request_timeout, headers={"User-Agent": "bybit-ml-llm-research-lab/2.0"})
    response.raise_for_status()
    return response.json()


def _safe_get_text(url: str, timeout: float | None = None) -> str:
    request_timeout = timeout if timeout is not None else settings.sentiment_http_timeout_sec
    response = requests.get(url, timeout=request_timeout, headers={"User-Agent": "bybit-ml-llm-research-lab/2.0"})
    response.raise_for_status()
    return response.text


def _has_sentiment_budget(deadline: float | None, reserve_sec: float = 2.0) -> bool:
    if deadline is None:
        return True
    return time.monotonic() + reserve_sec < deadline


def _base_symbol(symbol: str) -> str:
    base = symbol.upper().replace("USDT", "")
    if base.startswith("1000"):
        base = base[4:]
    return base


def _symbol_query(symbol: str) -> str:
    base = _base_symbol(symbol)
    return SYMBOL_ALIASES.get(base, f"{base} cryptocurrency")


def _label_from_score(score: float) -> str:
    if score <= -0.55:
        return "strong_bearish"
    if score <= -0.15:
        return "bearish"
    if score >= 0.55:
        return "strong_bullish"
    if score >= 0.15:
        return "bullish"
    return "neutral"


def _parse_source_def(raw: str) -> tuple[str, str]:
    if "|" in raw:
        url, name = raw.split("|", 1)
        return url.strip(), name.strip()
    url = raw.strip()
    host = urlparse(url).netloc.replace("www.", "") or "rss"
    return url, host


def _parse_rss_date(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _title_matches_symbol(title: str, symbol: str) -> bool:
    base = _base_symbol(symbol)
    if base in {"BTC", "ETH", "SOL", "XRP", "DOGE", "BNB", "ADA"}:
        pattern = rf"\b({re.escape(base)}|{_symbol_query(symbol).replace(' OR ', '|')})\b"
    else:
        pattern = rf"\b{re.escape(base)}\b"
    return bool(re.search(pattern, title, flags=re.IGNORECASE))


def sync_fear_greed(limit: int = 30) -> int:
    if not settings.use_fear_greed:
        return 0
    payload = _safe_get_json("https://api.alternative.me/fng/", params={"limit": limit, "format": "json"})
    rows = []
    for item in payload.get("data", []):
        day = datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc).date()
        value = float(item["value"])
        score = (value - 50.0) / 50.0
        rows.append((day, "alternative_fng", "MARKET", score, item.get("value_classification"), item))
    return execute_many_values(
        """
        INSERT INTO sentiment_daily(day, source, symbol, score, label, raw_json)
        VALUES %s
        ON CONFLICT(day, source, symbol)
        DO UPDATE SET score=EXCLUDED.score, label=EXCLUDED.label, raw_json=EXCLUDED.raw_json
        """,
        rows,
    )


def fetch_gdelt_news(symbol: str, days: int = 2, maxrecords: int | None = None) -> list[dict[str, Any]]:
    if not settings.use_gdelt:
        return []

    circuit = _gdelt_circuit_status()
    if not circuit["enabled"]:
        # Не логируем каждый символ внутри cooldown: иначе один недоступный GDELT
        # превращается в шум в журнале и маскирует реальные trading/core ошибки.
        return []

    limit = max(1, min(int(maxrecords or settings.gdelt_max_records), int(settings.gdelt_max_records)))
    query = quote_plus(f"({_symbol_query(symbol)}) crypto market")
    timespan = f"{max(1, days)}d"
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=artlist&format=json&maxrecords={limit}&timespan={timespan}"
    try:
        payload = _safe_get_json(url, timeout=settings.gdelt_http_timeout_sec)
        _record_gdelt_success()
        return payload.get("articles", [])
    except Exception as exc:
        _record_gdelt_failure(symbol, exc)
        return []


def _insert_news(rows: list[tuple]) -> int:
    return execute_many_values(
        """
        INSERT INTO news_items(source, symbol, published_at, title, url, source_domain, sentiment_score, llm_score, llm_label, raw_json)
        VALUES %s
        ON CONFLICT(source, url)
        DO UPDATE SET sentiment_score=EXCLUDED.sentiment_score, llm_score=EXCLUDED.llm_score, llm_label=EXCLUDED.llm_label, raw_json=EXCLUDED.raw_json
        """,
        rows,
    )


def _aggregate_news_daily(symbol: str, source: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    by_day: dict[Any, list[float]] = {}
    for _, _, published_at, _, _, _, vader_score, llm_score, _, _ in rows:
        day = (published_at or datetime.now(timezone.utc)).date()
        score = float(llm_score if llm_score is not None else vader_score)
        by_day.setdefault(day, []).append(score)
    daily_rows = [
        (day, source, symbol.upper(), sum(vals) / len(vals), "news_avg", {"n": len(vals)})
        for day, vals in by_day.items()
    ]
    return execute_many_values(
        """
        INSERT INTO sentiment_daily(day, source, symbol, score, label, raw_json)
        VALUES %s
        ON CONFLICT(day, source, symbol)
        DO UPDATE SET score=EXCLUDED.score, label=EXCLUDED.label, raw_json=EXCLUDED.raw_json
        """,
        daily_rows,
    )


def sync_gdelt_news(symbol: str, days: int = 2, use_llm: bool = False) -> int:
    articles = fetch_gdelt_news(symbol, days=days)
    rows = []
    for article in articles:
        title = article.get("title") or ""
        if not title:
            continue
        vader_score = float(_analyzer.polarity_scores(title)["compound"])
        llm_score = None
        llm_label = None
        if use_llm:
            llm = classify_news_with_llm(title, symbol)
            llm_score = llm["score"]
            llm_label = llm["label"]
        published = article.get("seendate")
        published_at = None
        if published:
            try:
                published_at = datetime.strptime(published[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            except Exception:
                published_at = None
        stable_url = _news_url("gdelt", title, article.get("url"), published_at)
        rows.append(("gdelt", symbol.upper(), published_at, title, stable_url, article.get("domain") or urlparse(stable_url).netloc, vader_score, llm_score, llm_label, article))
    inserted = _insert_news(rows)
    _aggregate_news_daily(symbol, "gdelt_news", rows)
    return inserted


def sync_rss_news(symbols: list[str], use_llm: bool = False) -> dict[str, int]:
    if not settings.use_rss:
        return {s.upper(): 0 for s in symbols}
    symbols = [s.upper() for s in symbols]
    per_symbol: dict[str, list[tuple]] = {s: [] for s in symbols}
    market_rows: list[tuple] = []
    for raw_source in settings.rss_urls:
        url, name = _parse_source_def(raw_source)
        if not url:
            continue
        try:
            xml = _safe_get_text(url)
            root = ET.fromstring(xml)
        except Exception as exc:
            logger.warning("RSS source %s failed: %s", name, exc)
            continue
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        for item in items[:120]:
            title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
            title = " ".join(title.split())
            if not title:
                continue
            link = item.findtext("link") or ""
            if not link:
                link_node = item.find("{http://www.w3.org/2005/Atom}link")
                link = link_node.attrib.get("href", "") if link_node is not None else ""
            published_at = _parse_rss_date(item.findtext("pubDate") or item.findtext("published") or item.findtext("updated"))
            vader_score = float(_analyzer.polarity_scores(title)["compound"])
            llm_score = None
            llm_label = None
            if use_llm:
                llm = classify_news_with_llm(title, "MARKET")
                llm_score = llm["score"]
                llm_label = llm["label"]
            raw = {"rss_source": name, "url": url}
            source = f"rss:{name}"
            stable_url = _news_url(source, title, link, published_at)
            row = (source, "MARKET", published_at, title, stable_url, urlparse(stable_url).netloc, vader_score, llm_score, llm_label, raw)
            market_rows.append(row)
            for symbol in symbols:
                if _title_matches_symbol(title, symbol):
                    per_symbol[symbol].append((source, symbol, published_at, title, stable_url, urlparse(stable_url).netloc, vader_score, llm_score, llm_label, raw))
    inserted_market = _insert_news(market_rows)
    result: dict[str, int] = {"MARKET": inserted_market}
    _aggregate_news_daily("MARKET", "rss_news", market_rows)
    for symbol, rows in per_symbol.items():
        result[symbol] = _insert_news(rows)
        _aggregate_news_daily(symbol, "rss_news", rows)
    return result


def sync_cryptopanic(symbol: str, use_llm: bool = False) -> int:
    if not settings.use_cryptopanic or not settings.cryptopanic_token:
        return 0
    base = _base_symbol(symbol)
    params = {"auth_token": settings.cryptopanic_token, "currencies": base, "filter": "hot", "public": "true"}
    try:
        payload = _safe_get_json("https://cryptopanic.com/api/developer/v2/posts/", params=params)
    except Exception as exc:
        logger.warning("CryptoPanic sync failed for %s: %s", symbol, exc)
        return 0
    rows = []
    for item in payload.get("results", []):
        title = item.get("title") or ""
        if not title:
            continue
        vader_score = float(_analyzer.polarity_scores(title)["compound"])
        llm_score = None
        llm_label = None
        if use_llm:
            llm = classify_news_with_llm(title, symbol)
            llm_score = llm["score"]
            llm_label = llm["label"]
        published_at = None
        if item.get("published_at"):
            try:
                published_at = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
            except Exception:
                published_at = None
        stable_url = _news_url("cryptopanic", title, item.get("url"), published_at)
        rows.append(("cryptopanic", symbol.upper(), published_at, title, stable_url, urlparse(stable_url).netloc, vader_score, llm_score, llm_label, item))
    inserted = _insert_news(rows)
    _aggregate_news_daily(symbol, "cryptopanic_news", rows)
    return inserted


def sync_market_sentiment(symbol: str, category: str = "linear", interval: str = "60", limit: int = 500) -> int:
    if not settings.use_market_sentiment:
        return 0
    df = load_market_frame(category, symbol, interval, limit=limit)
    if df.empty or len(df) < 80:
        return 0
    rows = []
    for _, row in df.tail(240).iterrows():
        ret_24 = float(row.get("ret_24", 0) or 0)
        oi_chg = float(row.get("oi_change_24", 0) or 0)
        funding = float(row.get("funding_rate", 0) or 0)
        vol_z = float(row.get("volume_z", 0) or 0)
        trend = float(row.get("ema20_50_gap", 0) or 0)
        score = 0.0
        score += max(-0.4, min(0.4, ret_24 * 8.0))
        score += max(-0.25, min(0.25, trend * 10.0))
        score += max(-0.20, min(0.20, oi_chg * 4.0))
        # Crowded funding is contrarian, so very positive funding lowers score and negative funding raises score.
        score += max(-0.20, min(0.20, -funding * 180.0))
        score += max(-0.10, min(0.10, vol_z * 0.025))
        score = max(-1.0, min(1.0, score))
        components = {"ret_24": ret_24, "oi_change_24": oi_chg, "funding_rate": funding, "volume_z": vol_z, "ema20_50_gap": trend}
        rows.append((row["start_time"], "market_microstructure", symbol.upper(), interval, score, _label_from_score(score), components))
    return execute_many_values(
        """
        INSERT INTO sentiment_intraday(ts, source, symbol, interval, score, label, components)
        VALUES %s
        ON CONFLICT(ts, source, symbol, interval)
        DO UPDATE SET score=EXCLUDED.score, label=EXCLUDED.label, components=EXCLUDED.components
        """,
        rows,
    )


def sync_sentiment_bundle(symbols: list[str], days: int, use_llm: bool = False, category: str = "linear", interval: str = "60") -> dict[str, Any]:
    result = sync_sentiment_bundle_multi(symbols, days, [interval], use_llm=use_llm, category=category)
    # Обратная совместимость: старый endpoint возвращал market_microstructure одним числом,
    # а не словарем по таймфреймам. Multi-timeframe контур использует новую функцию ниже.
    for symbol, payload in result.get("symbols", {}).items():
        intervals = payload.get("market_microstructure_by_interval", {})
        payload["market_microstructure"] = intervals.get(interval, 0)
    return result


def sync_sentiment_bundle_multi(
    symbols: list[str],
    days: int,
    intervals: list[str] | tuple[str, ...],
    use_llm: bool = False,
    category: str = "linear",
) -> dict[str, Any]:
    symbols = [s.upper() for s in symbols]
    normalized_intervals = []
    for interval in intervals:
        value = str(interval).strip().upper()
        if value and value not in normalized_intervals:
            normalized_intervals.append(value)

    deadline = time.monotonic() + max(15, int(settings.sentiment_sync_budget_sec))
    skipped: list[str] = []

    fear_greed = 0
    if _has_sentiment_budget(deadline):
        fear_greed = sync_fear_greed(limit=max(30, days + 5))
    else:
        skipped.append("fear_greed")

    rss_news: dict[str, int] = {"MARKET": 0, **{s: 0 for s in symbols}}
    if _has_sentiment_budget(deadline):
        rss_news = sync_rss_news(symbols, use_llm=use_llm)
    else:
        skipped.append("rss_news")

    result: dict[str, Any] = {
        "fear_greed": fear_greed,
        "rss_news": rss_news,
        "symbols": {},
        "intervals": normalized_intervals,
        "cryptopanic_enabled": bool(settings.use_cryptopanic and settings.cryptopanic_token),
        "budget_sec": int(settings.sentiment_sync_budget_sec),
        "gdelt_circuit": _gdelt_circuit_status(),
        "skipped": skipped,
    }
    for symbol in symbols:
        gdelt = 0
        cp = 0
        gdelt_status = _gdelt_circuit_status()
        if not gdelt_status["enabled"]:
            skipped.append(f"{symbol}:gdelt_cooldown")
        elif _has_sentiment_budget(deadline):
            gdelt = sync_gdelt_news(symbol, days=min(max(days, 1), 7), use_llm=use_llm)
        else:
            skipped.append(f"{symbol}:gdelt")
        if _has_sentiment_budget(deadline):
            cp = sync_cryptopanic(symbol, use_llm=use_llm)
        else:
            skipped.append(f"{symbol}:cryptopanic")
        market_by_interval: dict[str, int] = {}
        for interval in normalized_intervals:
            if not _has_sentiment_budget(deadline):
                skipped.append(f"{symbol}:{interval}:market_microstructure")
                market_by_interval[interval] = 0
                continue
            # Рыночный micro-sentiment зависит от свечного таймфрейма. Его нельзя
            # считать один раз для 1h и молча переиспользовать для 15m/4h.
            market_by_interval[interval] = sync_market_sentiment(symbol, category=category, interval=interval)
        result["symbols"][symbol] = {
            "gdelt_news": gdelt,
            "cryptopanic_news": cp,
            "market_microstructure_by_interval": market_by_interval,
        }
    result["skipped"] = skipped
    result["gdelt_circuit"] = _gdelt_circuit_status()
    return result

def sentiment_summary(symbol: str = "BTCUSDT", limit: int = 20) -> dict[str, Any]:
    symbol = symbol.upper()
    daily = fetch_all(
        """
        SELECT day, source, symbol, score, label
        FROM sentiment_daily
        WHERE symbol IN (%s, 'MARKET')
        ORDER BY day DESC, source
        LIMIT %s
        """,
        (symbol, limit),
    )
    intraday = fetch_all(
        """
        SELECT ts, source, symbol, interval, score, label, components
        FROM sentiment_intraday
        WHERE symbol=%s
        ORDER BY ts DESC, source
        LIMIT %s
        """,
        (symbol, limit),
    )
    return {"daily": daily, "intraday": intraday}
