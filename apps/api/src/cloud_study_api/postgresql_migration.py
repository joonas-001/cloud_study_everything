from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from sqlalchemy import Engine, make_url, select, text

from cloud_study_api.database import create_database_engine, create_postgresql_engine
from cloud_study_api.models import Base

SYNTHETIC_DATABASE_NAME = "cloud_study_synthetic_9b"
CURRENT_SCHEMA_REVISION = "0015"


class PostgreSqlMigrationError(RuntimeError):
    """Raised when the isolated 9B migration boundary or verification fails."""


def _validate_candidate_url(database_url: str) -> None:
    parsed = make_url(database_url)
    if parsed.drivername != "postgresql+psycopg":
        raise PostgreSqlMigrationError("the candidate must use postgresql+psycopg")
    if parsed.database != SYNTHETIC_DATABASE_NAME:
        raise PostgreSqlMigrationError("destructive migration is restricted to the 9B database")
    if parsed.host not in {"127.0.0.1", "localhost", "::1"}:
        raise PostgreSqlMigrationError("the 9B PostgreSQL candidate must be loopback-only")


def _schema_revision(engine: Engine) -> str:
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    return str(revision)


def _normalized(value: Any) -> Any:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _table_summary(engine: Engine, table_name: str) -> dict[str, object]:
    table = Base.metadata.tables[table_name]
    primary_key = list(table.primary_key.columns)
    statement = select(table)
    if primary_key:
        statement = statement.order_by(*primary_key)
    digest = sha256()
    count = 0
    with engine.connect() as connection:
        for row in connection.execute(statement).mappings():
            payload = {column.name: _normalized(row[column.name]) for column in table.columns}
            encoded = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def database_summary(engine: Engine) -> dict[str, dict[str, object]]:
    return {table.name: _table_summary(engine, table.name) for table in Base.metadata.sorted_tables}


def migrate_sqlite_to_postgresql(
    *,
    source_database: Path,
    target_database_url: str,
) -> dict[str, object]:
    """Copy the current SQLite candidate into an exact loopback-only PostgreSQL target.

    The source is never written. The target reset and copy are one PostgreSQL
    transaction, so any copy or digest mismatch rolls back atomically.
    """

    _validate_candidate_url(target_database_url)
    source_engine = create_database_engine(source_database)
    target_engine = create_postgresql_engine(target_database_url)
    try:
        if _schema_revision(source_engine) != CURRENT_SCHEMA_REVISION:
            raise PostgreSqlMigrationError(
                f"source database must be at revision {CURRENT_SCHEMA_REVISION}"
            )
        if _schema_revision(target_engine) != CURRENT_SCHEMA_REVISION:
            raise PostgreSqlMigrationError(
                f"target database must be at revision {CURRENT_SCHEMA_REVISION}"
            )
        source_before = database_summary(source_engine)
        tables = list(Base.metadata.sorted_tables)
        quoted_tables = ", ".join(f'"{table.name}"' for table in tables)
        with source_engine.connect() as source, target_engine.begin() as target:
            target.execute(text(f"TRUNCATE TABLE {quoted_tables} RESTART IDENTITY CASCADE"))
            for table in tables:
                rows = [dict(row) for row in source.execute(select(table)).mappings()]
                if rows:
                    target.execute(table.insert(), rows)
            for table_name in (
                "app_settings",
                "user_settings",
                "notification_preferences",
            ):
                target.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                        f'COALESCE((SELECT MAX(id) FROM "{table_name}"), 0) + 1, false)'
                    )
                )
        target_summary = database_summary(target_engine)
        source_after = database_summary(source_engine)
        if source_before != source_after:
            raise PostgreSqlMigrationError("source SQLite database changed during migration")
        if source_before != target_summary:
            mismatches = sorted(
                name for name in source_before if source_before[name] != target_summary.get(name)
            )
            raise PostgreSqlMigrationError(
                f"PostgreSQL verification mismatch: {', '.join(mismatches)}"
            )
        return {
            "source_revision": CURRENT_SCHEMA_REVISION,
            "target_revision": CURRENT_SCHEMA_REVISION,
            "table_count": len(tables),
            "row_count": sum(cast(int, item["rows"]) for item in source_before.values()),
            "tables": source_before,
            "source_unchanged": True,
            "target_verified": True,
        }
    finally:
        source_engine.dispose()
        target_engine.dispose()
