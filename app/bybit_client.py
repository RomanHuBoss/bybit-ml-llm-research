from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from .config import settings
from .db import execute_many_values


class BybitAPIError(RuntimeError):
    pass


@dataclass
class BybitClient:
    base_url: str = settings.bybit_base_url
    sleep_sec: float = settings.bybit_request_sleep_sec

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = requests.get(
            url,
            params=params,
            timeout=30,
            headers={"User-Agent": "bybit-ml-llm-research-lab/2.0"},
        )
        time.sleep(self.sleep_sec)
        response.raise_for_status()
        payload = response.json()
        if payload.get("retCode") != 0:
            raise BybitAPIError(f"Bybit error: {payload}")
        return payload.get("result", {})

    def get_kline(
        self,
        category: str,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 1000,
    ) -> list[list[str]]:
        params: dict[str, Any] = {"category": category, "symbol": symbol.upper(), "interval": interval, "limit": limit}
        if start_ms is not None:
            params["start"] = start_ms
        if end_ms is not None:
            params["end"] = end_ms
        result = self._get("/v5/market/kline", params)
        return result.get("list", [])

    def get_funding_history(
        self,
        category: str,
        symbol: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "symbol": symbol.upper(), "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        result = self._get("/v5/market/funding/history", params)
        return result.get("list", [])

    def get_open_interest(
        self,
        category: str,
        symbol: str,
        interval_time: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "symbol": symbol.upper(), "intervalTime": interval_time, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        result = self._get("/v5/market/open-interest", params)
        return result.get("list", [])

    def get_tickers(self, category: str = "linear") -> list[dict[str, Any]]:
        result = self._get("/v5/market/tickers", {"category": category})
        return result.get("list", [])

    def get_instruments_info(self, category: str = "linear") -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"category": category, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            result = self._get("/v5/market/instruments-info", params)
            all_items.extend(result.get("list", []))
            cursor = result.get("nextPageCursor") or None
            if not cursor:
                break
        return all_items


def _dt_to_ms(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_dt(ms: int | str) -> datetime:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def _interval_to_minutes(interval: str) -> int:
    if interval.isdigit():
        return int(interval)
    mapping = {"D": 1440, "W": 10080, "M": 43200}
    return mapping.get(interval.upper(), 60)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def sync_candles(category: str, symbol: str, interval: str, days: int) -> int:
    client = BybitClient()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    step_minutes = _interval_to_minutes(interval) * 900
    inserted = 0
    cursor = start

    while cursor < end:
        chunk_end = min(cursor + timedelta(minutes=step_minutes), end)
        rows = client.get_kline(category, symbol, interval, _dt_to_ms(cursor), _dt_to_ms(chunk_end), limit=1000)
        parsed = []
        for item in rows:
            parsed.append(
                (
                    category,
                    symbol.upper(),
                    interval,
                    _ms_to_dt(item[0]),
                    item[1],
                    item[2],
                    item[3],
                    item[4],
                    item[5],
                    item[6] if len(item) > 6 else None,
                )
            )
        inserted += execute_many_values(
            """
            INSERT INTO candles(category, symbol, interval, start_time, open, high, low, close, volume, turnover)
            VALUES %s
            ON CONFLICT(category, symbol, interval, start_time)
            DO UPDATE SET open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close,
                          volume=EXCLUDED.volume, turnover=EXCLUDED.turnover
            """,
            parsed,
        )
        cursor = chunk_end
    return inserted


def sync_funding(category: str, symbol: str, days: int) -> int:
    if category not in {"linear", "inverse"}:
        return 0
    client = BybitClient()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = client.get_funding_history(category, symbol, _dt_to_ms(start), _dt_to_ms(end), limit=200)
    parsed = [(category, symbol.upper(), _ms_to_dt(item["fundingRateTimestamp"]), item["fundingRate"]) for item in rows]
    return execute_many_values(
        """
        INSERT INTO funding_rates(category, symbol, funding_time, funding_rate)
        VALUES %s
        ON CONFLICT(category, symbol, funding_time)
        DO UPDATE SET funding_rate=EXCLUDED.funding_rate
        """,
        parsed,
    )


def interval_to_oi_interval(interval: str) -> str:
    if interval in {"1", "3", "5"}:
        return "5min"
    if interval == "15":
        return "15min"
    if interval == "30":
        return "30min"
    if interval in {"60", "120"}:
        return "1h"
    if interval == "240":
        return "4h"
    if interval.upper() in {"D", "1D"}:
        return "1d"
    return "1h"


def sync_open_interest(category: str, symbol: str, interval: str, days: int) -> int:
    if category not in {"linear", "inverse"}:
        return 0
    client = BybitClient()
    oi_interval = interval_to_oi_interval(interval)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = client.get_open_interest(category, symbol, oi_interval, _dt_to_ms(start), _dt_to_ms(end), limit=200)
    parsed = [(category, symbol.upper(), oi_interval, _ms_to_dt(item["timestamp"]), item["openInterest"]) for item in rows]
    return execute_many_values(
        """
        INSERT INTO open_interest(category, symbol, interval_time, ts, open_interest)
        VALUES %s
        ON CONFLICT(category, symbol, interval_time, ts)
        DO UPDATE SET open_interest=EXCLUDED.open_interest
        """,
        parsed,
    )


def _listing_age_days(instrument: dict[str, Any]) -> int | None:
    launch = instrument.get("launchTime") or instrument.get("launchTimeMs")
    if not launch:
        return None
    try:
        dt = _ms_to_dt(launch)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


def sync_liquidity_snapshots(category: str = "linear") -> int:
    client = BybitClient()
    captured_at = datetime.now(timezone.utc)
    tickers = client.get_tickers(category)
    instruments = {i.get("symbol"): i for i in client.get_instruments_info(category)}
    rows = []
    for item in tickers:
        symbol = str(item.get("symbol", "")).upper()
        if not symbol.endswith("USDT") or symbol in settings.exclude_symbols:
            continue
        inst = instruments.get(symbol, {})
        if inst and inst.get("status") not in {"Trading", "PreLaunch", None, ""}:
            continue
        turnover = _to_float(item.get("turnover24h"))
        volume = _to_float(item.get("volume24h"))
        oi_value = _to_float(item.get("openInterestValue"))
        bid = _to_float(item.get("bid1Price"))
        ask = _to_float(item.get("ask1Price"))
        last = _to_float(item.get("lastPrice"))
        spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask > 0 else 999.0
        funding = _to_float(item.get("fundingRate"))
        age_days = _listing_age_days(inst)
        eligible = (
            turnover >= settings.min_turnover_24h
            and oi_value >= settings.min_open_interest_value
            and spread_pct <= settings.max_spread_pct
            and (age_days is None or age_days >= settings.min_listing_age_days)
        )
        # Log-compressed liquidity score. Spread penalty makes high-volume but thin markets rank lower.
        import math

        turnover_score = math.log10(max(turnover, 1.0))
        oi_score = math.log10(max(oi_value, 1.0))
        spread_score = max(0.0, 1.0 - min(spread_pct / max(settings.max_spread_pct, 0.001), 2.0) / 2.0)
        age_score = min((age_days or settings.min_listing_age_days) / 180.0, 1.0)
        score = 0.45 * turnover_score + 0.35 * oi_score + 0.15 * spread_score + 0.05 * age_score
        rows.append(
            (
                captured_at,
                category,
                symbol,
                turnover,
                volume,
                oi_value,
                bid,
                ask,
                last,
                spread_pct,
                funding,
                age_days,
                score,
                eligible,
                item | {"instrument": inst},
            )
        )
    return execute_many_values(
        """
        INSERT INTO liquidity_snapshots(captured_at, category, symbol, turnover_24h, volume_24h, open_interest_value,
                                        bid1_price, ask1_price, last_price, spread_pct, funding_rate, listing_age_days,
                                        liquidity_score, is_eligible, raw_json)
        VALUES %s
        ON CONFLICT(category, symbol, captured_at) DO NOTHING
        """,
        rows,
    )


def sync_market_bundle(category: str, symbol: str, interval: str, days: int) -> dict[str, int]:
    return {
        "candles": sync_candles(category, symbol, interval, days),
        "funding_rates": sync_funding(category, symbol, days),
        "open_interest": sync_open_interest(category, symbol, interval, days),
    }
