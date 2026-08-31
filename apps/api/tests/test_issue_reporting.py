from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from cloud_study_api.issue_reporting import find_prohibited_diagnostic_content
from cloud_study_api.main import app


def _payload(report_type: str = "bug") -> dict[str, object]:
    return {
        "report_type": report_type,
        "included_optional_fields": [
            "page_route",
            "operation_type",
            "skill_version",
            "request_audit_id",
            "reason_code",
            "event_names",
            "runner_details",
        ],
        "page_route": "/settings",
        "operation_type": "runner",
        "skill_version": "algorithm@0.3.0",
        "request_audit_id": "8d6b2d52-ff4f-4c84-8b36-a2a61ebbc792",
        "reason_code": "runner_unavailable",
        "event_names": ["runner_unavailable"],
    }


@pytest.mark.parametrize(
    ("report_type", "template"),
    [("bug", "bug.yml"), ("feature", "feature.yml"), ("content", "content.yml")],
)
def test_issue_preview_is_allowlist_only_and_never_submits(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    report_type: str,
    template: str,
) -> None:
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(tmp_path / "issue-preview.db"))
    monkeypatch.setenv("CLOUD_STUDY_RELEASE_COMMIT", "8cd0e36")

    with TestClient(app) as client:
        response = client.post("/settings/issue-report/preview", json=_payload(report_type))

    assert response.status_code == 200
    preview = response.json()
    assert preview["automatic_submission_enabled"] is False
    assert preview["attachments_enabled"] is False
    assert preview["copy_required_before_open"] is True
    assert f"template={template}" in preview["submission_url"]
    assert preview["submission_url"].startswith(
        "https://github.com/joonas-001/cloud_study_everything/issues/new?"
    )
    assert "- page_route: /settings" in preview["rendered_text"]
    assert "- skill_version: algorithm@0.3.0" in preview["rendered_text"]
    assert "- runner_details: protocol=1.1.0; gcc=15.2.0; python=3.14.3" in preview["rendered_text"]
    assert find_prohibited_diagnostic_content(preview["rendered_text"]) == []


def test_optional_fields_can_be_removed_from_the_complete_preview(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(tmp_path / "issue-fields.db"))

    with TestClient(app) as client:
        response = client.post(
            "/settings/issue-report/preview",
            json={
                "report_type": "bug",
                "included_optional_fields": ["runner_details"],
                "event_names": [],
            },
        )

    assert response.status_code == 200
    preview = response.json()
    keys = [field["key"] for field in preview["fields"]]
    assert "runner_details" in keys
    assert "page_route" not in keys
    assert "operation_type" not in keys
    assert "skill_version" not in keys
    assert "request_audit_id" not in keys
    assert "reason_code" not in keys
    assert "event_names" not in keys


@pytest.mark.parametrize(
    "patch",
    [
        {"page_route": "/users/owner/private"},
        {"operation_type": "paste_raw_log"},
        {"skill_version": "algorithm@9.9.9"},
        {"request_audit_id": "owner@example.com"},
        {"reason_code": "private=token"},
        {"event_names": ["raw_log_attached"]},
    ],
)
def test_unmanaged_or_sensitive_context_is_rejected(
    tmp_path: Path, monkeypatch: MonkeyPatch, patch: dict[str, object]
) -> None:
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(tmp_path / "issue-reject.db"))
    payload = _payload()
    payload.update(patch)

    with TestClient(app) as client:
        response = client.post("/settings/issue-report/preview", json=payload)

    assert response.status_code == 422
    body = response.json()
    detail = body.get("detail", {})
    if isinstance(detail, dict):
        assert detail["code"] == "unsafe_issue_diagnostic"
        assert "owner@example.com" not in detail["message"]


def test_prohibited_content_scanner_reports_codes_without_echoing_values() -> None:
    samples = [
        "path=" + "C:" + "\\private\\answer.txt",
        "email=" + "owner" + "@example.com",
        "private=" + "192.168." + "1.8",
        "credential=" + "sk" + "-" + ("x" * 20),
        "password" + "=" + "do-not-store",
        "url=" + "https" + "://private.example.invalid",
    ]

    for sample in samples:
        violations = find_prohibited_diagnostic_content(sample)
        assert violations
        assert all(sample not in violation for violation in violations)
