from __future__ import annotations

from pathlib import Path

from .config import BASE_DIR
from .db import get_conn


def init_db() -> None:
    schema_path = BASE_DIR / "sql" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)


if __name__ == "__main__":
    init_db()
    print("PostgreSQL schema initialized.")
