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
        WITH latest AS (
            SELECT DISTINCT ON (l.symbol)
                   l.symbol, l.captured_at, l.turnover_24h, l.volume_24h, l.open_interest_value,
                   l.spread_pct, l.funding_rate, l.listing_age_days, l.liquidity_score, l.is_eligible,
                   l.last_price,
                   (l.captured_at >= NOW() - (%s::text || ' minutes')::interval) AS liquidity_is_fresh
            FROM liquidity_snapshots l
            WHERE l.category=%s
            ORDER BY l.symbol, l.captured_at DESC
        )
        SELECT symbol, captured_at,
               CASE WHEN liquidity_is_fresh THEN turnover_24h ELSE NULL END AS turnover_24h,
               CASE WHEN liquidity_is_fresh THEN volume_24h ELSE NULL END AS volume_24h,
               CASE WHEN liquidity_is_fresh THEN open_interest_value ELSE NULL END AS open_interest_value,
               CASE WHEN liquidity_is_fresh THEN spread_pct ELSE NULL END AS spread_pct,
               CASE WHEN liquidity_is_fresh THEN funding_rate ELSE NULL END AS funding_rate,
               listing_age_days,
               CASE WHEN liquidity_is_fresh THEN liquidity_score ELSE 0 END AS liquidity_score,
               CASE WHEN liquidity_is_fresh THEN is_eligible ELSE FALSE END AS is_eligible,
               last_price,
               CASE WHEN liquidity_is_fresh THEN 'fresh' ELSE 'stale' END AS liquidity_status
        FROM latest
        ORDER BY is_eligible DESC, liquidity_score DESC
        LIMIT %s
        """,
        (settings.liquidity_snapshot_max_age_minutes, category, limit),
    )
    return rows


def refresh_liquidity(category: str = "linear") -> dict[str, Any]:
    inserted = sync_liquidity_snapshots(category)
    return {"upserted": inserted, "latest": latest_liquidity(category, settings.dynamic_symbol_limit)}


def _select_core_symbols(latest_rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    latest_by_symbol = {str(r["symbol"]).upper(): r for r in latest_rows}
    selected: list[str] = []
    reasons: dict[str, str] = {}
    for sym in settings.core_symbols:
        if sym in settings.exclude_symbols:
            continue
        row = latest_by_symbol.get(sym)
        if row and row.get("is_eligible"):
            selected.append(sym)
            reasons[sym] = "core_liquidity_verified"
        elif settings.allow_unverified_core_symbols:
            selected.append(sym)
            reasons[sym] = "core_unverified_manual_override"
    return selected, reasons


def build_universe(category: str = "linear", mode: str | None = None, limit: int | None = None, refresh: bool = False) -> dict[str, Any]:
    mode = (mode or settings.symbol_mode).lower()
    limit = int(limit or settings.universe_limit)
    if refresh:
        sync_liquidity_snapshots(category)

    latest_rows = latest_liquidity(category, max(limit * 3, settings.dynamic_symbol_limit, len(settings.core_symbols)))
    dynamic = [r for r in latest_rows if r.get("is_eligible")]
    dynamic_symbols = [str(r["symbol"]).upper() for r in dynamic]
    score_map = {str(r["symbol"]).upper(): float(r.get("liquidity_score") or 0) for r in latest_rows}
    components_map = {str(r["symbol"]).upper(): _jsonable(r) for r in latest_rows}
    core_symbols, reason_map = _select_core_symbols(latest_rows)

    if mode == "core":
        symbols = core_symbols
    elif mode == "dynamic":
        symbols = dynamic_symbols
        reason_map.update({sym: "dynamic_liquidity" for sym in symbols})
    elif mode == "hybrid":
        merged: list[str] = []
        for sym in core_symbols + dynamic_symbols:
            if sym not in merged and sym not in settings.exclude_symbols:
                merged.append(sym)
                reason_map.setdefault(sym, "dynamic_liquidity")
        symbols = merged
    else:
        raise ValueError(f"Unknown symbol universe mode: {mode}")

    symbols = symbols[:limit]
    selected_at = datetime.now(timezone.utc)
    rows = []
    for idx, sym in enumerate(symbols, start=1):
        comp = components_map.get(sym, {})
        rows.append((selected_at, category, mode, sym, idx, score_map.get(sym, 0.0), reason_map.get(sym, "dynamic_liquidity"), comp))
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
