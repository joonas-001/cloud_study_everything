from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cloud_study_api.backups import (
    BackupError,
    create_encrypted_backup,
    restore_encrypted_backup,
)
from cloud_study_api.database import upgrade_database

EVENT_SCOPES = {
    "diagnostic_events": "session_id",
    "planning_change_events": "proposal_id",
    "learning_events": "run_id",
    "market_research_events": "run_id",
    "experiment_events": "experiment_id",
}


def _canonical_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return {"float": value.hex()}
    if isinstance(value, bytes):
        return {"bytes_base64": base64.b64encode(value).decode("ascii")}
    raise BackupError(f"unsupported SQLite value type: {type(value).__name__}")


def _table_digest(database: sqlite3.Connection, table_name: str) -> tuple[int, str]:
    escaped = table_name.replace('"', '""')
    columns = [
        str(row[1]) for row in database.execute(f'PRAGMA table_info("{escaped}")').fetchall()
    ]
    if not columns:
        raise BackupError(f"SQLite table has no columns: {table_name}")
    order = ", ".join(f'"{column.replace(chr(34), chr(34) * 2)}"' for column in columns)
    digest = hashlib.sha256()
    count = 0
    for row in database.execute(f'SELECT * FROM "{escaped}" ORDER BY {order}'):
        encoded = json.dumps(
            [_canonical_value(value) for value in row],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return count, digest.hexdigest()


def _verify_event_order(database: sqlite3.Connection, table_name: str, scope: str) -> int:
    escaped_table = table_name.replace('"', '""')
    escaped_scope = scope.replace('"', '""')
    previous: dict[object, str] = {}
    checked = 0
    rows = database.execute(
        f'SELECT "{escaped_scope}", occurred_at FROM "{escaped_table}" ORDER BY id'
    )
    for scope_value, occurred_at in rows:
        if not isinstance(occurred_at, str):
            raise BackupError(f"{table_name}.occurred_at is not text")
        prior = previous.get(scope_value)
        if prior is not None and occurred_at < prior:
            raise BackupError(f"{table_name} event order is not monotonic")
        previous[scope_value] = occurred_at
        checked += 1
    return checked


def database_semantic_snapshot(database_path: Path) -> dict[str, Any]:
    if not database_path.is_file() or database_path.is_symlink():
        raise BackupError("migration source must be a regular SQLite database")
    uri = f"file:{database_path.as_posix()}?mode=ro"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as database:
            integrity = database.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise BackupError("SQLite integrity_check failed")
            foreign_keys = database.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise BackupError("SQLite foreign_key_check found violations")
            revision = database.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision is None:
                raise BackupError("SQLite database has no Alembic revision")
            tables = [
                str(row[0])
                for row in database.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            table_snapshots = {}
            for table_name in tables:
                rows, digest = _table_digest(database, table_name)
                table_snapshots[table_name] = {"rows": rows, "sha256": digest}
            event_order = {
                table_name: _verify_event_order(database, table_name, scope)
                for table_name, scope in EVENT_SCOPES.items()
                if table_name in table_snapshots
            }
    except sqlite3.Error as error:
        raise BackupError("SQLite semantic verification failed") from error
    return {
        "alembic_revision": str(revision[0]),
        "tables": table_snapshots,
        "event_order_rows_checked": event_order,
        "foreign_key_violations": 0,
        "integrity_check": "ok",
    }


def run_migration_rehearsal(
    source_database: Path,
    encrypted_backup: Path,
    public_key: Path,
    private_key: Path,
    repository_root: Path,
    *,
    operator: str,
    writes_stopped: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not writes_stopped:
        raise BackupError("writes must be stopped and explicitly confirmed")
    if not operator.strip() or len(operator.strip()) > 100:
        raise BackupError("migration rehearsal operator must be identified")
    started = now or datetime.now(UTC)
    source_snapshot = database_semantic_snapshot(source_database)
    backup_manifest = create_encrypted_backup(
        source_database,
        encrypted_backup,
        public_key,
        policy_id="single-user-singapore",
        policy_version="1.0.0",
        now=started,
    )
    with tempfile.TemporaryDirectory(prefix="cloud-study-migration-") as temporary:
        temporary_root = Path(temporary)
        migrated_database = temporary_root / "migrated.sqlite3"
        rollback_database = temporary_root / "rollback.sqlite3"
        restore_encrypted_backup(encrypted_backup, migrated_database, private_key)
        upgrade_database(migrated_database, repository_root)
        migrated_snapshot = database_semantic_snapshot(migrated_database)
        restore_encrypted_backup(encrypted_backup, rollback_database, private_key)
        rollback_snapshot = database_semantic_snapshot(rollback_database)
    if migrated_snapshot != source_snapshot:
        raise BackupError("migration rehearsal produced an unexplained semantic difference")
    if rollback_snapshot != source_snapshot:
        raise BackupError("rollback rehearsal did not reproduce the source snapshot")
    finished = datetime.now(UTC)
    database_manifest = backup_manifest.get("database")
    if not isinstance(database_manifest, dict):
        raise BackupError("backup manifest has no database metadata")
    return {
        "status": "passed",
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "operator": operator.strip(),
        "writes_stopped_confirmed": True,
        "source": {
            "alembic_revision": source_snapshot["alembic_revision"],
            "snapshot_sha256": database_manifest.get("sha256"),
            "table_count": len(source_snapshot["tables"]),
            "row_counts": {
                name: value["rows"] for name, value in source_snapshot["tables"].items()
            },
        },
        "checks": {
            "formal_alembic_upgrade": "passed",
            "semantic_table_digests": "passed",
            "foreign_keys": "passed",
            "event_order": "passed",
            "immutable_content_locks": "covered_by_table_digest",
            "rollback_restore": "passed",
            "plaintext_copies_retained": False,
        },
        "encrypted_backup": {
            "format_version": backup_manifest.get("format_version"),
            "created_at": backup_manifest.get("created_at"),
            "policy_id": backup_manifest.get("policy_id"),
            "policy_version": backup_manifest.get("policy_version"),
        },
    }
