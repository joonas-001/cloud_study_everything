from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml
from cloud_study_api.governance import (
    RepositoryValidationError,
    load_skill_packages,
    validate_dependency_graph,
    validate_repository,
)
from jsonschema import Draft202012Validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {
    ".git",
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
    for path in root.rglob("*"):
        if path.is_file() and not EXCLUDED_PARTS.intersection(
            path.relative_to(root).parts
        ):
            yield path


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
        "apps/api/pyproject.toml",
        "apps/api/alembic.ini",
        "apps/api/migrations/versions/0001_initialize_schema.py",
        "apps/api/src/cloud_study_api/main.py",
        "apps/web/package.json",
        "apps/web/src/app/page.tsx",
        "contracts/api/openapi.json",
        "contracts/runner/invocation.schema.json",
        "contracts/skill-pack/manifest.schema.json",
        "contracts/skill-pack/registry.schema.json",
        ".github/actions/setup-project/action.yml",
        ".github/workflows/ci.yml",
        "package.json",
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "skill-packs/registry.yaml",
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
