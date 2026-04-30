from __future__ import annotations

import sys

from .config import BASE_DIR
from .db import DatabaseConnectionError, get_conn, masked_connection_info


def migrate_v20_strategy_lab() -> None:
    migration_path = BASE_DIR / "sql" / "migrations" / "20260430_v20_strategy_lab.sql"
    sql = migration_path.read_text(encoding="utf-8")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)


def main() -> int:
    try:
        migrate_v20_strategy_lab()
    except DatabaseConnectionError as exc:
        print("Не удалось подключиться к PostgreSQL для V20 migration.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("\nПроверяемые параметры:", masked_connection_info(), file=sys.stderr)
        return 2
    print("V20 Strategy Lab migration applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
