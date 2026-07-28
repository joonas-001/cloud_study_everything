from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from itertools import pairwise
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
    intake: str
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
        option_values = [option["value"] for option in question.get("options", [])]
        if len(option_values) != len(set(option_values)):
            raise RepositoryValidationError(
                f"{label}: question {question['id']} has duplicate option values"
            )
        for next_question_id in question["transitions"].values():
            if next_question_id is not None and next_question_id not in known_ids:
                raise RepositoryValidationError(
                    f"{label}: transition points to unknown question {next_question_id}"
                )


def _validate_source_catalog(
    catalog: dict[str, Any],
    schema_path: Path,
    label: str,
    package_id: str,
    package_version: str,
) -> None:
    _validate_with_schema(catalog, schema_path, label)
    if catalog["skill_id"] != package_id or catalog["skill_version"] != package_version:
        raise RepositoryValidationError(
            f"{label}: skill_id and skill_version must match the package manifest"
        )
    source_ids = [source["id"] for source in catalog["sources"]]
    if len(source_ids) != len(set(source_ids)):
        raise RepositoryValidationError(f"{label}: duplicate source id")
    known_source_ids = set(source_ids)
    expert_ids = [expert["id"] for expert in catalog["experts"]]
    if len(expert_ids) != len(set(expert_ids)):
        raise RepositoryValidationError(f"{label}: duplicate expert id")
    for expert in catalog["experts"]:
        unknown = set(expert["source_ids"]) - known_source_ids
        if unknown:
            raise RepositoryValidationError(
                f"{label}: expert {expert['id']} references unknown sources {sorted(unknown)}"
            )


def _validate_planning_template(
    template: dict[str, Any],
    schema_path: Path,
    label: str,
    package_id: str,
    package_version: str,
    known_source_ids: set[str],
) -> None:
    _validate_with_schema(template, schema_path, label)
    if template["skill_id"] != package_id or template["skill_version"] != package_version:
        raise RepositoryValidationError(
            f"{label}: skill_id and skill_version must match the package manifest"
        )
    unit_ids = [unit["id"] for unit in template["units"]]
    if len(unit_ids) != len(set(unit_ids)):
        raise RepositoryValidationError(f"{label}: duplicate planning unit id")
    for unit in template["units"]:
        unknown = set(unit["source_ids"]) - known_source_ids
        if unknown:
            raise RepositoryValidationError(
                f"{label}: unit {unit['id']} references unknown sources {sorted(unknown)}"
            )


