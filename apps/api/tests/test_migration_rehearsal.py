from __future__ import annotations

from pathlib import Path

import pytest

from cloud_study_api.backups import BackupError, generate_backup_key_pair
from cloud_study_api.database import upgrade_database
from cloud_study_api.migration_rehearsal import run_migration_rehearsal

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_migration_rehearsal_uses_encrypted_copy_and_proves_rollback(tmp_path: Path) -> None:
    database = tmp_path / "real.sqlite3"
    upgrade_database(database, REPOSITORY_ROOT)
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    generate_backup_key_pair(private_key, public_key)
    encrypted_backup = tmp_path / "migration.csbak"

    report = run_migration_rehearsal(
        database,
        encrypted_backup,
        public_key,
        private_key,
        REPOSITORY_ROOT,
        operator="project-owner",
        writes_stopped=True,
    )

    assert encrypted_backup.read_bytes().startswith(b"CSBKP01\n")
    assert report["status"] == "passed"
    assert report["checks"]["formal_alembic_upgrade"] == "passed"
    assert report["checks"]["rollback_restore"] == "passed"
    assert report["checks"]["plaintext_copies_retained"] is False
    assert report["source"]["alembic_revision"] == "0010"
    assert "app_settings" in report["source"]["row_counts"]


def test_migration_rehearsal_requires_explicit_write_stop(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="writes must be stopped"):
        run_migration_rehearsal(
            tmp_path / "missing.sqlite3",
            tmp_path / "backup.csbak",
            tmp_path / "public.pem",
            tmp_path / "private.pem",
            REPOSITORY_ROOT,
            operator="project-owner",
            writes_stopped=False,
        )
