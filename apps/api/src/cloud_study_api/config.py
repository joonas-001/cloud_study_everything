from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cloud_study_api.deployment import DeploymentSettings


def find_repository_root() -> Path:
    """Return the repository root from this source checkout."""
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True, slots=True)
class Settings:
    repository_root: Path
    database_path: Path
    deployment: DeploymentSettings

    @classmethod
    def from_environment(cls) -> Settings:
        repository_root = find_repository_root()
        configured_database = os.getenv("CLOUD_STUDY_DATABASE_PATH")
        database_path = (
            Path(configured_database).expanduser().resolve()
            if configured_database
            else repository_root / "apps" / "api" / "data" / "cloud-study.db"
        )
        return cls(
            repository_root=repository_root,
            database_path=database_path,
            deployment=DeploymentSettings.from_environment(repository_root),
        )
