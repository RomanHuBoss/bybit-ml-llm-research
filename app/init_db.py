from __future__ import annotations

import sys
from pathlib import Path

from .config import BASE_DIR
from .db import DatabaseConnectionError, get_conn, masked_connection_info


def init_db() -> None:
    schema_path = BASE_DIR / "sql" / "schema.sql"
    sql = schema_path.read_text(encoding="utf-8")
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql)


def main() -> int:
    try:
        init_db()
    except DatabaseConnectionError as exc:
        print("Не удалось инициализировать PostgreSQL.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print("\nПроверяемые параметры:", masked_connection_info(), file=sys.stderr)
        print(
            "\nМинимальная ручная проверка:\n"
            "1) Убедитесь, что PostgreSQL запущен.\n"
            "2) Убедитесь, что база и пользователь из .env существуют.\n"
            "3) Проверьте подключение через psql той же учетной записью.\n"
            "4) Если пароль содержит кириллицу или нестандартные символы, временно замените его на ASCII.",
            file=sys.stderr,
        )
        return 2
    print("PostgreSQL schema initialized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
