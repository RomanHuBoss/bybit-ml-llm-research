from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .bybit_client import sync_liquidity_snapshots
from .config import settings
from .db import execute_many_values, fetch_all


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def latest_liquidity(category: str = "linear", limit: int = 100) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        WITH latest AS (SELECT MAX(captured_at) AS captured_at FROM liquidity_snapshots WHERE category=%s)
        SELECT l.symbol, l.captured_at, l.turnover_24h, l.volume_24h, l.open_interest_value,
               l.spread_pct, l.funding_rate, l.listing_age_days, l.liquidity_score, l.is_eligible,
               l.last_price
        FROM liquidity_snapshots l
        JOIN latest x ON x.captured_at = l.captured_at
        WHERE l.category=%s
        ORDER BY l.is_eligible DESC, l.liquidity_score DESC
        LIMIT %s
        """,
        (category, category, limit),
    )
    return rows


def refresh_liquidity(category: str = "linear") -> dict[str, Any]:
    inserted = sync_liquidity_snapshots(category)
    return {"inserted": inserted, "latest": latest_liquidity(category, settings.dynamic_symbol_limit)}


def build_universe(category: str = "linear", mode: str | None = None, limit: int | None = None, refresh: bool = False) -> dict[str, Any]:
    mode = (mode or settings.symbol_mode).lower()
    limit = int(limit or settings.universe_limit)
    if refresh:
        sync_liquidity_snapshots(category)

    dynamic = [r for r in latest_liquidity(category, max(limit * 3, settings.dynamic_symbol_limit)) if r.get("is_eligible")]
    dynamic_symbols = [str(r["symbol"]).upper() for r in dynamic]
    score_map = {str(r["symbol"]).upper(): float(r.get("liquidity_score") or 0) for r in dynamic}
    components_map = {str(r["symbol"]).upper(): _jsonable(r) for r in dynamic}

    if mode == "core":
        symbols = [s for s in settings.core_symbols if s not in settings.exclude_symbols]
    elif mode == "dynamic":
        symbols = dynamic_symbols
    else:
        merged: list[str] = []
        for sym in list(settings.core_symbols) + dynamic_symbols:
            if sym not in merged and sym not in settings.exclude_symbols:
                merged.append(sym)
        symbols = merged

    symbols = symbols[:limit]
    selected_at = datetime.now(timezone.utc)
    rows = []
    for idx, sym in enumerate(symbols, start=1):
        comp = components_map.get(sym, {})
        reason = "core" if sym in settings.core_symbols else "dynamic_liquidity"
        rows.append((selected_at, category, mode, sym, idx, score_map.get(sym, 0.0), reason, comp))
    inserted = execute_many_values(
        """
        INSERT INTO symbol_universe(selected_at, category, mode, symbol, rank_no, liquidity_score, reason, components)
        VALUES %s
        ON CONFLICT(category, mode, symbol, selected_at) DO NOTHING
        """,
        rows,
    )
    return {"selected_at": selected_at.isoformat(), "mode": mode, "inserted": inserted, "symbols": symbols, "items": rows_to_items(rows)}


def rows_to_items(rows: list[tuple]) -> list[dict[str, Any]]:
    return [
        {
            "selected_at": r[0].isoformat() if hasattr(r[0], "isoformat") else str(r[0]),
            "category": r[1],
            "mode": r[2],
            "symbol": r[3],
            "rank_no": r[4],
            "liquidity_score": float(r[5]),
            "reason": r[6],
            "components": r[7],
        }
        for r in rows
    ]


def latest_universe(category: str = "linear", mode: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    params: tuple[Any, ...]
    where_mode = ""
    if mode:
        where_mode = "AND mode=%s"
        params = (category, mode, category, mode, limit)
    else:
        params = (category, category, limit)
    return fetch_all(
        f"""
        WITH latest AS (
            SELECT MAX(selected_at) AS selected_at
            FROM symbol_universe
            WHERE category=%s {where_mode}
        )
        SELECT u.selected_at, u.category, u.mode, u.symbol, u.rank_no, u.liquidity_score, u.reason, u.components
        FROM symbol_universe u
        JOIN latest x ON x.selected_at = u.selected_at
        WHERE u.category=%s {where_mode}
        ORDER BY u.rank_no
        LIMIT %s
        """,
        params,
    )
