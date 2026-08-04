from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from cloud_study_api.backups import (
    BackupError,
    apply_backup_retention,
    create_encrypted_backup,
    generate_backup_key_pair,
    inspect_encrypted_backup,
    restore_encrypted_backup,
)
from cloud_study_api.database import create_database_engine, read_schema_version, upgrade_database

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_encrypted_backup_round_trip_preserves_migrated_database(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    private_key = tmp_path / "offline" / "private.pem"
    public_key = tmp_path / "runtime" / "public.pem"
    backup_path = tmp_path / "backups" / "daily.csbak"
    restored_path = tmp_path / "restore" / "restored.sqlite3"
    upgrade_database(database_path, REPOSITORY_ROOT)
    engine = create_database_engine(database_path)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE app_settings SET inactivity_timeout_minutes = 90, "
                    "updated_at = '2026-08-02T00:00:00+00:00' WHERE id = 1"
                )
            )
    finally:
        engine.dispose()

    generate_backup_key_pair(private_key, public_key)
    manifest = create_encrypted_backup(
        database_path,
        backup_path,
        public_key,
        policy_id="single-user-singapore",
        policy_version="1.0.0",
    )

    assert backup_path.is_file()
    assert manifest["database"]["alembic_revision"] == "0010"
    assert inspect_encrypted_backup(backup_path)["policy_id"] == "single-user-singapore"
    restored_manifest = restore_encrypted_backup(backup_path, restored_path, private_key)
    assert restored_manifest == manifest
    assert read_schema_version(restored_path) == "0010"
    restored_engine = create_database_engine(restored_path)
    try:
        with restored_engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT inactivity_timeout_minutes FROM app_settings WHERE id = 1")
                ).scalar_one()
                == 90
            )
    finally:
        restored_engine.dispose()


def test_restore_rejects_tampering_without_creating_target(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    backup_path = tmp_path / "daily.csbak"
    target_path = tmp_path / "restored.sqlite3"
    upgrade_database(database_path, REPOSITORY_ROOT)
    generate_backup_key_pair(private_key, public_key)
    create_encrypted_backup(
        database_path,
        backup_path,
        public_key,
        policy_id="single-user-singapore",
        policy_version="1.0.0",
    )
    value = bytearray(backup_path.read_bytes())
    value[-8] ^= 0x01
    backup_path.write_bytes(value)

    with pytest.raises(BackupError, match=r"authentication|decryption|trailing"):
        restore_encrypted_backup(backup_path, target_path, private_key)
    assert not target_path.exists()


def test_backup_and_key_generation_refuse_overwrite(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    backup_path = tmp_path / "daily.csbak"
    upgrade_database(database_path, REPOSITORY_ROOT)
    generate_backup_key_pair(private_key, public_key)
    with pytest.raises(BackupError, match="already exists"):
        generate_backup_key_pair(private_key, public_key)
    backup_path.write_bytes(b"existing")
    with pytest.raises(BackupError, match="already exists"):
        create_encrypted_backup(
            database_path,
            backup_path,
            public_key,
            policy_id="single-user-singapore",
            policy_version="1.0.0",
        )


def test_retention_keeps_recent_daily_and_weekly_artifacts_only(tmp_path: Path) -> None:
    for day in range(1, 16):
        (tmp_path / f"cloud-study-202607{day:02d}T010000Z.csbak").write_bytes(b"backup")
    unrelated = tmp_path / "notes.txt"
    unrelated.write_text("preserve", encoding="utf-8")

    planned = apply_backup_retention(tmp_path.resolve())
    assert planned
    assert all(path.exists() for path in planned)
    removed = apply_backup_retention(tmp_path.resolve(), apply=True)
    assert removed == planned
    assert all(not path.exists() for path in removed)
    assert unrelated.read_text(encoding="utf-8") == "preserve"
    assert len(list(tmp_path.glob("*.csbak"))) >= 7
