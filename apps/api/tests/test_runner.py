from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tarfile
from itertools import pairwise
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from cloud_study_api.runner import (
    DockerRunnerBackend,
    RunnerCleanupError,
    RunnerProtocolError,
    RuntimeRegistry,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _invocation(source: str = "print('ok')\n") -> dict[str, Any]:
    profile = RuntimeRegistry(REPOSITORY_ROOT).get("python-3-14-3", "1.0.0")
    return {
        "protocol_version": "1.1.0",
        "audit_id": str(uuid4()),
        "artifact_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "runtime": {
            "id": profile["id"],
            "version": profile["version"],
            "language": profile["language"],
            "platform": profile["platform"],
            "image": profile["image"],
        },
        "source": {"filename": "main.py", "content": source},
        "tests": [{"id": "smoke", "stdin": "", "expected_stdout": "ok\n"}],
        "limits": {
            "compile_wall_seconds": 15,
            "run_wall_seconds": 3,
            "compile_memory_mb": 768,
            "run_memory_mb": 256,
            "cpus": 1,
            "compile_pids": 64,
            "run_pids": 32,
            "output_bytes": 65536,
            "tmpfs_mb": 128,
        },
    }


def test_runtime_registry_locks_verified_official_images_and_d_drive() -> None:
    registry = RuntimeRegistry(REPOSITORY_ROOT)

    assert registry.registry["data_root"] == r"D:\CloudStudy\DockerData"
    assert registry.registry["disk_budget_gb"] == 6
    assert registry.get("cpp-gcc-15-2", "1.0.0")["tool_version"] == "15.2.0"
    assert registry.get("python-3-14-3", "1.0.0")["tool_version"] == "3.14.3"
    assert all("@sha256:" in profile["image"] for profile in registry.profiles.values())


def test_container_creation_has_no_host_mount_and_all_confirmed_security_limits() -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, b"container-id\n", b"")

    backend = DockerRunnerBackend(REPOSITORY_ROOT, command_runner=fake_run)
    invocation = _invocation()
    container_id = backend._create_container(
        "docker",
        "cloud-study-test",
        invocation,
        phase="run",
    )

    assert container_id == "container-id"
    command = calls[0]
    pairs = list(pairwise(command))
    assert ("--network", "none") in pairs
    assert "--read-only" in command
    assert ("--user", "65534:65534") in pairs
    assert ("--cap-drop", "ALL") in pairs
    assert ("--security-opt", "no-new-privileges=true") in pairs
    assert ("--security-opt", "seccomp=builtin") in pairs
    assert ("--pids-limit", "32") in pairs
    assert ("--memory", "256m") in pairs
    assert ("--memory-swap", "256m") in pairs
    assert ("--cpus", "1") in pairs
    assert ("--pull", "never") in pairs
    assert ("--platform", "linux/amd64") in pairs
    assert (
        "--tmpfs",
        "/tmp:rw,exec,nosuid,nodev,mode=1777,size=128m",
    ) in pairs
    assert (
        "--tmpfs",
        "/work:rw,nosuid,nodev,mode=1777,size=128m",
    ) in pairs
    assert not {"--mount", "--volume", "-v", "--privileged"} & set(command)
    assert str(REPOSITORY_ROOT) not in " ".join(command)


def test_runner_rejects_multibyte_source_over_byte_limit_before_docker() -> None:
    source = "学" * 22000
    backend = DockerRunnerBackend(REPOSITORY_ROOT)

    with pytest.raises(RunnerProtocolError, match="64 KiB"):
        backend.execute(_invocation(source))


def test_submission_streams_into_running_tmpfs_without_docker_cp() -> None:
    captured: dict[str, Any] = {}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(args, 0, b"", b"")

    backend = DockerRunnerBackend(REPOSITORY_ROOT, command_runner=fake_run)
    backend._copy_submission("docker", "container-id", {"main.py": b"print('ok')\n"})

    assert captured["args"] == [
        "docker",
        "exec",
        "-i",
        "container-id",
        "tar",
        "-x",
        "-C",
        "/tmp",
    ]
    with tarfile.open(fileobj=io.BytesIO(captured["input"]), mode="r:") as archive:
        member = archive.getmember("cloud-study/main.py")
        assert member.uid == 65534
        assert member.gid == 65534
        extracted = archive.extractfile(member)
        assert extracted is not None
        assert extracted.read() == b"print('ok')\n"


def test_runner_concurrency_one_returns_stable_infrastructure_result() -> None:
    backend = DockerRunnerBackend(REPOSITORY_ROOT)
    invocation = _invocation()
    assert backend._execution_lock.acquire(blocking=False)
    try:
        result = backend.execute(invocation)
    finally:
        backend._execution_lock.release()

    assert result["status"] == "infrastructure_error"
    assert result["failure_code"] == "runner_busy"
    assert result["tests"] == []


def test_cleanup_failure_is_never_reported_as_success() -> None:
    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(args, 1, b"", b"still present")

    backend = DockerRunnerBackend(REPOSITORY_ROOT, command_runner=fake_run)

    with pytest.raises(RunnerCleanupError, match="cleanup failed"):
        backend._remove_container("docker", "container-id")


@pytest.mark.parametrize("failing_command", ["ps", "rm"])
def test_stale_cleanup_failure_is_never_reported_as_no_leftovers(
    monkeypatch: pytest.MonkeyPatch,
    failing_command: str,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _command: "docker")

    def fake_run(args: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args[1] == "ps":
            return subprocess.CompletedProcess(
                args,
                1 if failing_command == "ps" else 0,
                b"container-id\n",
                b"listing failed" if failing_command == "ps" else b"",
            )
        return subprocess.CompletedProcess(
            args,
            1,
            b"",
            b"removal failed",
        )

    backend = DockerRunnerBackend(REPOSITORY_ROOT, command_runner=fake_run)

    with pytest.raises(RunnerCleanupError, match="stale-container"):
        backend.cleanup_stale()
