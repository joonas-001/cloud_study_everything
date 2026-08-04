from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from tools import deployment_preflight

from cloud_study_api.backups import generate_backup_key_pair
from cloud_study_api.credentials import CredentialStoreError, ReadOnlyFileCredentialStore
from cloud_study_api.database import upgrade_database
from cloud_study_api.deployment import DeploymentConfigurationError, DeploymentSettings
from cloud_study_api.main import app

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
OWNER_LOGIN = "owner@example.com"
PRIVATE_ORIGIN = "https://cloud-study.example.ts.net"


def _configure_private_preview(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    secret_directory = tmp_path / "secrets"
    secret_directory.mkdir()
    monkeypatch.setenv("CLOUD_STUDY_DEPLOYMENT_MODE", "private_preview")
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(tmp_path / "private.sqlite3"))
    monkeypatch.setenv("CLOUD_STUDY_CREDENTIAL_STORE", "file")
    monkeypatch.setenv("CLOUD_STUDY_SECRET_DIRECTORY", str(secret_directory.resolve()))
    monkeypatch.setenv("CLOUD_STUDY_OWNER_LOGIN", OWNER_LOGIN)
    monkeypatch.setenv("CLOUD_STUDY_ALLOWED_ORIGIN", PRIVATE_ORIGIN)


def test_private_preview_requires_complete_exact_configuration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLOUD_STUDY_DEPLOYMENT_MODE", "private_preview")
    with pytest.raises(DeploymentConfigurationError, match="CLOUD_STUDY_CREDENTIAL_STORE"):
        DeploymentSettings.from_environment(REPOSITORY_ROOT)

    _configure_private_preview(tmp_path, monkeypatch)
    settings = DeploymentSettings.from_environment(REPOSITORY_ROOT)
    assert settings.mode == "private_preview"
    assert settings.owner_login == OWNER_LOGIN
    assert settings.allowed_origin == PRIVATE_ORIGIN
    assert settings.remote_runner_enabled is False
    assert settings.external_calls_enabled is False

    monkeypatch.setenv("CLOUD_STUDY_ALLOWED_ORIGIN", "https://example.com")
    with pytest.raises(DeploymentConfigurationError, match=r"\*\.ts\.net"):
        DeploymentSettings.from_environment(REPOSITORY_ROOT)


def test_private_preview_enforces_proxy_owner_origin_and_capability_stops(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_private_preview(tmp_path, monkeypatch)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.headers["x-frame-options"] == "DENY"
        assert "max-age=31536000" in health.headers["strict-transport-security"]

        missing_owner = client.get("/deployment/status")
        assert missing_owner.status_code == 401
        assert missing_owner.json()["detail"]["code"] == "authentication_required"

        wrong_owner = client.get(
            "/deployment/status",
            headers={"Tailscale-User-Login": "other@example.com"},
        )
        assert wrong_owner.status_code == 403
        assert wrong_owner.json()["detail"]["code"] == "owner_identity_required"

        headers = {"Tailscale-User-Login": OWNER_LOGIN}
        status = client.get("/deployment/status", headers=headers)
        assert status.status_code == 200
        assert status.json() == {
            "mode": "private_preview",
            "authentication_required": True,
            "identity_provider": "microsoft_personal",
            "owner_login_configured": True,
            "region": "singapore",
            "data_store": "sqlite",
            "remote_runner_enabled": False,
            "external_calls_enabled": False,
            "monthly_budget_cny": 50,
        }

        no_origin = client.put(
            "/settings/privacy",
            headers=headers,
            json={"external_ai_enabled": True},
        )
        assert no_origin.status_code == 403
        assert no_origin.json()["detail"]["code"] == "csrf_origin_rejected"

        blocked_external = client.put(
            "/settings/privacy",
            headers={**headers, "Origin": PRIVATE_ORIGIN},
            json={"external_ai_enabled": True},
        )
        assert blocked_external.status_code == 409
        assert blocked_external.json()["detail"]["code"] == "external_calls_disabled"

        blocked_diagnostic = client.post(
            "/diagnostic-sessions",
            headers={**headers, "Origin": PRIVATE_ORIGIN},
            json={
                "skill_id": "algorithm",
                "skill_version": "0.2.1",
                "preview": False,
                "provider_id": "deepseek",
                "model_id": "deepseek-v4-flash",
                "credential_reference": "provider-key",
                "external_ai_consent": True,
            },
        )
        assert blocked_diagnostic.status_code == 409
        assert blocked_diagnostic.json()["detail"]["code"] == "external_calls_disabled"

        runner = client.get("/runner/availability", headers=headers)
        assert runner.status_code == 200
        assert runner.json()["available"] is False
        assert runner.json()["reason_code"] == "remote_runner_disabled"


def test_cloud_credential_filename_maps_existing_path_like_references() -> None:
    filename = ReadOnlyFileCredentialStore.filename_for_reference(
        "cloud-study/ai/00000000-0000-0000-0000-000000000000"
    )
    assert filename.startswith("sha256-")
    assert filename.endswith(".secret")
    assert "/" not in filename


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are enforced on the cloud host")
def test_read_only_file_credential_store_enforces_mode_and_no_mutation(
    tmp_path: Path,
) -> None:
    directory = tmp_path.resolve()
    reference = "cloud-study/ai/profile-id"
    credential = directory / ReadOnlyFileCredentialStore.filename_for_reference(reference)
    credential.write_text("secret-value\n", encoding="utf-8")
    credential.chmod(0o600)
    store = ReadOnlyFileCredentialStore(directory)
    assert store.get(reference) == "secret-value"
    with pytest.raises(CredentialStoreError, match="read-only"):
        store.put(reference, "replacement")

    credential.chmod(0o644)
    with pytest.raises(CredentialStoreError, match="group or world"):
        store.get(reference)


def test_private_preview_preflight_is_read_only_and_version_locked(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    _configure_private_preview(tmp_path, monkeypatch)
    database_path = tmp_path / "private.sqlite3"
    upgrade_database(database_path, REPOSITORY_ROOT)
    private_key = tmp_path / "offline-private.pem"
    public_key = tmp_path / "backup-public.pem"
    generate_backup_key_pair(private_key, public_key)
    monkeypatch.setenv("CLOUD_STUDY_BACKUP_PUBLIC_KEY", str(public_key.resolve()))

    versions = {
        "node": "v24.14.0",
        "pnpm": "11.9.0",
        "uv": "uv 0.11.32",
    }
    monkeypatch.setattr(
        deployment_preflight,
        "_command_version",
        lambda command: versions[command],
    )
    result = deployment_preflight.run_preflight()
    assert result["ok"] is True
    assert result["database_revision"] == "0010"
    assert result["remote_runner_enabled"] is False
    assert result["external_calls_enabled"] is False
