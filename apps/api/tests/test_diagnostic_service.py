from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.diagnostics import DiagnosticError, DiagnosticService
from cloud_study_api.governance import SkillPackage, validate_repository
from cloud_study_api.models import DiagnosticSession
from cloud_study_api.providers import (
    LocalDeterministicProvider,
    ProviderCapabilities,
    ProviderRegistry,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class ExternalDeterministicProvider(LocalDeterministicProvider):
    capabilities = ProviderCapabilities(
        provider_id="test-external",
        model_ids=frozenset({"test-model"}),
        is_external=True,
        supports_streaming=False,
    )


def test_external_provider_requires_both_permission_layers_and_credential(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "external-gate.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    package = replace(
        next(
            package
            for package in validate_repository(REPOSITORY_ROOT)
            if package.version == "0.2.2"
        ),
        state="active",
    )
    service = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=[package],
        session_factory=create_session_factory(database_path),
        provider_registry=ProviderRegistry([ExternalDeterministicProvider()]),
    )
    request = {
        "skill_id": package.package_id,
        "skill_version": package.version,
        "preview": False,
        "provider_id": "test-external",
        "model_id": "test-model",
    }

    with pytest.raises(DiagnosticError, match="global external AI") as disabled:
        service.create_session(
            **request,
            credential_reference="windows-credential:test",
            external_ai_consent=True,
        )
    assert disabled.value.code == "external_ai_disabled"

    service.update_privacy_settings(True)
    with pytest.raises(DiagnosticError, match="Conversation-level") as no_consent:
        service.create_session(
            **request,
            credential_reference="windows-credential:test",
            external_ai_consent=False,
        )
    assert no_consent.value.code == "conversation_consent_required"

    with pytest.raises(DiagnosticError, match="credential reference") as no_credential:
        service.create_session(
            **request,
            credential_reference=None,
            external_ai_consent=True,
        )
    assert no_credential.value.code == "credential_reference_required"

    created = service.create_session(
        **request,
        credential_reference="windows-credential:test",
        external_ai_consent=True,
    )
    service.update_privacy_settings(False)
    with pytest.raises(DiagnosticError, match="global external AI") as revoked:
        service.submit_answer(
            created["id"],
            question_id=created["current_question"]["id"],
            response_kind="uncertain",
            content=None,
        )
    assert revoked.value.code == "external_ai_disabled"


def test_inactivity_timeout_ends_session_without_silent_resume(tmp_path: Path) -> None:
    database_path = tmp_path / "timeout.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    package = next(
        package for package in validate_repository(REPOSITORY_ROOT) if package.version == "0.2.2"
    )
    clock = [datetime(2026, 7, 27, 8, 0, tzinfo=UTC)]
    service = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=[package],
        session_factory=create_session_factory(database_path),
        now=lambda: clock[0],
    )
    created = service.create_session(
        skill_id=package.package_id,
        skill_version=package.version,
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )

    clock[0] += timedelta(hours=2)
    with pytest.raises(DiagnosticError, match="No active session") as expired:
        service.get_active_session(package.package_id, package.version)
    assert expired.value.code == "active_session_not_found"

    ended = service.get_session(created["id"])
    assert ended["status"] == "ended"
    assert ended["end_reason"] == "inactivity_timeout"


def _adaptive_service(
    tmp_path: Path,
    clock: list[datetime],
) -> tuple[DiagnosticService, SkillPackage]:
    database_path = tmp_path / "adaptive.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    package = replace(
        next(
            package
            for package in validate_repository(REPOSITORY_ROOT)
            if package.version == "0.3.0"
        ),
        intake="open",
    )
    service = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=[package],
        session_factory=create_session_factory(database_path),
        now=lambda: clock[0],
    )
    return service, package


def _create_adaptive_preview(
    service: DiagnosticService,
    package: SkillPackage,
) -> dict[str, object]:
    return service.create_session(
        skill_id=package.package_id,
        skill_version=package.version,
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )


