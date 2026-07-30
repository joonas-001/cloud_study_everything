from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from cloud_study_api.governance import (
    RepositoryValidationError,
    SkillPackage,
    load_skill_packages,
    validate_dependency_graph,
    validate_repository,
)
from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".codex-m4-review",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".pnpm-store",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "coverage",
    "htmlcov",
    "node_modules",
}


class CheckFailure(RuntimeError):
    """Raised when a deterministic repository check fails."""


def iter_repository_files(root: Path) -> Iterable[Path]:
    for current_root, directory_names, file_names in os.walk(root):
        directory_names[:] = [
            name for name in directory_names if name not in EXCLUDED_PARTS
        ]
        current_path = Path(current_root)
        for file_name in file_names:
            yield current_path / file_name


def check_markdown(root: Path) -> None:
    errors: list[str] = []
    markdown_files = sorted(
        path for path in iter_repository_files(root) if path.suffix == ".md"
    )
    if not markdown_files:
        errors.append("repository contains no Markdown documents")

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(root)
        if not text.endswith("\n"):
            errors.append(f"{relative}: missing final newline")
        if "\x00" in text:
            errors.append(f"{relative}: contains a NUL byte")

        heading_levels: list[int] = []
        in_fence = False
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = re.match(r"^(#{1,6})\s+\S", line)
            if match:
                level = len(match.group(1))
                if heading_levels and level > heading_levels[-1] + 1:
                    errors.append(
                        f"{relative}:{line_number}: heading jumps from "
                        f"H{heading_levels[-1]} to H{level}"
                    )
                heading_levels.append(level)
        if heading_levels and heading_levels[0] != 1:
            errors.append(f"{relative}: first heading must be H1")

    if errors:
        raise CheckFailure("\n".join(errors))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CheckFailure(f"{path}: expected a JSON object")
    return value


