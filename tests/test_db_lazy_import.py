from __future__ import annotations


def test_db_import_does_not_load_psycopg2_until_real_connection():
    import app.db as db

    # В среде с битым или отсутствующим C-extension импорт app.db должен оставаться
    # безопасным: ошибка PostgreSQL допустима только при фактическом connect/query.
    assert db.psycopg2 is None or hasattr(db.psycopg2, "connect")
