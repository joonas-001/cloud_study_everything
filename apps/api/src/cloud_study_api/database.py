from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, inspect, make_url, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import (
    ORMExecuteState,
    Session,
    SessionTransaction,
    sessionmaker,
    with_loader_criteria,
)

from cloud_study_api.models import UserOwnedMixin
from cloud_study_api.principals import require_data_principal


class DataOwnershipError(RuntimeError):
    """Raised when a write attempts to cross the current principal boundary."""


def _validated_postgresql_url(database_url: str) -> str:
    parsed = make_url(database_url)
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("PostgreSQL candidates must use the postgresql+psycopg driver")
    if not parsed.database:
        raise ValueError("PostgreSQL database name is required")
    return database_url


@event.listens_for(Session, "do_orm_execute")
def _scope_user_owned_statements(execute_state: ORMExecuteState) -> None:
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    principal = require_data_principal()
    user_id = principal.user_id
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            UserOwnedMixin,
            lambda model: model.user_id == user_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _enforce_user_owned_writes(
    session: Session,
    _flush_context: object,
    _instances: object,
) -> None:
    principal = require_data_principal()
    for record in session.new:
        if not isinstance(record, UserOwnedMixin):
            continue
        owner = getattr(record, "user_id", None)
        if owner is None:
            record.user_id = principal.user_id
        elif owner != principal.user_id:
            raise DataOwnershipError("new object owner does not match the current principal")
    for record in session.dirty | session.deleted:
        if isinstance(record, UserOwnedMixin) and record.user_id != principal.user_id:
            raise DataOwnershipError("object owner does not match the current principal")
    for record in session.new | session.dirty:
        if not isinstance(record, UserOwnedMixin):
            continue
        state = inspect(record)
        assert state is not None
        for column in state.mapper.columns:
            value = getattr(record, column.key)
            if value is None:
                continue
            for foreign_key in column.foreign_keys:
                target_table = foreign_key.column.table
                if "user_id" not in target_table.c or target_table.name == "users":
                    continue
                related_owner = _pending_related_owner(
                    session,
                    target_table.name,
                    foreign_key.column.key,
                    value,
                )
                if related_owner is None:
                    related_owner = (
                        session.connection()
                        .execute(select(target_table.c.user_id).where(foreign_key.column == value))
                        .scalar_one_or_none()
                    )
                if related_owner is not None and related_owner != principal.user_id:
                    raise DataOwnershipError(
                        "related object owner does not match the current principal"
                    )


def _pending_related_owner(
    session: Session,
    table_name: str,
    key: str,
    value: object,
) -> str | None:
    for candidate in session.new:
        state = inspect(candidate)
        if (
            isinstance(candidate, UserOwnedMixin)
            and state is not None
            and state.mapper.local_table.name == table_name
            and getattr(candidate, key) == value
        ):
            return candidate.user_id
    return None


@event.listens_for(Session, "after_begin")
def _set_postgresql_principal(
    _session: Session,
    _transaction: SessionTransaction,
    connection: Connection,
) -> None:
    if connection.dialect.name != "postgresql":
        return
    principal = require_data_principal()
    connection.execute(
        text("SELECT set_config('cloud_study.user_id', :user_id, true)"),
        {"user_id": principal.user_id},
    )


def create_database_url(database_path: Path) -> str:
    """Create a SQLAlchemy URL for a local SQLite database."""
    return f"sqlite+pysqlite:///{database_path.as_posix()}"


def create_database_engine(database_path: Path) -> Engine:
    """Create the SQLAlchemy engine used by application database boundaries."""
    return create_engine(
        create_database_url(database_path),
        connect_args={"check_same_thread": False},
    )


def create_postgresql_engine(database_url: str) -> Engine:
    """Create an engine for an explicitly supplied 9B PostgreSQL candidate URL."""
    return create_engine(_validated_postgresql_url(database_url), pool_pre_ping=True)


def create_session_factory(database_path: Path) -> sessionmaker[Session]:
    """Create the SQLAlchemy session factory for application requests."""
    return sessionmaker(
        bind=create_database_engine(database_path),
        class_=Session,
        expire_on_commit=False,
    )


def create_postgresql_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=create_postgresql_engine(database_url),
        class_=Session,
        expire_on_commit=False,
    )


def upgrade_database(database_path: Path, repository_root: Path) -> None:
    """Upgrade the local database to the latest versioned Alembic revision."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(repository_root / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(repository_root / "apps" / "api" / "migrations"),
    )
    config.set_main_option("sqlalchemy.url", create_database_url(database_path).replace("%", "%%"))
    command.upgrade(config, "head")


def upgrade_postgresql_database(database_url: str, repository_root: Path) -> None:
    """Upgrade an isolated PostgreSQL candidate; callers own target authorization."""
    config = Config(str(repository_root / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(repository_root / "apps" / "api" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url", _validated_postgresql_url(database_url).replace("%", "%%")
    )
    command.upgrade(config, "head")


def read_schema_version(database_path: Path) -> str:
    """Read the current Alembic revision from SQLite."""
    engine = create_database_engine(database_path)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()
    return str(revision)
