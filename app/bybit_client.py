from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests

from .config import settings
from .db import execute_many_values
from .market_data_quality import validate_ohlcv_values

logger = logging.getLogger(__name__)


_BYBIT_REQUEST_SEMAPHORE = threading.BoundedSemaphore(max(1, int(settings.bybit_max_concurrent_requests)))


class BybitAPIError(RuntimeError):
    def __init__(self, message: str, *, ret_code: int | None = None, transient: bool = False) -> None:
        super().__init__(message)
        self.ret_code = ret_code
        self.transient = transient


TRANSIENT_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
MAX_BYBIT_CURSOR_PAGES = 200


def _parse_ret_code(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


TRANSIENT_BYBIT_RET_CODES = {
    10000,  # Server timeout.
    10006,  # Too many visits / rate limit.
    10016,  # Service is restarting / internal error.
    10429,  # System-level frequency protection.
    170007,  # Timeout waiting for response from backend service.
}


def _result_list(result: dict[str, Any], endpoint: str) -> list[Any]:
    items = result.get("list", [])
    if items is None:
        return []
    if not isinstance(items, list):
        raise BybitAPIError(f"Bybit {endpoint} result.list has unexpected type: {type(items).__name__}")
    return items


@dataclass
class BybitClient:
    base_url: str = settings.bybit_base_url
    sleep_sec: float = settings.bybit_request_sleep_sec

    def _sleep_before_retry(self, attempt: int) -> None:
        delay = settings.bybit_retry_backoff_sec * (2 ** attempt)
        delay += random.uniform(0, settings.bybit_retry_backoff_sec)
        time.sleep(min(delay, 20.0))

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(settings.bybit_max_retries + 1):
            transient = False
            try:
                # Даже при параллельной загрузке истории держим общий лимит
                # одновременных HTTP-запросов к Bybit. Иначе ускорение легко
                # превращается в retCode=10006/10429 и каскад retry.
                with _BYBIT_REQUEST_SEMAPHORE:
                    response = requests.get(
                        url,
                        params=params,
                        timeout=settings.bybit_timeout_sec,
                        headers={"User-Agent": "bybit-ml-llm-research-lab/2.1"},
                    )
                if response.status_code in TRANSIENT_HTTP_STATUSES:
                    transient = True
                    raise BybitAPIError(
                        f"Bybit transient HTTP status {response.status_code}: {response.text[:300]}",
                        transient=True,
                    )
                response.raise_for_status()
                try:
                    payload = response.json()
                except ValueError as exc:
                    raise BybitAPIError(f"Bybit returned non-JSON response: {response.text[:300]}") from exc
                ret_code_raw = payload.get("retCode")
                ret_code = _parse_ret_code(ret_code_raw)
                if ret_code != 0:
                    # Bybit обычно возвращает retCode числом, но защитный парсер нужен,
                    # чтобы нестандартный gateway/body не превращался в ValueError вне
                    # retry-контракта клиента и не маскировал реальную ошибку API.
                    transient = ret_code in TRANSIENT_BYBIT_RET_CODES if ret_code is not None else False
                    raise BybitAPIError(
                        f"Bybit retCode={ret_code_raw}, retMsg={payload.get('retMsg')}, params={params}",
                        ret_code=ret_code,
                        transient=transient,
                    )
                result = payload.get("result", {})
                if not isinstance(result, dict):
                    raise BybitAPIError(f"Bybit result has unexpected type: {type(result).__name__}")
                return result
            except requests.RequestException as exc:
                transient = True
                last_exc = exc
            except BybitAPIError as exc:
                last_exc = exc
                transient = exc.transient or transient
            finally:
                if self.sleep_sec > 0:
                    time.sleep(self.sleep_sec)

            if not transient or attempt >= settings.bybit_max_retries:
                break
            logger.warning("Transient Bybit error on %s, retry %s/%s: %s", path, attempt + 1, settings.bybit_max_retries, last_exc)
            self._sleep_before_retry(attempt)
        raise BybitAPIError(f"Bybit request failed after retries: {last_exc}") from last_exc

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
        return _result_list(result, "/v5/market/kline")

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
        return _result_list(result, "/v5/market/funding/history")

    def get_open_interest(
        self,
        category: str,
        symbol: str,
        interval_time: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        base_params: dict[str, Any] = {"category": category, "symbol": symbol.upper(), "intervalTime": interval_time, "limit": limit}
        if start_ms is not None:
            base_params["startTime"] = start_ms
        if end_ms is not None:
            base_params["endTime"] = end_ms

        all_items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page_no in range(MAX_BYBIT_CURSOR_PAGES):
            params = dict(base_params)
            if cursor:
                params["cursor"] = cursor
            result = self._get("/v5/market/open-interest", params)
            all_items.extend(_result_list(result, "/v5/market/open-interest"))
            next_cursor = result.get("nextPageCursor") or None
            if not next_cursor:
                break
            next_cursor = str(next_cursor)
            if next_cursor in seen_cursors:
                raise BybitAPIError(f"Bybit open-interest cursor loop detected: {next_cursor!r}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise BybitAPIError(f"Bybit open-interest exceeded {MAX_BYBIT_CURSOR_PAGES} cursor pages")
        return all_items

    def get_tickers(self, category: str = "linear") -> list[dict[str, Any]]:
        result = self._get("/v5/market/tickers", {"category": category})
        return _result_list(result, "/v5/market/tickers")

    def get_instruments_info(self, category: str = "linear") -> list[dict[str, Any]]:
        all_items: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page_no in range(MAX_BYBIT_CURSOR_PAGES):
            params: dict[str, Any] = {"category": category, "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            result = self._get("/v5/market/instruments-info", params)
            items = result.get("list", [])
            if not isinstance(items, list):
                raise BybitAPIError("Bybit instruments-info result.list has unexpected type")
            all_items.extend(items)
            next_cursor = result.get("nextPageCursor") or None
            if not next_cursor:
                break
            next_cursor = str(next_cursor)
            if next_cursor in seen_cursors:
                raise BybitAPIError(f"Bybit instruments-info cursor loop detected: {next_cursor!r}")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise BybitAPIError(f"Bybit instruments-info exceeded {MAX_BYBIT_CURSOR_PAGES} cursor pages")
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


def _is_closed_candle(start_time: datetime, interval: str, now: datetime | None = None) -> bool:
    """Проверяет, что свеча полностью закрыта до использования в сигналах.

    Bybit возвращает текущую незакрытую свечу вместе с историей; ее close является
    последней сделкой, а не финальной ценой бара. Для рекомендательной системы это
    опасно: сигнал может исчезнуть после закрытия свечи.
    """
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return start_time + timedelta(minutes=_interval_to_minutes(interval)) <= now


def _is_supported_liquidity_symbol(category: str, symbol: str) -> bool:
    if category == "inverse":
        return symbol.endswith("USD") and not symbol.endswith("USDT")
    # Текущие core-настройки и риск-фильтры проекта рассчитаны на USDT-котируемые пары.
    return symbol.endswith("USDT")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _page_ranges(start: datetime, end: datetime, step: timedelta) -> list[tuple[datetime, datetime]]:
    ranges: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + step, end)
        ranges.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(milliseconds=1)
    return ranges


def _parse_kline_item(category: str, symbol: str, interval: str, item: list[Any], now: datetime) -> tuple | None:
    """Парсит и валидирует Bybit kline item перед записью в БД.

    Public API может вернуть неполную строку, текущую незакрытую свечу или битые
    числовые значения после сетевого/gateway сбоя. Такие бары нельзя использовать
    для ATR, entry, SL/TP и R/R: безопаснее пропустить их и оставить оператору
    последний доказуемо валидный закрытый рынок.
    """
    if not isinstance(item, list) or len(item) < 6:
        logger.warning("skip malformed Bybit kline item for %s %s %s: %r", category, symbol, interval, item)
        return None
    try:
        start_time = _ms_to_dt(item[0])
    except Exception:
        logger.warning("skip kline with invalid start_time for %s %s %s: %r", category, symbol, interval, item[:1])
        return None
    if not _is_closed_candle(start_time, interval, now):
        return None
    ok, reason, values = validate_ohlcv_values(
        item[1],
        item[2],
        item[3],
        item[4],
        item[5],
        item[6] if len(item) > 6 else None,
    )
    if not ok:
        logger.warning(
            "skip invalid Bybit candle for %s %s %s at %s: %s",
            category,
            symbol,
            interval,
            start_time.isoformat(),
            reason,
        )
        return None
    return (
        category,
        symbol.upper(),
        interval,
        start_time,
        values["open"],
        values["high"],
        values["low"],
        values["close"],
        values["volume"],
        values["turnover"],
    )


def sync_candles(category: str, symbol: str, interval: str, days: int) -> int:
    client = BybitClient()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    step_minutes = _interval_to_minutes(interval) * 900
    inserted = 0
    for cursor, chunk_end in _page_ranges(start, end, timedelta(minutes=step_minutes)):
        rows = client.get_kline(category, symbol, interval, _dt_to_ms(cursor), _dt_to_ms(chunk_end), limit=1000)
        parsed = []
        now = datetime.now(timezone.utc)
        for item in rows:
            parsed_item = _parse_kline_item(category, symbol, interval, item, now)
            if parsed_item is not None:
                parsed.append(parsed_item)
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
    return inserted


def sync_funding(category: str, symbol: str, days: int) -> int:
    if category not in {"linear", "inverse"}:
        return 0
    client = BybitClient()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    # Funding обычно публикуется раз в 8 часов. Окно меньше лимита API защищает от тихой потери старых записей.
    step = timedelta(hours=8 * 180)
    seen: set[datetime] = set()
    parsed = []
    for cursor, chunk_end in _page_ranges(start, end, step):
        rows = client.get_funding_history(category, symbol, _dt_to_ms(cursor), _dt_to_ms(chunk_end), limit=200)
        for item in rows:
            ts_raw = item.get("fundingRateTimestamp")
            if ts_raw is None:
                continue
            ts = _ms_to_dt(ts_raw)
            if ts in seen:
                continue
            seen.add(ts)
            parsed.append((category, symbol.upper(), ts, item.get("fundingRate", 0)))
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


def _oi_interval_minutes(oi_interval: str) -> int:
    return {"5min": 5, "15min": 15, "30min": 30, "1h": 60, "4h": 240, "1d": 1440}.get(oi_interval, 60)


def sync_open_interest(category: str, symbol: str, interval: str, days: int) -> int:
    if category not in {"linear", "inverse"}:
        return 0
    client = BybitClient()
    oi_interval = interval_to_oi_interval(interval)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    step = timedelta(minutes=_oi_interval_minutes(oi_interval) * 180)
    seen: set[datetime] = set()
    parsed = []
    for cursor, chunk_end in _page_ranges(start, end, step):
        rows = client.get_open_interest(category, symbol, oi_interval, _dt_to_ms(cursor), _dt_to_ms(chunk_end), limit=200)
        for item in rows:
            ts_raw = item.get("timestamp")
            if ts_raw is None:
                continue
            ts = _ms_to_dt(ts_raw)
            if ts in seen:
                continue
            seen.add(ts)
            parsed.append((category, symbol.upper(), oi_interval, ts, item.get("openInterest", 0)))
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
        if not _is_supported_liquidity_symbol(category, symbol) or symbol in settings.exclude_symbols:
            continue
        inst = instruments.get(symbol, {})
        # PreLaunch исключён намеренно: в исследовательский universe не должны попадать инструменты без нормальной торговли.
        if inst and inst.get("status") not in {"Trading", None, ""}:
            continue
        turnover = _to_float(item.get("turnover24h"))
        volume = _to_float(item.get("volume24h"))
        oi_value = _to_float(item.get("openInterestValue"))
        bid = _to_float(item.get("bid1Price"))
        ask = _to_float(item.get("ask1Price"))
        last = _to_float(item.get("lastPrice"))
        spread_pct = ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask > 0 and ask >= bid else 999.0
        funding = _to_float(item.get("fundingRate"))
        age_days = _listing_age_days(inst)
        requires_open_interest = category in {"linear", "inverse"}
        oi_ok = (oi_value >= settings.min_open_interest_value) if requires_open_interest else True
        eligible = (
            turnover >= settings.min_turnover_24h
            and oi_ok
            and spread_pct <= settings.max_spread_pct
            and age_days is not None
            and age_days >= settings.min_listing_age_days
        )
        import math

        turnover_score = math.log10(max(turnover, 1.0))
        oi_score = math.log10(max(oi_value, 1.0))
        spread_score = max(0.0, 1.0 - min(spread_pct / max(settings.max_spread_pct, 0.001), 2.0) / 2.0)
        age_score = min((age_days or 0) / 180.0, 1.0)
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
