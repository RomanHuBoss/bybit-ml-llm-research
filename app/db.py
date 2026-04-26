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
from .serialization import to_jsonable


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


def _adapt_params(params: tuple | dict | None) -> tuple | dict | None:
    if params is None:
        return None
    if isinstance(params, tuple):
        return tuple(_adapt_value(value) for value in params)
    if isinstance(params, dict):
        return {key: _adapt_value(value) for key, value in params.items()}
    return params


def execute(sql: str, params: tuple | dict | None = None) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, _adapt_params(params))
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

    # Не используем pandas.read_sql_query с raw psycopg2 connection: начиная с pandas 2.x
    # это стабильно печатает UserWarning и может засорять production-логи при каждом запросе.
    # Для текущего проекта достаточно DB-API cursor: он сохраняет параметризацию SQL,
    # не добавляет тяжелую зависимость SQLAlchemy и возвращает DataFrame с корректными именами колонок.
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchall() if columns else []
    return pd.DataFrame(rows, columns=columns)


def json_safe(obj: Any) -> Any:
    # Обратная совместимость для старых импортов: фактическая JSON-нормализация
    # вынесена в app.serialization и используется также LLM endpoint.
    return to_jsonable(obj)
