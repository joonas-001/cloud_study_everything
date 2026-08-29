import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from cloud_study_api.config import find_repository_root
from cloud_study_api.governance import (
    RepositoryValidationError,
    _validate_learning_core_contracts,
    _validate_learning_core_intake,
    validate_repository,
)


def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _learning_core_fixture() -> tuple[
    dict[str, dict[str, Any]], dict[str, str], dict[str, Any], dict[str, Any]
]:
    root = find_repository_root()
    package_root = root / "skill-packs" / "algorithm" / "versions" / "0.3.0"
    manifest = _load_yaml(package_root / "manifest.yaml")
    documents: dict[str, dict[str, Any]] = {}
    labels: dict[str, str] = {}
    source_catalog: dict[str, Any] | None = None
    diagnostic: dict[str, Any] | None = None
    for content in manifest["content_files"]:
        path = package_root / content["path"]
        if path.suffix != ".yaml":
            continue
        document = _load_yaml(path)
        if content["kind"] == "source_catalog":
            source_catalog = document
        elif content["kind"] == "diagnostic_definition":
            diagnostic = document
        else:
            documents[content["kind"]] = document
            labels[content["kind"]] = str(path)
    assert source_catalog is not None
    assert diagnostic is not None
    return documents, labels, source_catalog, diagnostic


def _validate_fixture(
    documents: dict[str, dict[str, Any]],
    labels: dict[str, str],
    source_catalog: dict[str, Any],
    diagnostic: dict[str, Any],
) -> None:
    _validate_learning_core_contracts(
        documents,
        find_repository_root() / "contracts" / "skill-pack",
        labels,
        "algorithm",
        "0.3.0",
        source_catalog,
        diagnostic,
    )


def test_repository_skill_packages_are_consistent() -> None:
    packages = validate_repository(find_repository_root())

    assert [(package.package_id, package.version) for package in packages] == [
        ("algorithm", "0.1.0"),
        ("algorithm", "0.2.0"),
        ("algorithm", "0.2.1"),
        ("algorithm", "0.2.2"),
        ("algorithm", "0.3.0"),
    ]
    assert packages[0].state == "draft"
    assert packages[0].availability == "available"
    assert packages[0].intake == "closed"
    assert (
        packages[0].manifest_sha256
        == "d6b69dc944070d80d5c1bc9f92144ed4bed4c5ef5d650deea8ae649ad21467df"
    )
    assert "intake" not in packages[0].manifest
    assert packages[1].state == "draft"
    assert packages[1].availability == "available"
    assert packages[1].intake == "closed"
    assert "intake" not in packages[1].manifest
    assert packages[2].state == "draft"
    assert packages[2].availability == "available"
    assert packages[2].intake == "closed"
    assert packages[2].manifest["runner_protocol"]["version"] == "1.1.0"
    assert "intake" not in packages[2].manifest
    assert packages[3].state == "draft"
    assert packages[3].availability == "available"
    assert packages[3].intake == "open"
    assert packages[3].manifest["runner_protocol"]["version"] == "1.1.0"
    assert packages[3].manifest_sha256 == (
        "384d1c275dfccbc2eb748c0bbb90e1e25106601ef2d8e711a6ce7538be075336"
    )
    assert "intake" not in packages[3].manifest
    assert packages[4].state == "draft"
    assert packages[4].availability == "available"
    assert packages[4].intake == "closed"
    assert packages[4].manifest["schema_version"] == "1.1.0"
    assert packages[4].manifest["runner_protocol"]["version"] == "1.1.0"
    assert "intake" not in packages[4].manifest


def test_learning_core_requires_all_new_contracts() -> None:
    documents, labels, source_catalog, diagnostic = _learning_core_fixture()
    documents.pop("diagnostic_policy")

    with pytest.raises(RepositoryValidationError, match="contracts are incomplete"):
        _validate_fixture(documents, labels, source_catalog, diagnostic)


def test_learning_core_rejects_capability_cycles() -> None:
    documents, labels, source_catalog, diagnostic = _learning_core_fixture()
    changed = copy.deepcopy(documents)
    changed["capability_graph"]["capabilities"][0]["prerequisite_capability_ids"] = [
        "p-functions-io"
    ]

    with pytest.raises(RepositoryValidationError, match="cyclic capability dependency"):
        _validate_fixture(changed, labels, source_catalog, diagnostic)


def test_learning_core_rejects_unknown_capability_references() -> None:
    documents, labels, source_catalog, diagnostic = _learning_core_fixture()
    changed = copy.deepcopy(documents)
    changed["capability_graph"]["capabilities"][0]["prerequisite_capability_ids"] = [
        "unknown-capability"
    ]

    with pytest.raises(RepositoryValidationError, match="unknown prerequisites"):
        _validate_fixture(changed, labels, source_catalog, diagnostic)


def test_learning_core_rejects_coverage_gaps() -> None:
    documents, labels, source_catalog, diagnostic = _learning_core_fixture()
    changed = copy.deepcopy(documents)
    changed["content_coverage"]["domains"][0]["required_activity_roles"].append("project")

    with pytest.raises(RepositoryValidationError, match="lacks activity roles"):
        _validate_fixture(changed, labels, source_catalog, diagnostic)


def test_learning_core_rejects_contradictory_diagnostic_answers() -> None:
    documents, labels, source_catalog, diagnostic = _learning_core_fixture()
    changed = copy.deepcopy(diagnostic)
    changed["questions"][0]["critical_misconception_values"] = ["scoped"]

    with pytest.raises(RepositoryValidationError, match="inconsistent answer metadata"):
        _validate_fixture(documents, labels, source_catalog, changed)


def test_learning_core_intake_must_remain_closed() -> None:
    documents, _, _, _ = _learning_core_fixture()

    with pytest.raises(RepositoryValidationError, match="must keep intake closed"):
        _validate_learning_core_intake(documents, "open", "algorithm@0.3.0")
