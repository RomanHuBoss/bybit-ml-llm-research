from __future__ import annotations


def test_connect_raw_wraps_unicode_decode_error_without_leaking_password(monkeypatch):
    from app import db

    class FakePsycopg2:
        @staticmethod
        def connect(**_kwargs):
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(db, "psycopg2", FakePsycopg2)
    monkeypatch.setattr(db, "_tcp_preflight", lambda: None)

    try:
        db.connect_raw()
    except db.DatabaseConnectionError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("DatabaseConnectionError was not raised")

    assert "password=<hidden>" in message
    assert db.settings.postgres_password not in message
    assert "psql -h" in message
