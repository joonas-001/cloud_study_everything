from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def create_database_url(database_path: Path) -> str:
    """Create a SQLAlchemy URL for a local SQLite database."""
    return f"sqlite+pysqlite:///{database_path.as_posix()}"


def create_database_engine(database_path: Path) -> Engine:
    """Create the SQLAlchemy engine used by application database boundaries."""
    return create_engine(
        create_database_url(database_path),
        connect_args={"check_same_thread": False},
    )


def create_session_factory(database_path: Path) -> sessionmaker[Session]:
    """Create the SQLAlchemy session factory for application requests."""
    return sessionmaker(
        bind=create_database_engine(database_path),
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
