from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cloud_study_api.deployment import DeploymentSettings

AuthenticationMode = Literal["legacy_owner", "synthetic_oidc", "managed_oidc"]


@dataclass(frozen=True, slots=True)
class AuthenticationSettings:
    mode: AuthenticationMode
    issuer: str
    audience: str
    authorization_endpoint: str
    redirect_uri: str
    allowed_origin: str
    server_secret: bytes | None
    session_cookie_name: str = "cloud_study_session"
    idle_minutes: int = 30
    absolute_hours: int = 12

    @classmethod
    def from_environment(cls, deployment: DeploymentSettings) -> AuthenticationSettings:
        raw_mode = os.getenv("CLOUD_STUDY_AUTH_MODE", "legacy_owner").strip()
        if raw_mode not in {"legacy_owner", "synthetic_oidc", "managed_oidc"}:
            raise ValueError("CLOUD_STUDY_AUTH_MODE is invalid")
        mode: AuthenticationMode = raw_mode  # type: ignore[assignment]
        if mode == "synthetic_oidc" and deployment.mode != "local":
            raise ValueError("synthetic OIDC is restricted to local validation mode")
        issuer = os.getenv("CLOUD_STUDY_OIDC_ISSUER", "").strip().rstrip("/")
        audience = os.getenv("CLOUD_STUDY_OIDC_AUDIENCE", "").strip()
        authorization_endpoint = os.getenv("CLOUD_STUDY_OIDC_AUTHORIZATION_ENDPOINT", "").strip()
        server_secret_text = os.getenv("CLOUD_STUDY_AUTH_SECRET", "")
        redirect_uri = os.getenv(
            "CLOUD_STUDY_OIDC_REDIRECT_URI", "http://127.0.0.1:8000/auth/callback"
        ).strip()
        allowed_origin = (
            os.getenv(
                "CLOUD_STUDY_AUTH_ALLOWED_ORIGIN",
                (deployment.allowed_origin or "")
                if deployment.mode == "private_preview"
                else "http://localhost:3000",
            )
            .strip()
            .rstrip("/")
        )
        if mode == "synthetic_oidc":
            issuer = issuer or "https://synthetic-identity.invalid"
            audience = audience or "cloud-study-synthetic-client"
            authorization_endpoint = (
                authorization_endpoint or "https://synthetic-identity.invalid/authorize"
            )
        if mode == "managed_oidc" and not all(
            (
                issuer,
                audience,
                authorization_endpoint,
                redirect_uri,
                allowed_origin,
                server_secret_text,
            )
        ):
            raise ValueError("managed OIDC configuration is incomplete")
        if mode == "managed_oidc" and len(server_secret_text.encode("utf-8")) < 32:
            raise ValueError("managed OIDC authentication secret must be at least 32 bytes")
        if mode != "legacy_owner":
            for name, value in {
                "issuer": issuer,
                "authorization endpoint": authorization_endpoint,
                "redirect URI": redirect_uri,
                "allowed origin": allowed_origin,
            }.items():
                if not value.startswith("https://") and not (
                    mode == "synthetic_oidc" and value.startswith("http://127.0.0.1")
                ):
                    raise ValueError(f"authentication {name} must use HTTPS")
        return cls(
            mode=mode,
            issuer=issuer,
            audience=audience,
            authorization_endpoint=authorization_endpoint,
            redirect_uri=redirect_uri,
            allowed_origin=allowed_origin,
            server_secret=server_secret_text.encode("utf-8") or None,
        )


def find_repository_root() -> Path:
    """Return the repository root from this source checkout."""
    return Path(__file__).resolve().parents[4]


@dataclass(frozen=True, slots=True)
class Settings:
    repository_root: Path
    database_path: Path
    deployment: DeploymentSettings
    synthetic_identity_enabled: bool
    authentication: AuthenticationSettings

    @classmethod
    def from_environment(cls) -> Settings:
        repository_root = find_repository_root()
        configured_database = os.getenv("CLOUD_STUDY_DATABASE_PATH")
        database_path = (
            Path(configured_database).expanduser().resolve()
            if configured_database
            else repository_root / "apps" / "api" / "data" / "cloud-study.db"
        )
        synthetic_identity_enabled = os.getenv(
            "CLOUD_STUDY_SYNTHETIC_IDENTITY_ENABLED", "0"
        ).strip() in {"1", "true"}
        deployment = DeploymentSettings.from_environment(repository_root)
        if synthetic_identity_enabled and deployment.mode != "local":
            raise ValueError("synthetic identities are restricted to local validation mode")
        authentication = AuthenticationSettings.from_environment(deployment)
        if synthetic_identity_enabled and authentication.mode != "legacy_owner":
            raise ValueError("9B synthetic headers and 9C OIDC mode cannot be enabled together")
        return cls(
            repository_root=repository_root,
            database_path=database_path,
            deployment=deployment,
            synthetic_identity_enabled=synthetic_identity_enabled,
            authentication=authentication,
        )
