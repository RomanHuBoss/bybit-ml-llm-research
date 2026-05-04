from __future__ import annotations

import argparse
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import BASE_DIR
from .db import DatabaseConnectionError, connect_raw, masked_connection_info


MIGRATIONS_DIR = BASE_DIR / "sql" / "migrations"
SCHEMA_PATH = BASE_DIR / "sql" / "schema.sql"
LEDGER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS public.schema_migrations (
    id BIGSERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    checksum_sha256 TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    execution_ms INTEGER NOT NULL,
    applied_by TEXT NOT NULL DEFAULT CURRENT_USER
);
"""
ADVISORY_LOCK_ID = 202605040043
SCHEMA_LEDGER_NAME = "__schema_sql__"


@dataclass(frozen=True)
class MigrationFile:
    """Физический SQL-файл миграции с неизменяемой контрольной суммой."""

    path: Path
    filename: str
    checksum_sha256: str
    sql: str


def sha256_text(text: str) -> str:
    """Считает checksum от SQL-текста, чтобы обнаруживать тихое изменение миграций."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_sql_file(path: Path) -> MigrationFile:
    sql = path.read_text(encoding="utf-8")
    return MigrationFile(
        path=path,
        filename=path.name,
        checksum_sha256=sha256_text(sql),
        sql=sql,
    )


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR, target: str | None = None) -> list[MigrationFile]:
    """Возвращает миграции в детерминированном порядке имени файла.

    Имена миграций начинаются с даты/версии, поэтому сортировка по имени совпадает
    с безопасным порядком наката. Если задан target, применяются файлы до него
    включительно; это удобно для пошаговой диагностики на боевой копии БД.
    """

    if not migrations_dir.exists():
        raise FileNotFoundError(f"Каталог миграций не найден: {migrations_dir}")
    files = sorted(path for path in migrations_dir.glob("*.sql") if path.is_file())
    if target:
        names = {path.name for path in files}
        if target not in names:
            raise FileNotFoundError(f"Целевая миграция не найдена: {target}")
        files = [path for path in files if path.name <= target]
    return [read_sql_file(path) for path in files]


def _schema_exists(cur) -> bool:
    cur.execute("SELECT to_regclass('public.candles') IS NOT NULL")
    return bool(cur.fetchone()[0])


def _ensure_ledger(cur) -> None:
    cur.execute(LEDGER_TABLE_SQL)


def _applied_migrations(cur) -> dict[str, str]:
    cur.execute("SELECT filename, checksum_sha256 FROM public.schema_migrations")
    return {str(name): str(checksum) for name, checksum in cur.fetchall()}


def _record_migration(cur, migration: MigrationFile, execution_ms: int) -> None:
    cur.execute(
        """
        INSERT INTO public.schema_migrations(filename, checksum_sha256, execution_ms)
        VALUES (%s, %s, %s)
        ON CONFLICT (filename) DO NOTHING
        """,
        (migration.filename, migration.checksum_sha256, execution_ms),
    )


def _apply_sql(cur, sql: str) -> int:
    started = time.perf_counter()
    cur.execute(sql)
    return int((time.perf_counter() - started) * 1000)


def _schema_migration() -> MigrationFile:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"schema.sql не найден: {SCHEMA_PATH}")
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    return MigrationFile(
        path=SCHEMA_PATH,
        filename=SCHEMA_LEDGER_NAME,
        checksum_sha256=sha256_text(sql),
        sql=sql,
    )


def _print_plan(migrations: Iterable[MigrationFile], applied: dict[str, str]) -> int:
    pending = 0
    for migration in migrations:
        checksum = applied.get(migration.filename)
        if checksum is None:
            status = "pending"
            pending += 1
        elif checksum == migration.checksum_sha256:
            status = "applied"
        else:
            status = "checksum-mismatch"
        print(f"{status:18} {migration.filename} {migration.checksum_sha256[:12]}")
    return pending


