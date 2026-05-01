from __future__ import annotations

import app.strategy_quality as sq


def test_strategy_quality_runtime_schema_has_single_diagnostics_column(monkeypatch):
    executed = []

    def fake_execute(sql, params=None):
        executed.append(str(sql))
        return None

    monkeypatch.setattr(sq, "execute", fake_execute)
    sq.ensure_strategy_quality_storage()

    create_sql = next(sql for sql in executed if "CREATE TABLE IF NOT EXISTS strategy_quality" in sql)
    assert create_sql.count("diagnostics JSONB") == 1


def test_strategy_quality_runtime_schema_recreates_unique_key_for_existing_tables(monkeypatch):
    executed = []

    def fake_execute(sql, params=None):
        executed.append(str(sql))
        return None

    monkeypatch.setattr(sq, "execute", fake_execute)
    sq.ensure_strategy_quality_storage()

    joined = "\n".join(executed)
    assert "ALTER TABLE strategy_quality ADD COLUMN IF NOT EXISTS diagnostics JSONB" in joined
    assert "DELETE FROM strategy_quality a" in joined
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ux_strategy_quality_key" in joined
    assert "ON strategy_quality(category, symbol, interval, strategy)" in joined
