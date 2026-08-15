from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from cloud_study_api.governance import (
    RepositoryValidationError,
    SkillPackage,
    load_skill_packages,
    validate_dependency_graph,
    validate_repository,
)
from jsonschema import Draft202012Validator, FormatChecker

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
    ".codex-m4-review",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".pytest-tmp",
    ".tmp",
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
        "apps/api/migrations/versions/0009_add_isolated_runner_4b.py",
        "apps/api/migrations/versions/0010_add_experiments_5c.py",
        "apps/api/src/cloud_study_api/main.py",
        "apps/api/src/cloud_study_api/backups.py",
        "apps/api/src/cloud_study_api/deployment.py",
        "apps/api/src/cloud_study_api/migration_rehearsal.py",
        "apps/api/src/cloud_study_api/runner_broker.py",
        "apps/api/src/cloud_study_api/security.py",
        "apps/api/src/cloud_study_api/experiments.py",
        "apps/api/src/cloud_study_api/readiness.py",
        "apps/api/src/cloud_study_api/runner.py",
        "apps/web/package.json",
        "apps/web/src/app/page.tsx",
        "apps/web/src/app/readiness/page.tsx",
        "contracts/api/openapi.json",
        "contracts/deployment/private-deployment-policy.schema.json",
        "contracts/readiness/user-goal.schema.json",
        "contracts/readiness/readiness-policy.schema.json",
        "contracts/readiness/market-evidence-snapshot.schema.json",
        "contracts/readiness/readiness-evaluation.schema.json",
        "contracts/readiness/path-comparison.schema.json",
        "contracts/readiness/experiment-policy.schema.json",
        "contracts/readiness/experiment-plan.schema.json",
        "contracts/readiness/independent-review.schema.json",
        "contracts/readiness/income-revision.schema.json",
        "contracts/readiness/learning-feedback.schema.json",
        "contracts/skill-pack/planning-template.schema.json",
        "contracts/skill-pack/learning-definition.schema.json",
        "docs/architecture/monetization-and-continuous-update.md",
        "contracts/skill-pack/assessment-definition.schema.json",
        "contracts/skill-pack/rubric-definition.schema.json",
        "contracts/skill-pack/review-policy.schema.json",
        "contracts/skill-pack/mastery-scope.schema.json",
        "contracts/skill-pack/source-catalog.schema.json",
        "contracts/runner/invocation.schema.json",
        "contracts/runner/invocation-v1.1.schema.json",
        "contracts/runner/result-v1.1.schema.json",
        "contracts/runner/runtime-registry.schema.json",
        "contracts/skill-pack/runner-task-definition.schema.json",
        "runtimes/registry.yaml",
        "tools/setup_runner_windows.ps1",
        "tools/provision_runner_images.ps1",
        "tools/manage_backup.py",
        "tools/deployment_preflight.py",
        "tools/provision_remote_runner_ubuntu.sh",
        "tools/run_migration_rehearsal.py",
        "tools/run_remote_runner_broker.py",
        "tools/run_private_preview_web.mjs",
        "tools/run_web_check.mjs",
        "tools/credential_file_name.py",
        "deployment/policies/single-user-singapore-v1.json",
        "deployment/private-preview.env.example",
        "deployment/systemd/cloud-study-api.service",
        "deployment/systemd/cloud-study-web.service",
        "deployment/systemd/cloud-study-backup.service",
        "deployment/systemd/cloud-study-backup.timer",
        "deployment/systemd/cloud-study-runner.service",
        "deployment/systemd/journald-cloud-study.conf",
        "docs/architecture/internet-deployment.md",
        "contracts/skill-pack/manifest.schema.json",
        "contracts/skill-pack/registry.schema.json",
        ".github/actions/setup-project/action.yml",
        ".github/workflows/ci.yml",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "skill-packs/registry.yaml",
        "readiness/policies/local-comparison-v1.json",
        "readiness/policies/employment-experiment-v1.json",
        "readiness/policies/employment-experiment-v2.json",
        "readiness/sources/official-cn-market-algorithm-0.2.1-v1.json",
        "readiness/sources/official-cn-market-algorithm-0.2.2-v1.json",
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
        "runner-contract",
        "runner-security",
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
        forbidden_execution_keys = ['"command"', '"file_upload"', '"local_path"']
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
        "runner",
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
            if strength in {"verified", "retained"} and method != "runner":
                raise CheckFailure(
                    f"{path}: scoped Runner evidence must use Runner evaluation"
                )
            if method == "runner" and strength not in {"verified", "retained"}:
                raise CheckFailure(
                    f"{path}: Runner evaluation must use scoped Runner evidence"
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
    for package, scope, path in scopes:
        if set(scope["dimensions"]) != required_dimensions:
            raise CheckFailure(
                f"{path}: mastery dimensions must remain the six dimensions"
            )
        runner_enabled = any(
            content["kind"] == "runner_task_definition"
            for content in package.manifest["content_files"]
        )
        required_prohibitions = {"scope_criteria_met", "mastered"}
        if not runner_enabled:
            required_prohibitions |= {"verified", "retained"}
        if not required_prohibitions <= set(scope["prohibited_claims"]):
            raise CheckFailure(
                f"{path}: required prohibited mastery claims are missing"
            )
        permitted_levels = {
            "limited",
            "supported",
            "retained_limited",
        }
        if runner_enabled:
            permitted_levels |= {"verified", "retained"}
            if not {"verified", "retained"} <= set(scope["allowed_evidence_levels"]):
                raise CheckFailure(
                    f"{path}: Runner scope must declare verified and retained boundaries"
                )
        if set(scope["allowed_evidence_levels"]) - permitted_levels:
            raise CheckFailure(f"{path}: unrestricted evidence level is not allowed")


def check_runner_contract(root: Path) -> None:
    schema_paths = [
        root / "contracts" / "runner" / "invocation.schema.json",
        root / "contracts" / "runner" / "invocation-v1.1.schema.json",
        root / "contracts" / "runner" / "result-v1.1.schema.json",
        root / "contracts" / "runner" / "runtime-registry.schema.json",
        root / "contracts" / "skill-pack" / "runner-task-definition.schema.json",
    ]
    for schema_path in schema_paths:
        Draft202012Validator.check_schema(_read_json(schema_path))
    legacy = _read_json(root / "contracts" / "runner" / "invocation.schema.json")
    if legacy["properties"]["protocol_version"].get("const") != "1.0.0":
        raise CheckFailure("historical Runner 1.0.0 invocation contract changed")

    registry_path = root / "runtimes" / "registry.yaml"
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    registry_schema = _read_json(
        root / "contracts" / "runner" / "runtime-registry.schema.json"
    )
    errors = sorted(
        Draft202012Validator(
            registry_schema, format_checker=FormatChecker()
        ).iter_errors(registry),
        key=lambda error: list(error.path),
    )
    if errors:
        raise CheckFailure(f"{registry_path}: {errors[0].message}")
    profiles = {
        (profile["id"], profile["version"]): profile for profile in registry["profiles"]
    }
    if len(profiles) != len(registry["profiles"]):
        raise CheckFailure(f"{registry_path}: duplicate runtime profile")
    provision_source = (root / "tools" / "provision_runner_images.ps1").read_text(
        encoding="utf-8"
    )
    missing_provisioned_images = [
        profile["image"]
        for profile in registry["profiles"]
        if profile["image"] not in provision_source
    ]
    if missing_provisioned_images:
        raise CheckFailure(
            "Runner provisioning script differs from the runtime registry: "
            f"{missing_provisioned_images}"
        )

    runner_definitions = _content_documents(root, "runner_task_definition")
    if not runner_definitions:
        raise CheckFailure("no governed Runner task definition")
    for package, definition, path in runner_definitions:
        if package.manifest["runner_protocol"]["version"] != "1.1.0":
            raise CheckFailure(f"{path}: Runner package must lock protocol 1.1.0")
        locked_profiles = {
            (item["id"], item["version"])
            for item in package.manifest["runtime_profiles"]
        }
        for task in definition["tasks"]:
            key = (task["runtime_profile_id"], task["runtime_profile_version"])
            if key not in locked_profiles or key not in profiles:
                raise CheckFailure(f"{path}: task {task['id']} runtime is not locked")
            profile = profiles[key]
            if profile["language"] != task["language"]:
                raise CheckFailure(
                    f"{path}: task {task['id']} language differs from runtime"
                )
            for test in task["tests"]:
                if len(test["stdin"].encode("utf-8")) > 65536:
                    raise CheckFailure(
                        f"{path}: test {test['id']} input exceeds 64 KiB"
                    )
                if len(test["expected_stdout"].encode("utf-8")) > 65536:
                    raise CheckFailure(
                        f"{path}: test {test['id']} expected output exceeds 64 KiB"
                    )


def check_runner_security(root: Path) -> None:
    source = (
        root / "apps" / "api" / "src" / "cloud_study_api" / "runner.py"
    ).read_text(encoding="utf-8")
    required_literals = {
        '"--network"',
        '"none"',
        '"--read-only"',
        '"--cap-drop"',
        '"ALL"',
        '"no-new-privileges=true"',
        '"seccomp=builtin"',
        '"--pids-limit"',
        '"--memory"',
        '"--memory-swap"',
        '"--cpus"',
        '"--pull"',
        '"never"',
        '"65534:65534"',
    }
    missing = sorted(item for item in required_literals if item not in source)
    if missing:
        raise CheckFailure(f"Runner security implementation lacks {missing}")
    forbidden_literals = {'"--privileged"', '"--volume"', '"--mount"', '"-v"'}
    found = sorted(item for item in forbidden_literals if item in source)
    if found:
        raise CheckFailure(
            f"Runner security implementation includes host access {found}"
        )
    if "subprocess.Popen(" not in source or "OUTPUT_LIMIT_BYTES = 65536" not in source:
        raise CheckFailure("Runner must enforce a live combined output cap")
    if "threading.Lock()" not in source or "acquire(blocking=False)" not in source:
        raise CheckFailure("Runner must enforce local concurrency one")


def _validate_json_instance(
    instance_path: Path,
    schema_path: Path,
) -> dict[str, Any]:
    instance = _read_json(instance_path)
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
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

    registry = _validate_json_instance(
        root / "readiness" / "market-research-registry-v1.json",
        root / "contracts" / "readiness" / "market-research-registry.schema.json",
    )
    if len(registry["registrations"]) != len(
        {
            (item["catalog_id"], item["catalog_version"])
            for item in registry["registrations"]
        }
    ):
        raise CheckFailure(
            "5B market research registry contains duplicate catalog versions"
        )
    catalogs: list[dict[str, Any]] = []
    for registration in registry["registrations"]:
        catalog_path = (root / registration["catalog_path"]).resolve()
        budget_path = (root / registration["budget_policy_path"]).resolve()
        if (
            root.resolve() not in catalog_path.parents
            or root.resolve() not in budget_path.parents
        ):
            raise CheckFailure(
                "5B market research registry path escapes the repository"
            )
        catalog = _validate_json_instance(
            catalog_path,
            root
            / "contracts"
            / "readiness"
            / "official-market-source-catalog.schema.json",
        )
        if (
            catalog["catalog_id"],
            catalog["version"],
        ) != (
            registration["catalog_id"],
            registration["catalog_version"],
        ):
            raise CheckFailure("5B registry catalog identity does not match its file")
        budget = _validate_json_instance(
            budget_path,
            root / "contracts" / "readiness" / "deepseek-budget-policy.schema.json",
        )
        if (
            budget["policy_id"],
            budget["version"],
        ) != (
            registration["budget_policy_id"],
            registration["budget_policy_version"],
        ):
            raise CheckFailure("5B registry budget identity does not match its file")
        catalogs.append(catalog)
    approved_sources = {
        "cn-nbs-data": ("中华人民共和国国家统计局", "www.stats.gov.cn"),
        "cn-mohrss-statistics": (
            "中华人民共和国人力资源和社会保障部",
            "www.mohrss.gov.cn",
        ),
        "cn-public-recruitment": ("中国公共招聘网", "job.mohrss.gov.cn"),
        "cn-miit-data": ("中华人民共和国工业和信息化部", "www.miit.gov.cn"),
    }
    expected_contexts = {
        ("algorithm", "0.2.0", "algorithm-entry-mastery-scope"),
        ("algorithm", "0.2.1", "algorithm-entry-mastery-scope"),
        ("algorithm", "0.2.2", "algorithm-entry-mastery-scope"),
    }
    actual_contexts = {
        (
            catalog["research_context"]["skill_id"],
            catalog["research_context"]["skill_version"],
            catalog["research_context"]["capability_scope_id"],
        )
        for catalog in catalogs
    }
    if actual_contexts != expected_contexts:
        raise CheckFailure(
            "5B market catalogs do not cover the governed skill versions"
        )
    for catalog in catalogs:
        if {source["id"] for source in catalog["sources"]} != set(approved_sources):
            raise CheckFailure(
                "5B official source IDs differ from the approved catalog"
            )
    catalog = catalogs[-1]
    covered_paths: set[str] = set()
    direct_paths: set[str] = set()
    independence_groups_by_owner: dict[str, set[str]] = {}
    independence_groups_by_path: dict[str, set[str]] = {
        path: set() for path in ("employment", "freelancing", "productization")
    }
    for source in catalog["sources"]:
        expected_owner, expected_host = approved_sources[source["id"]]
        parsed = urlsplit(source["url"])
        if (
            source["owner"] != expected_owner
            or parsed.scheme != "https"
            or parsed.hostname != expected_host
            or source["allowed_hosts"] != [expected_host]
        ):
            raise CheckFailure(
                f"{source['id']}: source owner, HTTPS URL, or host differs from approval"
            )
        covered_paths.update(source["paths"])
        independence_groups_by_owner.setdefault(source["owner"], set()).add(
            source["independence_group"]
        )
        for path in source["paths"]:
            independence_groups_by_path[path].add(source["independence_group"])
        if source["evidence_role"] == "direct_signal":
            direct_paths.update(source["paths"])
            observable = source.get("observable_signals", {})
            if any(path not in observable for path in source["paths"]):
                raise CheckFailure(
                    f"{source['id']}: direct signal source lacks observable terms for a path"
                )
    if covered_paths != {"employment", "freelancing", "productization"}:
        raise CheckFailure("5B official sources must cover all approved market paths")
    owners_with_multiple_independence_groups = sorted(
        owner
        for owner, groups in independence_groups_by_owner.items()
        if len(groups) > 1
    )
    if owners_with_multiple_independence_groups:
        raise CheckFailure(
            "5B pages from one source owner must not count as independent groups: "
            f"{owners_with_multiple_independence_groups}"
        )
    if set(catalog["path_evidence_capabilities"]) != set(
        catalog["research_context"]["allowed_paths"]
    ):
        raise CheckFailure(
            "5B path capability declarations must match the allowed paths"
        )
    for path, capability in catalog["path_evidence_capabilities"].items():
        if capability["coverage"] == "conclusive_supported" and (
            path not in direct_paths or len(independence_groups_by_path[path]) < 2
        ):
            raise CheckFailure(
                f"5B {path} declares conclusive support without a direct signal "
                "and two independent source groups"
            )
    context = catalog["research_context"]
    if set(context["allowed_paths"]) != {
        "employment",
        "freelancing",
        "productization",
    }:
        raise CheckFailure(
            "5B first catalog must explicitly allow the three approved paths"
        )
    if catalog["content_removal_policy"] != {
        "explicit_confirmation_required": True,
        "remove_saved_excerpt": True,
        "retain_hash_and_audit": True,
    }:
        raise CheckFailure(
            "5B source removal policy must redact excerpts and retain audit"
        )
    if (
        catalog["refresh_policy"]["metadata_interval_days"]
        != budget["metadata_refresh_interval_days"]
        or catalog["refresh_policy"]["synthesis_interval_days"]
        != budget["synthesis_interval_days"]
    ):
        raise CheckFailure(
            "5B catalog and budget refresh intervals must remain aligned"
        )
    if (
        catalog["refresh_policy"]["failure_cooldown_hours"] != 24
        or catalog["refresh_policy"]["manual_bypass_allowed"] is not False
    ):
        raise CheckFailure(
            "5B failed source access must cool down for 24 hours without manual bypass"
        )


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
    budget = _validate_json_instance(
        root / "readiness" / "policies" / "deepseek-v4-flash-budget-v1.json",
        root / "contracts" / "readiness" / "deepseek-budget-policy.schema.json",
    )
    if budget["automatic_top_up"]:
        raise CheckFailure("5B must never enable automatic top-up")
    if {
        budget["unknown_price_action"],
        budget["price_change_action"],
    } != {"stop"}:
        raise CheckFailure("5B must stop on unknown or changed prices")
    if budget["synthesis_lease_minutes"] != 5:
        raise CheckFailure("5B synthesis lease must remain the approved five minutes")
    experiment_policy = _validate_json_instance(
        root / "readiness" / "policies" / "employment-experiment-v2.json",
        root / "contracts" / "readiness" / "experiment-policy.schema.json",
    )
    if experiment_policy["enabled_paths"] != ["employment"]:
        raise CheckFailure("5C v1 must enable only the confirmed employment path")
    if set(experiment_policy["required_dimensions"]) != {
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    }:
        raise CheckFailure(
            "5C local approval must preserve all six evidence dimensions"
        )
    action_gate = experiment_policy["external_action_gate"]
    if action_gate["minimum_levels"] != {
        "operation": "verified",
        "retention": "retained",
    }:
        raise CheckFailure(
            "5C external action gate must require verified/retained evidence"
        )
    if action_gate["independent_review_dimensions"] != ["transfer", "artifact"]:
        raise CheckFailure(
            "5C must independently review transfer and artifact evidence"
        )
    if (
        action_gate["evidence_max_age_days"] != 90
        or action_gate["independent_review_max_age_days"] != 90
        or action_gate["market_max_age_days"] != 7
        or action_gate["independent_review_scope"] != "exact_capability_scope_id"
    ):
        raise CheckFailure("5C evidence, review, and market freshness policy changed")
    if action_gate["independent_review_rubrics"] != {
        "transfer": {
            "rubric_id": "external-transfer-v1",
            "rubric_version": "1.0.0",
        },
        "artifact": {
            "rubric_id": "external-artifact-v1",
            "rubric_version": "1.0.0",
        },
    }:
        raise CheckFailure("5C independent review rubric allowlist changed")
    if experiment_policy["external_action_mode"] != "manual_record_only":
        raise CheckFailure("5C must never execute external actions")
    income_policy = experiment_policy["income_policy"]
    if (
        income_policy["attachments_allowed"]
        or income_policy["default_visibility"] != "hidden"
        or income_policy["correction_mode"] != "append_revision"
        or income_policy["redaction_mode"] != "clear_sensitive_keep_tombstone"
    ):
        raise CheckFailure(
            "5C income privacy and append-only correction policy changed"
        )


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

    market_service_text = (
        root / "apps" / "api" / "src" / "cloud_study_api" / "market_research.py"
    ).read_text(encoding="utf-8")
    market_adapter_text = (
        root / "apps" / "api" / "src" / "cloud_study_api" / "market_ai.py"
    ).read_text(encoding="utf-8")
    required_guards = {
        '"external_ai_disabled"',
        '"external_ai_confirmation_required"',
        '"external_source_confirmation_required"',
        '"price_change_action"',
        '"unknown_price_action"',
        '"pricing_changed_or_unverifiable"',
        '"source_excerpt_redacted"',
        '"ai_synthesis_skipped"',
        "RobotFileParser",
        "MAX_SOURCE_BYTES",
        "MAX_EXCERPT_CHARS",
        '"synthesis_in_progress"',
        '"synthesis_input_preflight_exceeded"',
        '"external_ai_request_dispatch_started"',
        "catalog_snapshot_json",
        "budget_policy_snapshot_json",
        "normalized_content_sha256",
        "excerpt_sha256",
        '"recovery_required"',
        "MarketResearchSynthesisAttempt",
        "market-research-registry-v1.json",
        "deepseek_response_model_missing",
        "deepseek_response_model_mismatch",
        "response_model_id",
        "_outbound_source_material",
        "OUTBOUND_DATA_CATEGORIES",
        "EXCLUDED_DATA_CATEGORIES",
    }
    missing_guards = sorted(
        guard for guard in required_guards if guard not in market_service_text
    )
    if missing_guards:
        raise CheckFailure(f"5B external-call guards are missing: {missing_guards}")
    required_adapter_guards = {
        "class DeepSeekV4FlashMarketAdapter",
        '"https://api.deepseek.com/chat/completions"',
        '"deepseek-v4-flash"',
        '"api.deepseek.com"',
        '"stream": False',
        '"thinking": {"type": "disabled"}',
        "conservative_input_token_bound",
    }
    missing_adapter_guards = sorted(
        guard for guard in required_adapter_guards if guard not in market_adapter_text
    )
    if missing_adapter_guards:
        raise CheckFailure(
            f"5B DeepSeek adapter guards are missing: {missing_adapter_guards}"
        )
    forbidden_market_tokens = {
        "requests.",
        "httpx.",
        "time.sleep",
        "automatic_top_up = true",
        '"model": "deepseek-chat"',
        '"model": "deepseek-reasoner"',
    }
    found_market_tokens = sorted(
        token for token in forbidden_market_tokens if token in market_service_text
    )
    if found_market_tokens:
        raise CheckFailure(
            f"5B external-call boundary contains forbidden tokens: {found_market_tokens}"
        )

    experiment_text = (
        (root / "apps" / "api" / "src" / "cloud_study_api" / "experiments.py")
        .read_text(encoding="utf-8")
        .lower()
    )
    forbidden_experiment_tokens = {
        "import httpx",
        "import requests",
        "import urllib",
        "import socket",
        "import subprocess",
        "import smtplib",
        "webbrowser.",
        "selenium",
        "playwright",
        "credential_reference",
        "file_upload",
    }
    found_experiment_tokens = sorted(
        token for token in forbidden_experiment_tokens if token in experiment_text
    )
    if found_experiment_tokens:
        raise CheckFailure(
            f"5C external-action boundary contains forbidden tokens: "
            f"{found_experiment_tokens}"
        )
    required_experiment_guards = {
        '"manual_record_only"',
        '"completed_outside_product"',
        '"external_action_gate_not_ready"',
        '"income_action_record_required"',
        '"sensitive_export_confirmation_required"',
        '"learning_plan_modified": false',
    }
    missing_experiment_guards = sorted(
        guard for guard in required_experiment_guards if guard not in experiment_text
    )
    if missing_experiment_guards:
        raise CheckFailure(
            f"5C local-only or privacy guards are missing: {missing_experiment_guards}"
        )
    if '"/experiments"' not in route_text:
        raise CheckFailure("5C experiment routes are missing")


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


def check_deployment_policy(root: Path) -> None:
    schema = _read_json(
        root / "contracts/deployment/private-deployment-policy.schema.json"
    )
    policy = _read_json(root / "deployment/policies/single-user-singapore-v1.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            policy
        ),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise CheckFailure(
            f"deployment policy failed schema validation: {errors[0].message}"
        )

    required_values = {
        ("status",): "confirmed",
        ("access", "audience"): "owner_only",
        ("access", "registration"): "disabled",
        ("access", "ingress"): "tailscale_serve_private",
        ("identity", "provider"): "microsoft_personal",
        ("identity", "allowlist_size"): 1,
        ("platform", "provider"): "tencent_cloud",
        ("platform", "product"): "lighthouse",
        ("platform", "region"): "singapore",
        ("platform", "topology"): "single_instance",
        ("runtime", "node_major"): 24,
        ("runtime", "python"): "3.14.3",
        ("storage", "database"): "sqlite",
        ("runner", "remote_enabled"): False,
        ("external_calls", "enabled_by_default"): False,
        ("backup", "frequency"): "daily",
        ("backup", "daily_retention"): 7,
        ("backup", "weekly_retention"): 4,
        ("logs", "operations_retention_days"): 7,
        ("logs", "sensitive_body_logging"): False,
    }
    for path, expected in required_values.items():
        current: Any = policy
        for part in path:
            if not isinstance(current, dict) or part not in current:
                raise CheckFailure(f"deployment policy is missing {'.'.join(path)}")
            current = current[part]
        if current != expected:
            raise CheckFailure(
                f"deployment policy {'.'.join(path)} must remain {expected!r}"
            )

    authorization = policy["authorization"]
    if authorization != {
        "code_implementation": True,
        "cloud_resource_creation": True,
        "paid_service": True,
        "public_release": False,
    }:
        raise CheckFailure(
            "deployment authorization does not match the confirmed 6B resource scope"
        )
    budget = policy["budget"]
    if budget["expected_monthly"] > budget["monthly_hard_limit"]:
        raise CheckFailure("expected deployment cost exceeds the monthly hard limit")
    if budget["monthly_hard_limit"] != 50 or budget["alert_percentages"] != [50, 80]:
        raise CheckFailure("deployment cost stop or warning thresholds drifted")
    if budget["automatic_top_up"] or budget["automatic_scaling"]:
        raise CheckFailure("automatic spend expansion must remain disabled")

    source_hosts = {
        urlsplit(item["url"]).hostname
        for item in policy["sources"]
        if isinstance(item, dict) and isinstance(item.get("url"), str)
    }
    required_source_hosts = {"cloud.tencent.com", "tailscale.com", "www.miit.gov.cn"}
    if not required_source_hosts.issubset(source_hosts):
        raise CheckFailure(
            f"deployment policy is missing official evidence hosts: "
            f"{sorted(required_source_hosts - source_hosts)}"
        )

    api_unit = (root / "deployment/systemd/cloud-study-api.service").read_text(
        encoding="utf-8"
    )
    web_unit = (root / "deployment/systemd/cloud-study-web.service").read_text(
        encoding="utf-8"
    )
    web_launcher = (root / "tools/run_private_preview_web.mjs").read_text(
        encoding="utf-8"
    )
    backup_unit = (root / "deployment/systemd/cloud-study-backup.service").read_text(
        encoding="utf-8"
    )
    runner_unit = (root / "deployment/systemd/cloud-study-runner.service").read_text(
        encoding="utf-8"
    )
    runner_provision = (
        root / "tools/provision_remote_runner_ubuntu.sh"
    ).read_text(encoding="utf-8")
    env_template = (root / "deployment/private-preview.env.example").read_text(
        encoding="utf-8"
    )
    required_runtime_guards = [
        ("--host 127.0.0.1", api_unit),
        ("--no-access-log", api_unit),
        ("--no-proxy-headers", api_unit),
        ("ExecStartPre=", api_unit),
        ("IPAddressDeny=any", api_unit),
        ("tools/run_private_preview_web.mjs", web_unit),
        ('"--hostname", "127.0.0.1"', web_launcher),
        ("IPAddressDeny=any", web_unit),
        ("tools/manage_backup.py scheduled", backup_unit),
        ("RestrictAddressFamilies=AF_UNIX", backup_unit),
        ("User=cloud-study-runner", runner_unit),
        ("Group=cloud-study", runner_unit),
        ("SupplementaryGroups=docker", runner_unit),
        ("RestrictAddressFamilies=AF_UNIX", runner_unit),
        ("IPAddressDeny=any", runner_unit),
        ("NoNewPrivileges=true", runner_unit),
        ("ProtectSystem=strict", runner_unit),
        ("CapabilityBoundingSet=", runner_unit),
        ("--socket /run/cloud-study-runner/runner.sock", runner_unit),
        ("WorkingDirectory=/opt/cloud-study/runner/current", runner_unit),
        ("runuser -u cloud-study-runner -- test -x", runner_provision),
        ('python_version}" != "3.14.3', runner_provision),
        ("from cloud_study_api.runner_broker import serve_runner_broker", runner_provision),
        ("systemctl is-active --quiet cloud-study-runner.service", runner_provision),
        ("-S /run/cloud-study-runner/runner.sock", runner_provision),
        ("NEXT_PUBLIC_API_BASE_URL=/api", env_template),
        ("CLOUD_STUDY_DEPLOYMENT_MODE=private_preview", env_template),
    ]
    missing_runtime_guards = sorted(
        token for token, content in required_runtime_guards if token not in content
    )
    if missing_runtime_guards:
        raise CheckFailure(
            f"private deployment runtime guards are missing: {missing_runtime_guards}"
        )
    unit_text = f"{api_unit}\n{web_unit}\n{backup_unit}"
    forbidden_runtime_tokens = {"0.0.0.0", "docker.sock", "DockerData"}
    found_forbidden = sorted(
        token for token in forbidden_runtime_tokens if token in unit_text
    )
    if found_forbidden:
        raise CheckFailure(
            f"private deployment units contain forbidden exposure: {found_forbidden}"
        )
    if "[Install]" in runner_unit:
        raise CheckFailure("remote Runner broker must not be enabled before 6D")


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
    "runner-contract": check_runner_contract,
    "runner-security": check_runner_security,
    "market-sources": check_market_sources,
    "monetization-policy": check_monetization_policy,
    "external-call-boundary": check_external_call_boundary,
    "deployment-policy": check_deployment_policy,
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