def apply_migrations(
    *,
    init_schema: bool,
    dry_run: bool,
    list_only: bool,
    target: str | None,
    allow_changed_checksum: bool,
) -> int:
    """Применяет schema.sql при необходимости и все новые SQL-миграции.

    Все изменения выполняются под PostgreSQL advisory lock, чтобы два процесса не
    наложили миграции одновременно. Каждая миграция коммитится отдельно: сбой в
    одном файле не помечает его примененным и не скрывает точную точку отказа.
    """

    migrations = discover_migrations(target=target)
    try:
        conn = connect_raw()
    except DatabaseConnectionError as exc:
        print("Не удалось подключиться к PostgreSQL для применения миграций.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print(f"Параметры: {masked_connection_info()}", file=sys.stderr)
        return 2

    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (ADVISORY_LOCK_ID,))
            conn.commit()

        try:
            with conn.cursor() as cur:
                _ensure_ledger(cur)
                conn.commit()

                schema_exists = _schema_exists(cur)
                applied = _applied_migrations(cur)

                if list_only:
                    if init_schema:
                        schema = _schema_migration()
                        schema_status = "applied" if applied.get(schema.filename) == schema.checksum_sha256 else "pending"
                        if schema_exists and schema.filename not in applied:
                            schema_status = "schema-present"
                        print(f"{schema_status:18} schema.sql {schema.checksum_sha256[:12]}")
                    pending = _print_plan(migrations, applied)
                    print(f"Pending migrations: {pending}")
                    return 0

                if init_schema and not schema_exists:
                    schema = _schema_migration()
                    if dry_run:
                        print(f"DRY-RUN apply schema.sql {schema.checksum_sha256[:12]}")
                    else:
                        print("Applying schema.sql ...")
                        execution_ms = _apply_sql(cur, schema.sql)
                        _record_migration(cur, schema, execution_ms)
                        conn.commit()
                        print(f"Applied schema.sql in {execution_ms} ms")
                    applied = _applied_migrations(cur) if not dry_run else applied
                elif init_schema and schema_exists:
                    print("schema.sql skipped: core tables already exist")

                applied_count = 0
                skipped_count = 0
                for migration in migrations:
                    existing_checksum = applied.get(migration.filename)
                    if existing_checksum == migration.checksum_sha256:
                        print(f"SKIP    {migration.filename}")
                        skipped_count += 1
                        continue
                    if existing_checksum and existing_checksum != migration.checksum_sha256:
                        message = (
                            f"Checksum mismatch for already applied migration {migration.filename}: "
                            f"db={existing_checksum} file={migration.checksum_sha256}. "
                            "Это значит, что SQL-файл был изменен после наката."
                        )
                        if not allow_changed_checksum:
                            raise RuntimeError(message)
                        print(f"WARN    {message}")
                    if dry_run:
                        print(f"DRY-RUN APPLY {migration.filename} {migration.checksum_sha256[:12]}")
                        applied_count += 1
                        continue
                    print(f"APPLY   {migration.filename}")
                    execution_ms = _apply_sql(cur, migration.sql)
                    _record_migration(cur, migration, execution_ms)
                    conn.commit()
                    print(f"APPLIED {migration.filename} in {execution_ms} ms")
                    applied_count += 1

                print(f"Migration complete: applied={applied_count}, skipped={skipped_count}")
                return 0
        finally:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
            conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Безопасно применить SQL-миграции проекта к PostgreSQL из .env.")
    parser.add_argument(
        "--init-schema",
        action="store_true",
        help="Если core-таблиц еще нет, сначала применить sql/schema.sql, затем миграции.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Показать план без изменений в БД.")
    parser.add_argument("--list", action="store_true", help="Показать статус миграций и выйти.")
    parser.add_argument("--target", help="Применить миграции только до указанного имени файла включительно.")
    parser.add_argument(
        "--allow-changed-checksum",
        action="store_true",
        help="Не останавливать запуск при измененной уже примененной миграции. Использовать только для аварийного ремонта.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return apply_migrations(
        init_schema=args.init_schema,
        dry_run=args.dry_run,
        list_only=args.list,
        target=args.target,
        allow_changed_checksum=args.allow_changed_checksum,
    )


if __name__ == "__main__":
    raise SystemExit(main())
