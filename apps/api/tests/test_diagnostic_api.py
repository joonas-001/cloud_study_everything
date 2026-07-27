from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import func, select

from cloud_study_api.database import create_session_factory
from cloud_study_api.main import app
from cloud_study_api.models import DiagnosticAnswer, DiagnosticEvent


def _create_preview(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/diagnostic-sessions",
        json={
            "skill_id": "algorithm",
            "skill_version": "0.1.0",
            "preview": True,
            "provider_id": "local-deterministic",
            "model_id": "diagnostic-v1",
            "credential_reference": None,
            "external_ai_consent": False,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_preview_session_supports_resume_branching_correction_and_end(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "diagnostic-api.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))

    with TestClient(app) as client:
        privacy = client.get("/settings/privacy")
        assert privacy.status_code == 200
        assert privacy.json()["external_ai_enabled"] is False
        assert privacy.json()["inactivity_timeout_minutes"] == 120

        missing = client.get(
            "/diagnostic-sessions/active",
            params={"skill_id": "algorithm", "skill_version": "0.1.0"},
        )
        assert missing.status_code == 404

        created = _create_preview(client)
        session_id = str(created["id"])
        assert created["is_preview"] is True
        assert created["external_ai_consent"] is False
        assert created["can_generate_plan"] is False
        assert created["current_question"]["id"] == "programming-background"  # type: ignore[index]

        duplicate = client.post(
            "/diagnostic-sessions",
            json={
                "skill_id": "algorithm",
                "skill_version": "0.1.0",
                "preview": True,
                "provider_id": "local-deterministic",
                "model_id": "diagnostic-v1",
                "credential_reference": None,
                "external_ai_consent": False,
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "active_session_exists"
        assert duplicate.json()["detail"]["context"]["session_id"] == session_id

        uncertain = client.post(
            f"/diagnostic-sessions/{session_id}/answers",
            json={
                "question_id": "programming-background",
                "response_kind": "uncertain",
                "content": None,
            },
        )
        assert uncertain.status_code == 200
        assert uncertain.json()["current_question"]["id"] == "programming-foundation-check"

        corrected = client.post(
            f"/diagnostic-sessions/{session_id}/answers/programming-background/corrections",
            json={
                "response_kind": "answered",
                "content": "我使用 Python 写过一个读取文本并统计单词的小程序。",
            },
        )
        assert corrected.status_code == 200
        corrected_body = corrected.json()
        assert corrected_body["current_question"]["id"] == "data-structure-understanding"
        assert corrected_body["answers"][0]["revision"] == 2
        assert corrected_body["answers"][0]["response_kind"] == "answered"

        resumed = client.get(
            "/diagnostic-sessions/active",
            params={"skill_id": "algorithm", "skill_version": "0.1.0"},
        )
        assert resumed.status_code == 200
        assert resumed.json()["id"] == session_id

        ended = client.post(f"/diagnostic-sessions/{session_id}/end")
        assert ended.status_code == 200
        assert ended.json()["status"] == "ended"
        assert ended.json()["end_reason"] == "user_ended"

        write_after_end = client.post(
            f"/diagnostic-sessions/{session_id}/answers",
            json={
                "question_id": "data-structure-understanding",
                "response_kind": "skipped",
                "content": None,
            },
        )
        assert write_after_end.status_code == 409
        assert write_after_end.json()["detail"]["code"] == "session_not_active"

    session_factory = create_session_factory(database_path)
    with session_factory() as database:
        answer_revisions = database.scalar(select(func.count(DiagnosticAnswer.id)))
        event_count = database.scalar(select(func.count(DiagnosticEvent.id)))
    assert answer_revisions == 2
    assert event_count is not None and event_count >= 7


def test_privacy_setting_can_change_without_enabling_preview_external_access(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "privacy-api.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))

    with TestClient(app) as client:
        updated = client.put(
            "/settings/privacy",
            json={"external_ai_enabled": True},
        )
        assert updated.status_code == 200
        assert updated.json()["external_ai_enabled"] is True

        forbidden_preview = client.post(
            "/diagnostic-sessions",
            json={
                "skill_id": "algorithm",
                "skill_version": "0.1.0",
                "preview": True,
                "provider_id": "local-deterministic",
                "model_id": "diagnostic-v1",
                "credential_reference": "must-not-be-used",
                "external_ai_consent": True,
            },
        )
        assert forbidden_preview.status_code == 409
        assert forbidden_preview.json()["detail"]["code"] == "preview_forbids_external_ai"