def _validate_learning_content(
    documents: dict[str, dict[str, Any]],
    schema_root: Path,
    labels: dict[str, str],
    package_id: str,
    package_version: str,
    known_source_ids: set[str],
    diagnostic: dict[str, Any] | None,
) -> None:
    required_kinds = {
        "learning_definition": "learning-definition.schema.json",
        "assessment_definition": "assessment-definition.schema.json",
        "rubric_definition": "rubric-definition.schema.json",
        "review_policy": "review-policy.schema.json",
        "mastery_scope": "mastery-scope.schema.json",
    }
    present = required_kinds.keys() & documents.keys()
    if not present:
        return
    if set(present) != set(required_kinds):
        missing = sorted(set(required_kinds) - set(present))
        raise RepositoryValidationError(
            f"{package_id}@{package_version}: learning content is incomplete; missing {missing}"
        )
    for kind, schema_name in required_kinds.items():
        document = documents[kind]
        _validate_with_schema(document, schema_root / schema_name, labels[kind])
        if document["skill_id"] != package_id or document["skill_version"] != package_version:
            raise RepositoryValidationError(
                f"{labels[kind]}: skill_id and skill_version must match the package manifest"
            )

    learning = documents["learning_definition"]
    unit_ids = [unit["id"] for unit in learning["units"]]
    if len(unit_ids) != len(set(unit_ids)):
        raise RepositoryValidationError(f"{labels['learning_definition']}: duplicate unit id")
    known_unit_ids = set(unit_ids)
    unit_graph: dict[str, list[str]] = {}
    for unit in learning["units"]:
        unknown_units = set(unit["prerequisite_unit_ids"]) - known_unit_ids
        unknown_sources = set(unit["source_ids"]) - known_source_ids
        if unknown_units:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: unit {unit['id']} has unknown prerequisites "
                f"{sorted(unknown_units)}"
            )
        if unknown_sources:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: unit {unit['id']} references unknown sources "
                f"{sorted(unknown_sources)}"
            )
        unit_graph[unit["id"]] = unit["prerequisite_unit_ids"]

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit_unit(unit_id: str) -> None:
        if unit_id in visiting:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: cyclic unit dependency at {unit_id}"
            )
        if unit_id in visited:
            return
        visiting.add(unit_id)
        for prerequisite in unit_graph[unit_id]:
            visit_unit(prerequisite)
        visiting.remove(unit_id)
        visited.add(unit_id)

    for unit_id in unit_graph:
        visit_unit(unit_id)

    activity_ids = [activity["id"] for activity in learning["activities"]]
    if len(activity_ids) != len(set(activity_ids)):
        raise RepositoryValidationError(f"{labels['learning_definition']}: duplicate activity id")
    known_activity_ids = set(activity_ids)
    for activity in learning["activities"]:
        if activity["unit_id"] not in known_unit_ids:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: activity {activity['id']} has unknown unit"
            )
        unknown_sources = set(activity["source_ids"]) - known_source_ids
        if unknown_sources:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: activity {activity['id']} references unknown "
                f"sources {sorted(unknown_sources)}"
            )
        field_ids = [field["id"] for field in activity["submission_fields"]]
        if len(field_ids) != len(set(field_ids)):
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: activity {activity['id']} has duplicate fields"
            )
        deterministic = activity.get("deterministic_check")
        if activity["completion_rule"] == "deterministic_pass":
            if deterministic is None:
                raise RepositoryValidationError(
                    f"{labels['learning_definition']}: deterministic activity "
                    f"{activity['id']} lacks a check"
                )
            if deterministic["field_id"] not in set(field_ids):
                raise RepositoryValidationError(
                    f"{labels['learning_definition']}: activity {activity['id']} check field "
                    "does not exist"
                )
        elif deterministic is not None:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: non-deterministic activity "
                f"{activity['id']} declares a check"
            )

    known_question_ids = (
        {question["id"] for question in diagnostic["questions"]} if diagnostic else set()
    )
    for rule in learning["diagnostic_remediation_rules"]:
        if rule["question_id"] not in known_question_ids:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: remediation {rule['id']} references unknown "
                "diagnostic question"
            )
        unknown_activities = set(rule["activity_ids"]) - known_activity_ids
        if unknown_activities:
            raise RepositoryValidationError(
                f"{labels['learning_definition']}: remediation {rule['id']} references unknown "
                f"activities {sorted(unknown_activities)}"
            )

    assessment = documents["assessment_definition"]
    criterion_ids = [criterion["id"] for criterion in assessment["criteria"]]
    if len(criterion_ids) != len(set(criterion_ids)):
        raise RepositoryValidationError(
            f"{labels['assessment_definition']}: duplicate criterion id"
        )
    for criterion in assessment["criteria"]:
        if criterion["activity_id"] not in known_activity_ids:
            raise RepositoryValidationError(
                f"{labels['assessment_definition']}: criterion {criterion['id']} references "
                "unknown activity"
            )

    rubric = documents["rubric_definition"]
    rubric_ids = [criterion["id"] for criterion in rubric["criteria"]]
    if len(rubric_ids) != len(set(rubric_ids)):
        raise RepositoryValidationError(f"{labels['rubric_definition']}: duplicate rubric id")
    for criterion in rubric["criteria"]:
        values = [level["value"] for level in criterion["levels"]]
        if len(values) != len(set(values)):
            raise RepositoryValidationError(
                f"{labels['rubric_definition']}: rubric {criterion['id']} has duplicate levels"
            )

    review = documents["review_policy"]
    intervals = review["interval_days"]
    if intervals != sorted(intervals) or any(
        current <= previous for previous, current in pairwise(intervals)
    ):
        raise RepositoryValidationError(
            f"{labels['review_policy']}: interval_days must be strictly increasing"
        )
    if review["completion_checkpoint"] != len(intervals):
        raise RepositoryValidationError(
            f"{labels['review_policy']}: completion_checkpoint must equal interval count"
        )
    unknown_review_sources = set(review["source_ids"]) - known_source_ids
    if unknown_review_sources:
        raise RepositoryValidationError(
            f"{labels['review_policy']}: references unknown sources "
            f"{sorted(unknown_review_sources)}"
        )

    mastery = documents["mastery_scope"]
    required_dimensions = {
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    }
    if set(mastery["dimensions"]) != required_dimensions:
        raise RepositoryValidationError(
            f"{labels['mastery_scope']}: all six mastery dimensions are required"
        )
    if {"verified", "retained", "mastered", "scope_criteria_met"} - set(
        mastery["prohibited_claims"]
    ):
        raise RepositoryValidationError(
            f"{labels['mastery_scope']}: 4A prohibited claims are incomplete"
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
        for field in ("id", "version", "state", "availability", "intake"):
            if manifest[field] != entry[field]:
                raise RepositoryValidationError(
                    f"{manifest_path}: {field} differs from registry entry"
                )

        source_catalogs: list[dict[str, Any]] = []
        planning_templates: list[tuple[dict[str, Any], Path]] = []
        diagnostic_definition: dict[str, Any] | None = None
        learning_documents: dict[str, dict[str, Any]] = {}
        learning_labels: dict[str, str] = {}
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
                diagnostic_definition = definition
            elif content["kind"] == "source_catalog":
                catalog = _load_yaml(content_path)
                _validate_source_catalog(
                    catalog,
                    repository_root / "contracts" / "skill-pack" / "source-catalog.schema.json",
                    str(content_path),
                    entry["id"],
                    entry["version"],
                )
                source_catalogs.append(catalog)
            elif content["kind"] == "planning_template":
                planning_templates.append((_load_yaml(content_path), content_path))
            elif content["kind"] in {
                "learning_definition",
                "assessment_definition",
                "rubric_definition",
                "review_policy",
                "mastery_scope",
            }:
                learning_documents[content["kind"]] = _load_yaml(content_path)
                learning_labels[content["kind"]] = str(content_path)

        if planning_templates and len(source_catalogs) != 1:
            raise RepositoryValidationError(
                f"{manifest_path}: planning templates require exactly one source catalog"
            )
        known_source_ids = (
            {source["id"] for source in source_catalogs[0]["sources"]} if source_catalogs else set()
        )
        for template, template_path in planning_templates:
            _validate_planning_template(
                template,
                repository_root / "contracts" / "skill-pack" / "planning-template.schema.json",
                str(template_path),
                entry["id"],
                entry["version"],
                known_source_ids,
            )
        _validate_learning_content(
            learning_documents,
            repository_root / "contracts" / "skill-pack",
            learning_labels,
            entry["id"],
            entry["version"],
            known_source_ids,
            diagnostic_definition,
        )

        packages.append(
            SkillPackage(
                package_id=entry["id"],
                version=entry["version"],
                path=package_path,
                state=entry["state"],
                availability=entry["availability"],
                intake=entry["intake"],
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
