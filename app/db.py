from __future__ import annotations

import json
from contextlib import contextmanager
from decimal import Decimal
from typing import Any, Iterable

import pandas as pd

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor, execute_values
except ModuleNotFoundError:  # pragma: no cover - используется только в средах без установленного PostgreSQL-драйвера.
    psycopg2 = None  # type: ignore[assignment]

    class Json:  # type: ignore[no-redef]
        def __init__(self, value: Any) -> None:
            self.value = value

    RealDictCursor = None  # type: ignore[assignment]

    def execute_values(*_args: Any, **_kwargs: Any) -> None:  # type: ignore[no-redef]
        raise RuntimeError("psycopg2-binary is not installed; database writes are unavailable")

from .config import settings


def _adapt_value(value: Any) -> Any:
    if isinstance(value, dict) or isinstance(value, list):
        return Json(value)
    if hasattr(value, "item"):
        return value.item()
    return value


@contextmanager
def get_conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2-binary is not installed. Install requirements.txt before using the database.")
    conn = psycopg2.connect(settings.dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql: str, params: tuple | dict | None = None) -> list[dict[str, Any]]:
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def fetch_one(sql: str, params: tuple | dict | None = None) -> dict[str, Any] | None:
    with get_conn() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def execute(sql: str, params: tuple | dict | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def execute_many_values(sql: str, rows: Iterable[tuple], page_size: int = 1000) -> int:
    rows = [tuple(_adapt_value(v) for v in row) for row in rows]
    if not rows:
        return 0
    with get_conn() as conn, conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=page_size)
        return cur.rowcount


def query_df(sql: str, params: tuple | dict | None = None) -> pd.DataFrame:
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def json_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)
