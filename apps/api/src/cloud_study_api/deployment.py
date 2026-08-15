from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker

DeploymentMode = Literal["local", "private_preview"]

DEFAULT_POLICY_PATH = Path("deployment/policies/single-user-singapore-v1.json")
POLICY_SCHEMA_PATH = Path("contracts/deployment/private-deployment-policy.schema.json")


class DeploymentConfigurationError(RuntimeError):
    """Raised when deployment settings would weaken the confirmed boundary."""


class DeploymentCapabilityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_environment(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise DeploymentConfigurationError(f"{name} is required in private preview mode")
    return value


def _validate_owner_login(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 320 or "@" not in normalized:
        raise DeploymentConfigurationError(
            "CLOUD_STUDY_OWNER_LOGIN must be the exact Microsoft account email"
        )
    return normalized


def _validate_private_origin(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as error:
        raise DeploymentConfigurationError(
            "CLOUD_STUDY_ALLOWED_ORIGIN must be one exact https://*.ts.net origin"
        ) from error
    hostname = parsed.hostname
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
        or hostname is None
        or len(hostname) > 253
        or re.fullmatch(
            r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+ts\.net",
            hostname,
        )
        is None
    ):
        raise DeploymentConfigurationError(
            "CLOUD_STUDY_ALLOWED_ORIGIN must be one exact https://*.ts.net origin"
        )
    return f"https://{hostname}"


def load_deployment_policy(
    repository_root: Path, configured_path: str | None = None
) -> dict[str, Any]:
    policy_path = (
        Path(configured_path).expanduser().resolve()
        if configured_path
        else (repository_root / DEFAULT_POLICY_PATH).resolve()
    )
    schema_path = (repository_root / POLICY_SCHEMA_PATH).resolve()
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeploymentConfigurationError(
            "the governed deployment policy or schema could not be loaded"
        ) from error
    if not isinstance(policy, dict) or not isinstance(schema, dict):
        raise DeploymentConfigurationError("deployment policy and schema must be JSON objects")
    Draft202012Validator.check_schema(schema)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        raise DeploymentConfigurationError(
            f"deployment policy failed schema validation: {errors[0].message}"
        )
    return policy


@dataclass(frozen=True, slots=True)
class DeploymentSettings:
    mode: DeploymentMode
    policy: dict[str, Any] | None
    owner_login: str | None
    allowed_origin: str | None
    runner_socket_path: Path | None

    @classmethod
    def from_environment(cls, repository_root: Path) -> DeploymentSettings:
        raw_mode = os.getenv("CLOUD_STUDY_DEPLOYMENT_MODE", "local").strip()
        if raw_mode not in {"local", "private_preview"}:
            raise DeploymentConfigurationError(
                "CLOUD_STUDY_DEPLOYMENT_MODE must be local or private_preview"
            )
        mode = cast(DeploymentMode, raw_mode)
        if mode == "local":
            return cls(
                mode=mode,
                policy=None,
                owner_login=None,
                allowed_origin=None,
                runner_socket_path=None,
            )

        policy = load_deployment_policy(
            repository_root,
            os.getenv("CLOUD_STUDY_DEPLOYMENT_POLICY_PATH"),
        )
        if os.getenv("CLOUD_STUDY_CREDENTIAL_STORE", "").strip() != "file":
            raise DeploymentConfigurationError(
                "private preview mode requires CLOUD_STUDY_CREDENTIAL_STORE=file"
            )
        secret_directory = Path(_required_environment("CLOUD_STUDY_SECRET_DIRECTORY"))
        if not secret_directory.is_absolute():
            raise DeploymentConfigurationError(
                "CLOUD_STUDY_SECRET_DIRECTORY must be an absolute mounted path"
            )
        remote_runner_enabled = bool(policy["runner"]["remote_enabled"])
        runner_socket_path: Path | None = None
        if remote_runner_enabled:
            configured_socket = Path(_required_environment("CLOUD_STUDY_RUNNER_SOCKET"))
            if not configured_socket.is_absolute():
                raise DeploymentConfigurationError(
                    "CLOUD_STUDY_RUNNER_SOCKET must be an absolute Unix socket path"
                )
            runner_socket_path = configured_socket
        return cls(
            mode=mode,
            policy=policy,
            owner_login=_validate_owner_login(_required_environment("CLOUD_STUDY_OWNER_LOGIN")),
            allowed_origin=_validate_private_origin(
                _required_environment("CLOUD_STUDY_ALLOWED_ORIGIN")
            ),
            runner_socket_path=runner_socket_path,
        )

    @property
    def remote_runner_enabled(self) -> bool:
        return bool(self.policy and self.policy["runner"]["remote_enabled"])

    @property
    def external_calls_enabled(self) -> bool:
        return bool(self.policy and self.policy["external_calls"]["enabled_by_default"])


class DeploymentGuard:
    def __init__(self, settings: DeploymentSettings) -> None:
        self._settings = settings

    def require_remote_runner(self) -> None:
        if self._settings.mode == "private_preview" and not self._settings.remote_runner_enabled:
            raise DeploymentCapabilityError(
                "remote_runner_disabled",
                "Remote Runner is disabled for the private preview.",
            )

    def require_external_calls(self) -> None:
        if self._settings.mode == "private_preview" and not self._settings.external_calls_enabled:
            raise DeploymentCapabilityError(
                "external_calls_disabled",
                "External calls are disabled for the private preview.",
            )

    def status(self) -> dict[str, object]:
        policy = self._settings.policy
        return {
            "mode": self._settings.mode,
            "authentication_required": self._settings.mode == "private_preview",
            "identity_provider": None if policy is None else policy["identity"]["provider"],
            "owner_login_configured": self._settings.owner_login is not None,
            "region": None if policy is None else policy["platform"]["region"],
            "data_store": "sqlite",
            "remote_runner_enabled": self._settings.remote_runner_enabled,
            "external_calls_enabled": self._settings.external_calls_enabled,
            "monthly_budget_cny": None
            if policy is None
            else policy["budget"]["monthly_hard_limit"],
        }
