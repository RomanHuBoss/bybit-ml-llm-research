from __future__ import annotations

from pathlib import Path

from app.db_migrations import discover_migrations, sha256_text


def test_migration_runner_discovers_sql_files_in_deterministic_order(tmp_path: Path) -> None:
    (tmp_path / "20260504_v43_recent_loss_quarantine.sql").write_text("select 43;\n", encoding="utf-8")
    (tmp_path / "20260502_v28_recommendation_contract.sql").write_text("select 28;\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore", encoding="utf-8")

    migrations = discover_migrations(tmp_path)

    assert [m.filename for m in migrations] == [
        "20260502_v28_recommendation_contract.sql",
        "20260504_v43_recent_loss_quarantine.sql",
    ]
    assert migrations[0].checksum_sha256 == sha256_text("select 28;\n")


def test_migration_runner_target_stops_at_requested_file(tmp_path: Path) -> None:
    for version in ("20260502_v28_a.sql", "20260503_v30_b.sql", "20260504_v43_c.sql"):
        (tmp_path / version).write_text(f"-- {version}\n", encoding="utf-8")

    migrations = discover_migrations(tmp_path, target="20260503_v30_b.sql")

    assert [m.filename for m in migrations] == ["20260502_v28_a.sql", "20260503_v30_b.sql"]


def test_project_contains_direct_and_launcher_migration_entrypoints() -> None:
    assert Path("app/db_migrations.py").exists()
    assert Path("scripts/apply_migrations.py").exists()
    assert Path("scripts/apply_migrations.sh").exists()
    assert Path("scripts/apply_migrations.ps1").exists()

    run_py = Path("run.py").read_text(encoding="utf-8")
    assert 'subparsers.add_parser("migrate"' in run_py
    assert '"-m", "app.db_migrations"' in run_py
