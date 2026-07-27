from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


class RepositoryValidationError(RuntimeError):
    """Raised when repository-governed content is inconsistent."""


@dataclass(frozen=True, slots=True)
class SkillPackage:
    package_id: str
    version: str
    path: Path
    state: str
    availability: str
    manifest_sha256: str
    manifest: dict[str, Any]


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepositoryValidationError(f"{path}: expected a YAML object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RepositoryValidationError(f"{path}: expected a JSON object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_with_schema(instance: dict[str, Any], schema_path: Path, label: str) -> None:
    schema = _load_json(schema_path)
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = "; ".join(error.message for error in errors)
        raise RepositoryValidationError(f"{label}: {details}")


def _validate_diagnostic_definition(
    definition: dict[str, Any],
    schema_path: Path,
    label: str,
    package_id: str,
    package_version: str,
) -> None:
    _validate_with_schema(definition, schema_path, label)
    if definition["skill_id"] != package_id or definition["skill_version"] != package_version:
        raise RepositoryValidationError(
            f"{label}: skill_id and skill_version must match the package manifest"
        )
    questions = definition["questions"]
    question_ids = [question["id"] for question in questions]
    if len(question_ids) != len(set(question_ids)):
        raise RepositoryValidationError(f"{label}: duplicate diagnostic question id")
    known_ids = set(question_ids)
    if definition["start_question_id"] not in known_ids:
        raise RepositoryValidationError(f"{label}: start_question_id does not exist")
    for question in questions:
        for next_question_id in question["transitions"].values():
            if next_question_id is not None and next_question_id not in known_ids:
                raise RepositoryValidationError(
                    f"{label}: transition points to unknown question {next_question_id}"
                )


def load_skill_packages(repository_root: Path) -> list[SkillPackage]:
    """Load and validate the built-in registry and every registered manifest."""
    skill_root = (repository_root / "skill-packs").resolve()
    registry_path = skill_root / "registry.yaml"
    registry = _load_yaml(registry_path)
    _validate_with_schema(
        registry,
        repository_root / "contracts" / "skill-pack" / "registry.schema.json",
        "skill-packs/registry.yaml",
    )

    entries = registry["packages"]
    packages: list[SkillPackage] = []
    identities: set[tuple[str, str]] = set()
    registered_manifests: set[Path] = set()

    for entry in entries:
        identity = (entry["id"], entry["version"])
        if identity in identities:
            raise RepositoryValidationError(f"duplicate registry entry: {identity}")
        identities.add(identity)

        package_path = (repository_root / entry["path"]).resolve()
        if not package_path.is_relative_to(skill_root):
            raise RepositoryValidationError(f"registry path escapes skill-packs: {entry['path']}")
        manifest_path = package_path / "manifest.yaml"
        if not manifest_path.is_file():
            raise RepositoryValidationError(f"missing manifest: {manifest_path}")
        registered_manifests.add(manifest_path)

        actual_manifest_hash = _sha256(manifest_path)
        if actual_manifest_hash != entry["manifest_sha256"]:
            raise RepositoryValidationError(
                f"{manifest_path}: sha256 mismatch; expected {entry['manifest_sha256']}, "
                f"got {actual_manifest_hash}"
            )

        manifest = _load_yaml(manifest_path)
        _validate_with_schema(
            manifest,
            repository_root / "contracts" / "skill-pack" / "manifest.schema.json",
            str(manifest_path),
        )
        expected_path = skill_root / entry["id"] / "versions" / entry["version"]
        if package_path != expected_path.resolve():
            raise RepositoryValidationError(
                f"{entry['path']}: path must match id/version directory convention"
            )
        for field in ("id", "version", "state", "availability"):
            if manifest[field] != entry[field]:
                raise RepositoryValidationError(
                    f"{manifest_path}: {field} differs from registry entry"
                )

        for content in manifest["content_files"]:
            content_path = (package_path / content["path"]).resolve()
            if not content_path.is_relative_to(package_path) or not content_path.is_file():
                raise RepositoryValidationError(
                    f"{manifest_path}: invalid content path {content['path']}"
                )
            actual_content_hash = _sha256(content_path)
            if actual_content_hash != content["sha256"]:
                raise RepositoryValidationError(
                    f"{content_path}: sha256 mismatch; expected {content['sha256']}, "
                    f"got {actual_content_hash}"
                )
            if content["kind"] == "diagnostic_definition":
                definition = _load_yaml(content_path)
                _validate_diagnostic_definition(
                    definition,
                    repository_root
                    / "contracts"
                    / "skill-pack"
                    / "diagnostic-definition.schema.json",
                    str(content_path),
                    entry["id"],
                    entry["version"],
                )

        packages.append(
            SkillPackage(
                package_id=entry["id"],
                version=entry["version"],
                path=package_path,
                state=entry["state"],
                availability=entry["availability"],
                manifest_sha256=entry["manifest_sha256"],
                manifest=manifest,
            )
        )

    discovered_manifests = {
        path.resolve() for path in skill_root.glob("*/versions/*/manifest.yaml")
    }
    if registered_manifests != discovered_manifests:
        missing = discovered_manifests - registered_manifests
        stale = registered_manifests - discovered_manifests
        raise RepositoryValidationError(
            f"registry/filesystem mismatch; unregistered={sorted(map(str, missing))}, "
            f"missing={sorted(map(str, stale))}"
        )
    return packages


def validate_dependency_graph(packages: list[SkillPackage]) -> None:
    """Reject missing, incompatible, or cyclic skill-package dependencies."""
    by_id: dict[str, list[SkillPackage]] = {}
    for package in packages:
        by_id.setdefault(package.package_id, []).append(package)

    graph: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for package in packages:
        identity = (package.package_id, package.version)
        graph[identity] = []
        for dependency in package.manifest["skill_dependencies"]:
            try:
                version_range = SpecifierSet(dependency["version"])
            except InvalidSpecifier as error:
                raise RepositoryValidationError(
                    f"{identity}: invalid dependency range {dependency['version']}"
                ) from error
            candidates: list[SkillPackage] = []
            for candidate in by_id.get(dependency["id"], []):
                try:
                    if Version(candidate.version) in version_range:
                        candidates.append(candidate)
                except InvalidVersion as error:
                    raise RepositoryValidationError(
                        f"{candidate.package_id}: invalid version {candidate.version}"
                    ) from error
            if not candidates:
                raise RepositoryValidationError(
                    f"{identity}: unresolved dependency {dependency['id']} {dependency['version']}"
                )
            selected = max(candidates, key=lambda item: Version(item.version))
            graph[identity].append((selected.package_id, selected.version))

    visiting: set[tuple[str, str]] = set()
    visited: set[tuple[str, str]] = set()

    def visit(node: tuple[str, str]) -> None:
        if node in visiting:
            raise RepositoryValidationError(f"cyclic dependency detected at {node}")
        if node in visited:
            return
        visiting.add(node)
        for neighbor in graph[node]:
            visit(neighbor)
        visiting.remove(node)
        visited.add(node)

    for identity in graph:
        visit(identity)


def validate_repository(repository_root: Path) -> list[SkillPackage]:
    """Validate all repository-owned skill package invariants."""
    packages = load_skill_packages(repository_root)
    validate_dependency_graph(packages)
    return packages
