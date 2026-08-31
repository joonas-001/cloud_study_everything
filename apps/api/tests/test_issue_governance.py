from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def test_three_issue_forms_are_required_and_use_managed_initial_labels() -> None:
    expected = {
        "bug.yml": "type:bug",
        "feature.yml": "type:enhancement",
        "content.yml": "type:content",
    }
    template_root = REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE"

    for filename, type_label in expected.items():
        document = yaml.safe_load((template_root / filename).read_text(encoding="utf-8"))
        assert document["labels"] == [type_label, "status:needs-triage"]
        assert document["body"]
        for item in document["body"]:
            if item["type"] in {"input", "textarea", "dropdown"}:
                assert item["attributes"]["label"]
        confirmations = [item for item in document["body"] if item["type"] == "checkboxes"]
        assert confirmations
        assert all(
            option["required"] is True
            for item in confirmations
            for option in item["attributes"]["options"]
        )

    config = yaml.safe_load((template_root / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    assert any("security/advisories/new" in link["url"] for link in config["contact_links"])


def test_managed_label_contract_has_unique_stable_semantics_and_no_remote_authority() -> None:
    contract = json.loads(
        (REPOSITORY_ROOT / "governance" / "issues-v1.json").read_text(encoding="utf-8")
    )
    labels = contract["labels"]
    names = [label["name"] for label in labels]

    assert contract["schema_version"] == "1.0.0"
    assert contract["remote_sync"]["authorized"] is False
    assert len(names) == len(set(names))
    assert all(re.fullmatch(r"[0-9a-f]{6}", label["color"]) for label in labels)
    for required in (
        "type:bug",
        "type:enhancement",
        "type:content",
        "status:needs-triage",
        "status:needs-info",
        "status:accepted",
        "status:blocked",
        "status:in-progress",
        "status:needs-verification",
        "known-issue",
        "duplicate",
        "regression",
    ):
        assert required in names

    lifecycle = contract["lifecycle"]
    assert lifecycle["manual_needs_info_close_after_days"] == 14
    assert lifecycle["automatic_close_enabled"] is False
    assert set(lifecycle["close_reasons"]) == {
        "completed",
        "duplicate",
        "not-planned",
        "cannot-reproduce",
    }
    assert contract["accepted_issue_requirements"] == {
        "github_milestone": True,
        "todo_id": True,
        "exact_stage": True,
        "implementation_authorized_by_acceptance": False,
    }


def test_public_reporting_assets_forbid_sensitive_attachments_and_preserve_authority() -> None:
    paths = [
        REPOSITORY_ROOT / "SECURITY.md",
        REPOSITORY_ROOT / "docs" / "contributing" / "reporting-issues.md",
        REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug.yml",
        REPOSITORY_ROOT / ".github" / "ISSUE_TEMPLATE" / "content.yml",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "不会自动提交" in combined
    assert "完整日志" in combined
    assert "不得" in combined
    normalized = "".join(combined.split())
    assert "不等于" in normalized or "不能扩大" in normalized
