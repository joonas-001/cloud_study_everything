from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from cloud_study_api.config import Settings
from cloud_study_api.database import read_schema_version
from cloud_study_api.deployment import DeploymentConfigurationError
from cloud_study_api.runner import RunnerProtocolError, UnixSocketRunnerBackend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


class PreflightError(RuntimeError):
    """Raised when the private preview must not start."""


def _command_version(command: str) -> str:
    try:
        result = subprocess.run(
            [command, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise PreflightError(f"{command} version could not be verified") from error
    return (result.stdout or result.stderr).strip()


def _verify_public_key(path: Path) -> None:
    try:
        value = serialization.load_pem_public_key(path.read_bytes())
    except (OSError, ValueError, TypeError) as error:
        raise PreflightError("backup public key could not be loaded") from error
    if not isinstance(value, rsa.RSAPublicKey) or value.key_size < 3072:
        raise PreflightError("backup public key must be RSA with at least 3072 bits")


def run_preflight() -> dict[str, object]:
    if sys.version_info[:3] != (3, 14, 3):
        raise PreflightError("private preview requires Python 3.14.3 exactly")
    try:
        settings = Settings.from_environment()
    except DeploymentConfigurationError as error:
        raise PreflightError(str(error)) from error
    if settings.deployment.mode != "private_preview":
        raise PreflightError("deployment preflight requires private_preview mode")
    runner_availability: dict[str, object] | None = None
    if settings.deployment.remote_runner_enabled:
        socket_path = settings.deployment.runner_socket_path
        if socket_path is None or not socket_path.exists() or socket_path.is_symlink():
            raise PreflightError("remote Runner broker socket is unavailable")
        if os.name == "nt" or not stat.S_ISSOCK(socket_path.stat().st_mode):
            raise PreflightError("remote Runner broker path must be a Unix socket")
        docker_socket = Path("/var/run/docker.sock")
        if docker_socket.exists() and os.access(docker_socket, os.R_OK | os.W_OK):
            raise PreflightError(
                "FastAPI service identity must not access the Docker socket"
            )
        try:
            availability = UnixSocketRunnerBackend(
                socket_path, timeout_seconds=10
            ).availability()
        except RunnerProtocolError as error:
            raise PreflightError("remote Runner broker preflight failed") from error
        if not availability.get("available"):
            raise PreflightError("remote Runner broker is not ready")
        runner_availability = {
            "available": True,
            "reason_code": availability.get("reason_code"),
        }
    if settings.deployment.external_calls_enabled:
        raise PreflightError("external calls must remain disabled")

    database_path = settings.database_path
    if not database_path.is_file() or database_path.is_symlink():
        raise PreflightError("configured database must be an existing regular file")
    if read_schema_version(database_path) != "0010":
        raise PreflightError("database must be migrated to Alembic revision 0010")
    try:
        with closing(
            sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
        ) as database:
            external_ai = database.execute(
                "SELECT external_ai_enabled FROM app_settings WHERE id = 1"
            ).fetchone()
            email = database.execute(
                "SELECT email_enabled FROM notification_preferences WHERE id = 1"
            ).fetchone()
    except sqlite3.Error as error:
        raise PreflightError(
            "database external-call settings could not be verified"
        ) from error
    if external_ai is None or bool(external_ai[0]):
        raise PreflightError("external AI must be disabled before private preview")
    if email is None or bool(email[0]):
        raise PreflightError("email delivery must be disabled before private preview")

    secret_directory = Path(os.environ["CLOUD_STUDY_SECRET_DIRECTORY"]).resolve()
    if not secret_directory.is_dir() or secret_directory.is_symlink():
        raise PreflightError("secret directory must be a real directory")
    if os.name != "nt" and secret_directory.stat().st_mode & 0o077:
        raise PreflightError(
            "secret directory must not grant group or world permissions"
        )

    public_key_value = os.getenv("CLOUD_STUDY_BACKUP_PUBLIC_KEY", "").strip()
    if not public_key_value:
        raise PreflightError("CLOUD_STUDY_BACKUP_PUBLIC_KEY is required")
    public_key_path = Path(public_key_value)
    if not public_key_path.is_absolute():
        raise PreflightError("backup public key path must be absolute")
    _verify_public_key(public_key_path)

    node_command = "/usr/bin/node" if os.name != "nt" else "node"
    pnpm_command = "pnpm.cmd" if os.name == "nt" else "pnpm"
    node_version = _command_version(node_command)
    pnpm_version = _command_version(pnpm_command)
    uv_version = _command_version("uv")
    if not node_version.startswith("v24."):
        raise PreflightError("private preview requires Node.js 24")
    if not pnpm_version.startswith("11."):
        raise PreflightError("private preview requires pnpm 11")
    if not uv_version.startswith("uv 0.11."):
        raise PreflightError("private preview requires the locked uv 0.11 baseline")
    policy = settings.deployment.policy
    if policy is None:
        raise PreflightError("private preview deployment policy is unavailable")
    return {
        "ok": True,
        "mode": settings.deployment.mode,
        "region": policy["platform"]["region"],
        "database_revision": "0010",
        "remote_runner_enabled": settings.deployment.remote_runner_enabled,
        "runner_broker": runner_availability,
        "external_calls_enabled": False,
        "node": node_version,
        "node_executable": node_command,
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "pnpm": pnpm_version,
        "uv": uv_version,
        "backup_public_key_bits": 3072,
    }


def main() -> int:
    try:
        result = run_preflight()
    except (PreflightError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
