from __future__ import annotations

import sys

from .db import DatabaseConnectionError, get_conn, masked_connection_info


def main() -> int:
    print("PostgreSQL connection:", masked_connection_info())
    try:
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("select version(), current_database(), current_user")
            version, db_name, user_name = cur.fetchone()
    except DatabaseConnectionError as exc:
        print("DB check failed.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2
    print("DB check OK.")
    print(f"Database: {db_name}")
    print(f"User: {user_name}")
    print(f"Server: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