def check_structure(root: Path) -> None:
    required_paths = [
        ".node-version",
        ".python-version",
        "AGENTS.md",
        "README.md",
        "TODO.md",
        "apps/api/pyproject.toml",
        "apps/api/alembic.ini",
        "apps/api/migrations/versions/0001_initialize_schema.py",
        "apps/api/migrations/versions/0003_add_learning_planning.py",
        "apps/api/migrations/versions/0004_add_indeterminate_source_status.py",
        "apps/api/migrations/versions/0005_add_learning_execution.py",
        "apps/api/migrations/versions/0006_add_readiness_5a.py",
        "apps/api/src/cloud_study_api/main.py",
        "apps/api/src/cloud_study_api/readiness.py",
        "apps/web/package.json",
        "apps/web/src/app/page.tsx",
        "apps/web/src/app/readiness/page.tsx",
        "contracts/api/openapi.json",
        "contracts/readiness/user-goal.schema.json",
        "contracts/readiness/readiness-policy.schema.json",
        "contracts/readiness/market-evidence-snapshot.schema.json",
        "contracts/readiness/readiness-evaluation.schema.json",
        "contracts/readiness/path-comparison.schema.json",
        "contracts/skill-pack/planning-template.schema.json",
        "contracts/skill-pack/learning-definition.schema.json",
        "docs/architecture/monetization-and-continuous-update.md",
        "contracts/skill-pack/assessment-definition.schema.json",
        "contracts/skill-pack/rubric-definition.schema.json",
        "contracts/skill-pack/review-policy.schema.json",
        "contracts/skill-pack/mastery-scope.schema.json",
        "contracts/skill-pack/source-catalog.schema.json",
        "contracts/runner/invocation.schema.json",
        "contracts/skill-pack/manifest.schema.json",
        "contracts/skill-pack/registry.schema.json",
        ".github/actions/setup-project/action.yml",
        ".github/workflows/ci.yml",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "skill-packs/registry.yaml",
        "readiness/policies/local-comparison-v1.json",
        "readiness/fixtures/market-current-v1.json",
        "readiness/fixtures/market-stale-v1.json",
        "readiness/fixtures/market-conflicted-v1.json",
        "readiness/fixtures/market-indeterminate-v1.json",
        "apps/api/uv.lock",
    ]
    missing = [path for path in required_paths if not (root / path).is_file()]
    if missing:
        raise CheckFailure(f"missing required repository files: {missing}")

    forbidden_names = {
        "package-lock.json",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "poetry.lock",
    }
    forbidden = [
        str(path.relative_to(root))
        for path in iter_repository_files(root)
        if path.name in forbidden_names
    ]
    if forbidden:
        raise CheckFailure(f"forbidden lock files found: {forbidden}")

    if (root / ".node-version").read_text(encoding="utf-8").strip() != "24":
        raise CheckFailure(".node-version must pin Node.js 24 LTS")
    if (root / ".python-version").read_text(encoding="utf-8").strip() != "3.14.3":
        raise CheckFailure(".python-version must pin Python 3.14.3")

    root_package = _read_json(root / "package.json")
    if root_package.get("packageManager") != "pnpm@11.9.0":
        raise CheckFailure("package.json must pin pnpm@11.9.0")

    for yaml_path in [
        root / ".github" / "actions" / "setup-project" / "action.yml",
        root / ".github" / "workflows" / "ci.yml",
    ]:
        try:
            yaml.compose(yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise CheckFailure(
                f"{yaml_path.relative_to(root)}: invalid YAML: {error}"
            ) from error

    workflow = yaml.load(
        (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    jobs = workflow.get("jobs", {}) if isinstance(workflow, dict) else {}
    actual_job_names = {
        job.get("name") for job in jobs.values() if isinstance(job, dict)
    }
    required_job_names = {
        "markdown-and-structure",
        "registry-consistency",
        "manifest-schema",
        "dependency-resolution",
        "source-policy",
        "planning-contract",
        "curriculum-graph",
        "assessment-contract",
        "review-policy",
        "mastery-policy",
        "market-sources",
        "monetization-policy",
        "external-call-boundary",
        "api-tests",
        "web-tests",
        "contract-drift",
        "secret-scan",
        "release-readiness",
    }
    missing_jobs = required_job_names - actual_job_names
    if missing_jobs:
        raise CheckFailure(f"CI is missing stable job names: {sorted(missing_jobs)}")

    triggers = workflow.get("on", {}) if isinstance(workflow, dict) else {}
    if isinstance(triggers, dict):
        serialized_triggers = json.dumps(triggers)
        if '"paths"' in serialized_triggers or '"paths-ignore"' in serialized_triggers:
            raise CheckFailure("CI must not path-filter required checks")


def check_registry(root: Path) -> None:
    validate_repository(root)


def check_manifest(root: Path) -> None:
    load_skill_packages(root)


def check_dependencies(root: Path) -> None:
    validate_dependency_graph(load_skill_packages(root))


def _content_documents(
    root: Path, kind: str
) -> list[tuple[SkillPackage, dict[str, Any], Path]]:
    documents: list[tuple[SkillPackage, dict[str, Any], Path]] = []
    for package in validate_repository(root):
        for content in package.manifest["content_files"]:
            if content["kind"] != kind:
                continue
            path = package.path / content["path"]
            documents.append(
                (package, yaml.safe_load(path.read_text(encoding="utf-8")), path)
            )
    return documents


def check_sources(root: Path) -> None:
    catalogs = _content_documents(root, "source_catalog")
    if not catalogs:
        raise CheckFailure(
            "no source catalog is governed by a registered skill package"
        )
    for package, catalog, path in catalogs:
        sources = catalog["sources"]
        if not any(source["authority_tier"] <= 3 for source in sources):
            raise CheckFailure(f"{path}: no authoritative source with tier 1-3")
        for source in sources:
            if not source["url"].startswith("https://"):
                raise CheckFailure(f"{path}: source {source['id']} must use HTTPS")
            if source["check_mode"] == "http_metadata" and not source.get(
                "retrieved_at"
            ):
                raise CheckFailure(
                    f"{path}: monitored source {source['id']} lacks retrieval date"
                )
        if not catalog["experts"]:
            raise CheckFailure(
                f"{package.package_id}@{package.version}: no expert evidence"
            )


def check_planning(root: Path) -> None:
    templates = _content_documents(root, "planning_template")
    if not templates:
        raise CheckFailure(
            "no planning template is governed by a registered skill package"
        )
    for _package, template, path in templates:
        for unit in template["units"]:
            if len(unit["completion_criteria"]) < 2:
                raise CheckFailure(
                    f"{path}: unit {unit['id']} needs at least two observable criteria"
                )
            if not unit["source_ids"]:
                raise CheckFailure(f"{path}: unit {unit['id']} has no traceable source")


def check_learning_content(root: Path) -> None:
    definitions = _content_documents(root, "learning_definition")
    if not definitions:
        raise CheckFailure(
            "no learning definition is governed by a registered skill package"
        )
    required_checkpoint_types = {
        "explanation",
        "code_text",
        "transfer",
        "correction",
        "project_evidence",
        "review",
    }
    for package, definition, path in definitions:
        activities = definition["activities"]
        activity_types = {activity["type"] for activity in activities}
        missing_types = required_checkpoint_types - activity_types
        if missing_types:
            raise CheckFailure(
                f"{path}: missing representative activity types {sorted(missing_types)}"
            )
        units = definition["units"]
        entry_units = [
            unit for unit in units if unit["id"] != "entry-evidence-checkpoint"
        ][:3]
        if len(entry_units) != 3:
            raise CheckFailure(
                f"{package.package_id}@{package.version}: expected three entry units"
            )
        for unit in entry_units:
            unit_types = {
                activity["type"]
                for activity in activities
                if activity["unit_id"] == unit["id"] and activity["required"]
            }
            if not {"study", "structured_check"} <= unit_types:
                raise CheckFailure(
                    f"{path}: unit {unit['id']} needs required study and structured check"
                )
        serialized = json.dumps(definition, ensure_ascii=False).lower()
        forbidden_execution_keys = [
            '"command"',
            '"runtime_profile"',
            '"file_upload"',
            '"local_path"',
        ]
        found = [key for key in forbidden_execution_keys if key in serialized]
        if found:
            raise CheckFailure(
                f"{path}: executable or filesystem fields found: {found}"
            )


def check_assessment(root: Path) -> None:
    assessments = _content_documents(root, "assessment_definition")
    rubrics = _content_documents(root, "rubric_definition")
    if not assessments or not rubrics:
        raise CheckFailure("assessment and rubric definitions must both be governed")
    required_dimensions = {
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    }
    permitted_methods = {
        "deterministic",
        "self_review",
        "review_pending",
        "not_executable",
    }
    for _package, assessment, path in assessments:
        criteria = assessment["criteria"]
        dimensions = {criterion["dimension"] for criterion in criteria}
        if dimensions != required_dimensions:
            raise CheckFailure(
                f"{path}: assessment dimensions differ: {sorted(dimensions)}"
            )
        for criterion in criteria:
            method = criterion["evaluation_method"]
            strength = criterion["evidence_strength"]
            if method not in permitted_methods:
                raise CheckFailure(f"{path}: unsupported evaluation method {method}")
            if strength == "supported" and method != "deterministic":
                raise CheckFailure(f"{path}: supported evidence must be deterministic")
            if strength == "retained_limited" and criterion["dimension"] != "retention":
                raise CheckFailure(
                    f"{path}: retained_limited is restricted to retention"
                )
    for _package, rubric, path in rubrics:
        for criterion in rubric["criteria"]:
            values = {level["value"] for level in criterion["levels"]}
            if values != {"not_yet", "uncertain", "meets"}:
                raise CheckFailure(
                    f"{path}: rubric {criterion['id']} must use the bounded self-review scale"
                )


def check_review_policy(root: Path) -> None:
    policies = _content_documents(root, "review_policy")
    if not policies:
        raise CheckFailure("no review policy is governed by a registered skill package")
    for _package, policy, path in policies:
        if policy["strategy"] != "fixed_expanding":
            raise CheckFailure(f"{path}: 4A review strategy must be fixed_expanding")
        if policy["interval_days"] != [1, 2, 4, 7, 15]:
            raise CheckFailure(f"{path}: 4A review intervals must be 1,2,4,7,15")
        if policy["failure_retry_days"] != 1:
            raise CheckFailure(f"{path}: failed review retry must be one day")
        if policy["missed_task_behavior"] != "overdue_not_failure":
            raise CheckFailure(f"{path}: overdue review must not count as failure")
        if policy["completion_checkpoint"] != len(policy["interval_days"]):
            raise CheckFailure(
                f"{path}: completion checkpoint must be the final interval"
            )
        if len(policy["source_ids"]) < 2:
            raise CheckFailure(f"{path}: review policy needs cross-checked sources")


def check_mastery_policy(root: Path) -> None:
    scopes = _content_documents(root, "mastery_scope")
    if not scopes:
        raise CheckFailure("no mastery scope is governed by a registered skill package")
    required_dimensions = {
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    }
    required_prohibitions = {
        "scope_criteria_met",
        "verified",
        "retained",
        "mastered",
    }
    for _package, scope, path in scopes:
        if set(scope["dimensions"]) != required_dimensions:
            raise CheckFailure(
                f"{path}: mastery dimensions must remain the six dimensions"
            )
        if not required_prohibitions <= set(scope["prohibited_claims"]):
            raise CheckFailure(
                f"{path}: required prohibited mastery claims are missing"
            )
        if set(scope["allowed_evidence_levels"]) - {
            "limited",
            "supported",
            "retained_limited",
        }:
            raise CheckFailure(
                f"{path}: unrestricted evidence level is not allowed in 4A"
            )


def _validate_json_instance(
    instance_path: Path,
    schema_path: Path,
) -> dict[str, Any]:
    instance = _read_json(instance_path)
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    if errors:
        detail = "; ".join(
            f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise CheckFailure(f"{instance_path.relative_to(REPOSITORY_ROOT)}: {detail}")
    return instance


def check_market_sources(root: Path) -> None:
    schema_path = (
        root / "contracts" / "readiness" / "market-evidence-snapshot.schema.json"
    )
    fixture_paths = sorted((root / "readiness" / "fixtures").glob("*.json"))
    if len(fixture_paths) < 4:
        raise CheckFailure(
            "5A requires current, stale, conflicted, and indeterminate fixtures"
        )
    statuses: set[str] = set()
    for path in fixture_paths:
        fixture = _validate_json_instance(path, schema_path)
        if not fixture["synthetic"] or fixture["mode"] != "synthetic_fixture":
            raise CheckFailure(f"{path}: 5A market fixture must remain synthetic")
        statuses.add(fixture["freshness_status"])
        source_ids = {source["id"] for source in fixture["sources"]}
        if len(source_ids) < 2:
            raise CheckFailure(
                f"{path}: synthetic conclusion needs two fixture sources"
            )
        for source in fixture["sources"]:
            if not source["locator"].startswith("synthetic://"):
                raise CheckFailure(f"{path}: remote locator is forbidden in 5A")
        if {item["path"] for item in fixture["paths"]} != {
            "employment",
            "freelancing",
            "productization",
        }:
            raise CheckFailure(f"{path}: all three comparison paths are required")
        for item in fixture["paths"]:
            if not set(item["source_ids"]) <= source_ids:
                raise CheckFailure(f"{path}: path references an unknown fixture source")
    required = {"current", "stale", "conflicted", "indeterminate"}
    if statuses != required:
        raise CheckFailure(f"5A fixture freshness coverage differs: {sorted(statuses)}")


def check_monetization_policy(root: Path) -> None:
    policy = _validate_json_instance(
        root / "readiness" / "policies" / "local-comparison-v1.json",
        root / "contracts" / "readiness" / "readiness-policy.schema.json",
    )
    if set(policy["required_dimensions"]) != {
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    }:
        raise CheckFailure("5A readiness policy must preserve all six dimensions")
    if policy["real_user_max_status"] != "comparison_ready":
        raise CheckFailure("5A real users must never reach experiment_ready")
    if "experiment_threshold_unconfirmed" not in policy["reason_codes"]:
        raise CheckFailure("5A policy must expose the unconfirmed experiment threshold")
    if "goal_not_monetization" not in policy["reason_codes"]:
        raise CheckFailure("5A policy must support non-monetization goals")


def check_external_call_boundary(root: Path) -> None:
    service_path = root / "apps" / "api" / "src" / "cloud_study_api" / "readiness.py"
    text = service_path.read_text(encoding="utf-8").lower()
    forbidden = {
        "import httpx",
        "import requests",
        "import urllib",
        "import socket",
        "import subprocess",
        "http://",
        "https://",
        "smtp",
        "credential_reference",
        "code_execution",
        "file_upload",
        "local_path",
    }
    found = sorted(token for token in forbidden if token in text)
    if found:
        raise CheckFailure(
            f"5A external-call boundary contains forbidden tokens: {found}"
        )
    route_text = (
        root / "apps" / "api" / "src" / "cloud_study_api" / "routes.py"
    ).read_text(encoding="utf-8")
    forbidden_routes = {
        '"/readiness/experiments"',
        '"/readiness/external-research"',
        '"/readiness/market-refresh"',
    }
    found_routes = sorted(route for route in forbidden_routes if route in route_text)
    if found_routes:
        raise CheckFailure(f"5A exposes forbidden routes: {found_routes}")


def check_contracts(root: Path) -> None:
    schema_paths = sorted((root / "contracts").rglob("*.schema.json"))
    if not schema_paths:
        raise CheckFailure("no JSON Schema contracts found")
    for schema_path in schema_paths:
        Draft202012Validator.check_schema(_read_json(schema_path))

    openapi_path = root / "contracts" / "api" / "openapi.json"
    openapi = _read_json(openapi_path)
    if not isinstance(openapi.get("openapi"), str):
        raise CheckFailure("OpenAPI contract is missing its version")
    paths = openapi.get("paths")
    if not isinstance(paths, dict) or "/health" not in paths:
        raise CheckFailure("OpenAPI contract must contain the /health path")


def find_secrets(root: Path) -> list[str]:
    patterns = [
        re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(
            r"""(?ix)
            (?:api[_-]?key|client[_-]?secret|access[_-]?token|password)
            \s*[:=]\s*
            ["'][^"'{}\s]{8,}["']
            """
        ),
    ]
    findings: list[str] = []
    skipped_suffixes = {
        ".gif",
        ".ico",
        ".jpeg",
        ".jpg",
        ".lock",
        ".png",
        ".pyc",
        ".sqlite",
        ".woff",
        ".woff2",
    }
    for path in iter_repository_files(root):
        if path.suffix.lower() in skipped_suffixes or path.name == "pnpm-lock.yaml":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if any(pattern.search(line) for pattern in patterns):
                findings.append(f"{path.relative_to(root)}:{line_number}")
    return findings


def check_secrets(root: Path) -> None:
    findings = find_secrets(root)
    if findings:
        raise CheckFailure(f"potential secrets found: {findings}")


CHECKS = {
    "markdown": check_markdown,
    "structure": check_structure,
    "registry": check_registry,
    "manifest": check_manifest,
    "dependencies": check_dependencies,
    "sources": check_sources,
    "planning": check_planning,
    "learning-content": check_learning_content,
    "assessment": check_assessment,
    "review-policy": check_review_policy,
    "mastery-policy": check_mastery_policy,
    "market-sources": check_market_sources,
    "monetization-policy": check_monetization_policy,
    "external-call-boundary": check_external_call_boundary,
    "contracts": check_contracts,
    "secrets": check_secrets,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic repository checks.")
    parser.add_argument("check", choices=sorted(CHECKS))
    args = parser.parse_args()
    try:
        CHECKS[args.check](REPOSITORY_ROOT)
    except (CheckFailure, RepositoryValidationError, json.JSONDecodeError) as error:
        print(f"{args.check}: FAILED\n{error}", file=sys.stderr)
        return 1
    print(f"{args.check}: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
