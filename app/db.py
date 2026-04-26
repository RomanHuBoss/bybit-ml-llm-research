from __future__ import annotations

import json
import socket
from contextlib import contextmanager
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
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


class DatabaseConnectionError(RuntimeError):
    """Понятная ошибка подключения к PostgreSQL без утечки пароля из .env."""


TRANSIENT_CONNECT_HINT = (
    "Проверьте, что PostgreSQL запущен, база и пользователь из .env созданы, "
    "пароль указан верно, а хост/порт доступны. На Windows при русской локали "
    "psycopg2 иногда падает UnicodeDecodeError вместо исходной ошибки libpq; "
    "чаще всего первопричина — неверный пользователь/пароль, отсутствующая база "
    "или недоступный PostgreSQL. Используйте ASCII-пароль для локальной БД и UTF-8 .env."
)


def _adapt_value(value: Any) -> Any:
    if isinstance(value, dict) or isinstance(value, list):
        return Json(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def _connect_kwargs() -> dict[str, Any]:
    # Передаем параметры отдельно, а не единой DSN-строкой: так безопаснее для паролей
    # со спецсимволами и проще печатать диагностическую информацию без секрета.
    return {
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "dbname": settings.postgres_db,
        "user": settings.postgres_user,
        "password": settings.postgres_password,
        "connect_timeout": settings.postgres_connect_timeout_sec,
    }


def masked_connection_info() -> str:
    return (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        "password=<hidden>"
    )


def _tcp_preflight() -> None:
    if str(settings.postgres_host).startswith("/"):
        # Unix socket path: TCP-проверка неприменима, дальше проверяет сам libpq.
        return
    # Быстрая проверка сетевой доступности дает нормальную ошибку до вызова libpq.
    # Это не заменяет аутентификацию PostgreSQL, но отсекает частый случай: сервер не запущен.
    timeout = max(1.0, float(settings.postgres_connect_timeout_sec))
    try:
        with socket.create_connection(
            (settings.postgres_host, int(settings.postgres_port)),
            timeout=timeout,
        ):
            return
    except OSError as exc:
        raise DatabaseConnectionError(
            "PostgreSQL недоступен по TCP: "
            f"{masked_connection_info()}. Детали: {exc}. {TRANSIENT_CONNECT_HINT}"
        ) from exc


def connect_raw():
    """Создает raw-соединение PostgreSQL с диагностикой, пригодной для CLI и API."""
    if psycopg2 is None:
        raise DatabaseConnectionError(
            "psycopg2-binary не установлен. Выполните `python install.py` "
            "или `python -m pip install -r requirements.txt`."
        )
    _tcp_preflight()
    try:
        conn = psycopg2.connect(**_connect_kwargs())
        # Явно фиксируем клиентскую кодировку для чтения/записи данных после подключения.
        # Ошибки аутентификации происходят раньше, поэтому они дополнительно ловятся ниже.
        conn.set_client_encoding("UTF8")
        return conn
    except UnicodeDecodeError as exc:
        raise DatabaseConnectionError(
            "psycopg2 не смог декодировать сообщение libpq при подключении к PostgreSQL: "
            f"{exc}. Параметры: {masked_connection_info()}. {TRANSIENT_CONNECT_HINT} "
            "Для точной первопричины выполните: "
            f"psql -h {settings.postgres_host} -p {settings.postgres_port} "
            f"-U {settings.postgres_user} -d {settings.postgres_db} -c \"select 1;\""
        ) from exc
    except Exception as exc:
        raise DatabaseConnectionError(
            "Ошибка подключения к PostgreSQL: "
            f"{exc}. Параметры: {masked_connection_info()}. {TRANSIENT_CONNECT_HINT}"
        ) from exc


@contextmanager
def get_conn():
    conn = connect_raw()
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


def query_df(sql: str, params: tuple | dict | None = None) -> "pd.DataFrame":
    import pandas as pd

    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def json_safe(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    try:
        import pandas as pd

        if isinstance(obj, pd.Timestamp):
            return obj.isoformat()
    except ModuleNotFoundError:
        pass
    try:
        json.dumps(obj)
        return obj
    except TypeError:
        return str(obj)
