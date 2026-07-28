from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.diagnostics import DiagnosticError, DiagnosticService
from cloud_study_api.governance import validate_repository
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
            if package.version == "0.2.0"
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
        package for package in validate_repository(REPOSITORY_ROOT) if package.version == "0.2.0"
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
