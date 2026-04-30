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