def test_adaptive_diagnostic_replays_and_recomputes_downstream_after_correction(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 8, 29, 9, 0, tzinfo=UTC)]
    service, package = _adaptive_service(tmp_path, clock)
    created = _create_adaptive_preview(service, package)

    assert created["diagnostic_mode"] == "deterministic_adaptive"
    assert created["decision"]["strategy"] == "adaptive"  # type: ignore[index]
    first_question = created["current_question"]["id"]  # type: ignore[index]
    assert first_question == "diagnostic-01-p-control-flow"

    first = service.submit_answer(
        str(created["id"]),
        question_id=first_question,
        response_kind="answered",
        content="scoped",
    )
    assert first["current_question"]["id"] == "diagnostic-47-p-control-flow"  # type: ignore[index]
    second = service.submit_answer(
        str(created["id"]),
        question_id="diagnostic-47-p-control-flow",
        response_kind="answered",
        content="scoped",
    )
    p_state = next(
        item for item in second["capability_states"] if item["capability_id"] == "p-control-flow"
    )
    assert p_state["status"] == "ready"
    replay_hash = second["decision"]["state_sha256"]
    replay_question = second["current_question"]["id"]  # type: ignore[index]

    resumed = service.get_session(str(created["id"]))
    assert resumed["decision"]["state_sha256"] == replay_hash
    assert resumed["current_question"]["id"] == replay_question  # type: ignore[index]

    restarted = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=[package],
        session_factory=create_session_factory(tmp_path / "adaptive.db"),
        now=lambda: clock[0],
    )
    recovered = restarted.get_session(str(created["id"]))
    assert recovered["decision"] == resumed["decision"]
    assert recovered["current_question"] == resumed["current_question"]

    corrected = service.correct_answer(
        str(created["id"]),
        first_question,
        response_kind="answered",
        content="overclaim",
    )
    corrected_p = next(
        item for item in corrected["capability_states"] if item["capability_id"] == "p-control-flow"
    )
    downstream = next(
        item for item in corrected["capability_states"] if item["capability_id"] == "p-functions-io"
    )
    assert corrected_p["status"] == "remediation_required"
    assert downstream["status"] == "inconclusive"
    assert "prerequisite-remediation-block" in downstream["reason_codes"]
    assert corrected["decision"]["state_sha256"] != replay_hash


def test_adaptive_diagnostic_rejects_corrupt_and_future_persisted_state(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 8, 29, 9, 0, tzinfo=UTC)]
    service, package = _adaptive_service(tmp_path, clock)
    created = _create_adaptive_preview(service, package)
    session_factory = service._session_factory

    with session_factory() as database:
        session = database.get(DiagnosticSession, str(created["id"]))
        assert session is not None
        session.current_question_id = "diagnostic-64-h-collision-load"
        session.updated_at = clock[0]
        database.commit()
    with pytest.raises(DiagnosticError) as corrupt:
        service.get_session(str(created["id"]))
    assert corrupt.value.code == "diagnostic_state_corrupt"

    with session_factory() as database:
        session = database.get(DiagnosticSession, str(created["id"]))
        assert session is not None
        session.current_question_id = created["current_question"]["id"]  # type: ignore[index]
        session.updated_at = clock[0] + timedelta(minutes=1)
        database.commit()
    with pytest.raises(DiagnosticError) as future:
        service.get_session(str(created["id"]))
    assert future.value.code == "diagnostic_future_state"


def test_adaptive_diagnostic_stops_at_question_and_time_limits(tmp_path: Path) -> None:
    clock = [datetime(2026, 8, 29, 9, 0, tzinfo=UTC)]
    service, package = _adaptive_service(tmp_path, clock)
    created = _create_adaptive_preview(service, package)
    current = created
    while current["status"] == "active":
        question_id = current["current_question"]["id"]  # type: ignore[index]
        current = service.submit_answer(
            str(created["id"]),
            question_id=question_id,
            response_kind="answered",
            content="scoped",
        )
    assert current["end_reason"] == "diagnostic_question_limit"
    assert current["decision"]["question_count"] == 36
    assert all(
        item["status"] in {"ready", "remediation_required", "inconclusive"}
        for item in current["capability_states"]
    )

    second_service, second_package = _adaptive_service(tmp_path / "time", clock)
    timed = _create_adaptive_preview(second_service, second_package)
    clock[0] += timedelta(minutes=50)
    with pytest.raises(DiagnosticError) as expired:
        second_service.get_active_session("algorithm", "0.3.0")
    assert expired.value.code == "active_session_not_found"
    ended = second_service.get_session(str(timed["id"]))
    assert ended["end_reason"] == "diagnostic_time_limit"
