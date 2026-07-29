from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from packaging.specifiers import SpecifierSet
from packaging.version import Version
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.governance import RepositoryValidationError, SkillPackage
from cloud_study_api.models import (
    DiagnosticSession,
    PlanningProposal,
    SkillVersionContentLock,
    utc_now,
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def package_content_payload(package: SkillPackage) -> dict[str, Any]:
    return {
        "skill_id": package.package_id,
        "skill_version": package.version,
        "manifest_sha256": package.manifest_sha256,
        "manifest": package.manifest,
        "content_files": sorted(
            package.manifest["content_files"],
            key=lambda item: (item["kind"], item["path"]),
        ),
    }


def ensure_package_content_lock(
    database: Session,
    package: SkillPackage,
    now: datetime,
) -> SkillVersionContentLock:
    payload = package_content_payload(package)
    digest = sha256_json(payload)
    existing = database.scalar(
        select(SkillVersionContentLock).where(
            SkillVersionContentLock.skill_id == package.package_id,
            SkillVersionContentLock.skill_version == package.version,
        )
    )
    if existing is not None:
        if (
            existing.manifest_sha256 != package.manifest_sha256
            or existing.content_lock_sha256 != digest
            or existing.content_lock_json != canonical_json(payload)
        ):
            raise RepositoryValidationError(
                f"{package.package_id}@{package.version}: managed content changed after first "
                "persistent reference; publish a new package version"
            )
        return existing
    content_lock = SkillVersionContentLock(
        id=str(uuid4()),
        skill_id=package.package_id,
        skill_version=package.version,
        manifest_sha256=package.manifest_sha256,
        content_lock_sha256=digest,
        content_lock_json=canonical_json(payload),
        created_at=now,
    )
    database.add(content_lock)
    database.flush()
    return content_lock


def resolve_dependency_packages(
    root: SkillPackage,
    packages: list[SkillPackage],
) -> list[SkillPackage]:
    by_id: dict[str, list[SkillPackage]] = {}
    for package in packages:
        by_id.setdefault(package.package_id, []).append(package)
    resolved: list[SkillPackage] = []
    seen: set[tuple[str, str]] = set()

    def visit(package: SkillPackage) -> None:
        for requirement in package.manifest["skill_dependencies"]:
            specifier = SpecifierSet(requirement["version"])
            candidates = [
                candidate
                for candidate in by_id.get(requirement["id"], [])
                if Version(candidate.version) in specifier
            ]
            selected = max(candidates, key=lambda item: Version(item.version))
            identity = (selected.package_id, selected.version)
            if identity in seen:
                continue
            visit(selected)
            seen.add(identity)
            resolved.append(selected)

    visit(root)
    return resolved


def execution_package_lock(
    database: Session,
    root: SkillPackage,
    packages: list[SkillPackage],
    now: datetime,
) -> dict[str, Any]:
    dependency_packages = resolve_dependency_packages(root, packages)
    all_packages = [root, *dependency_packages]
    locks = [ensure_package_content_lock(database, package, now) for package in all_packages]
    return {
        "root": json.loads(locks[0].content_lock_json),
        "dependencies": [json.loads(content_lock.content_lock_json) for content_lock in locks[1:]],
    }


def validate_or_backfill_persisted_content_locks(
    session_factory: sessionmaker[Session],
    packages: list[SkillPackage],
) -> None:
    by_identity = {(package.package_id, package.version): package for package in packages}
    with session_factory() as database:
        referenced = {
            (row.skill_id, row.skill_version)
            for row in database.execute(
                select(DiagnosticSession.skill_id, DiagnosticSession.skill_version).distinct()
            ).all()
        }
        referenced.update(
            (row.skill_id, row.skill_version)
            for row in database.execute(
                select(PlanningProposal.skill_id, PlanningProposal.skill_version).distinct()
            ).all()
        )
        for identity in sorted(referenced):
            package = by_identity.get(identity)
            if package is None:
                raise RepositoryValidationError(
                    f"persisted records reference an unregistered package: {identity}"
                )
            ensure_package_content_lock(database, package, utc_now())

        for content_lock in database.scalars(select(SkillVersionContentLock)).all():
            package = by_identity.get((content_lock.skill_id, content_lock.skill_version))
            if package is None:
                raise RepositoryValidationError(
                    "persisted content lock references an unregistered package: "
                    f"{content_lock.skill_id}@{content_lock.skill_version}"
                )
            ensure_package_content_lock(database, package, content_lock.created_at)
        database.commit()
