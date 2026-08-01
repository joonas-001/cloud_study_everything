from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, cast

import yaml
from jsonschema import Draft202012Validator, FormatChecker

RUNNER_PROTOCOL_VERSION = "1.1.0"
RUNNER_LABEL = "cloud-study.runner=1.1.0"
OUTPUT_LIMIT_BYTES = 65536
COMPILED_ARTIFACT_LIMIT_BYTES = 16 * 1024 * 1024


class RunnerProtocolError(RuntimeError):
    pass


class RunnerCleanupError(RunnerProtocolError):
    pass


class RunnerBackend(Protocol):
    def availability(self) -> dict[str, Any]: ...

    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]: ...

    def cleanup_stale(self) -> list[str]: ...


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


class RuntimeRegistry:
    def __init__(self, repository_root: Path) -> None:
        registry_path = repository_root / "runtimes" / "registry.yaml"
        registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        if not isinstance(registry, dict):
            raise RunnerProtocolError("runtime registry must be an object")
        schema = json.loads(
            (repository_root / "contracts" / "runner" / "runtime-registry.schema.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(registry)
        self.registry = cast(dict[str, Any], registry)
        self.profiles = {
            (profile["id"], profile["version"]): cast(dict[str, Any], profile)
            for profile in registry["profiles"]
        }

    def get(self, profile_id: str, version: str) -> dict[str, Any]:
        try:
            return self.profiles[(profile_id, version)]
        except KeyError as error:
            raise RunnerProtocolError(
                f"runtime profile is not registered: {profile_id}@{version}"
            ) from error


class DockerRunnerBackend:
    def __init__(
        self,
        repository_root: Path,
        *,
        command_runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
    ) -> None:
        self._repository_root = repository_root
        self._command_runner = command_runner
        self._registry = RuntimeRegistry(repository_root)
        self._invocation_validator = Draft202012Validator(
            json.loads(
                (
                    repository_root / "contracts" / "runner" / "invocation-v1.1.schema.json"
                ).read_text(encoding="utf-8")
            ),
            format_checker=FormatChecker(),
        )
        self._result_validator = Draft202012Validator(
            json.loads(
                (repository_root / "contracts" / "runner" / "result-v1.1.schema.json").read_text(
                    encoding="utf-8"
                )
            ),
            format_checker=FormatChecker(),
        )
        self._execution_lock = threading.Lock()

    def availability(self) -> dict[str, Any]:
        docker_path = shutil.which("docker")
        data_root = Path(cast(str, self._registry.registry["data_root"]))
        drive_root = Path(f"{data_root.drive}\\")
        free_gb: float | None = None
        used_gb: float | None = None
        if drive_root.drive:
            try:
                free_gb = round(shutil.disk_usage(drive_root).free / (1024**3), 2)
            except OSError:
                free_gb = None
        try:
            used_gb = round(self._tree_size_bytes(data_root) / (1024**3), 3)
        except OSError:
            used_gb = None
        if docker_path is None:
            return {
                "available": False,
                "reason_code": "docker_unavailable",
                "docker_path": None,
                "data_root": str(data_root),
                "free_gb": free_gb,
                "used_gb": used_gb,
            }
        result = self._command_runner(
            [docker_path, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        available = result.returncode == 0
        minimum_free = cast(int, self._registry.registry["minimum_free_gb"])
        disk_budget = cast(int, self._registry.registry["disk_budget_gb"])
        if used_gb is not None and used_gb > disk_budget:
            return {
                "available": False,
                "reason_code": "runner_disk_budget_exceeded",
                "docker_path": docker_path,
                "data_root": str(data_root),
                "free_gb": free_gb,
                "used_gb": used_gb,
            }
        if free_gb is not None and free_gb < minimum_free:
            return {
                "available": False,
                "reason_code": "runner_disk_budget_unavailable",
                "docker_path": docker_path,
                "data_root": str(data_root),
                "free_gb": free_gb,
                "used_gb": used_gb,
            }
        return {
            "available": available,
            "reason_code": None if available else "docker_daemon_unavailable",
            "docker_path": docker_path,
            "data_root": str(data_root),
            "free_gb": free_gb,
            "used_gb": used_gb,
            "server_version": (
                result.stdout.decode("utf-8", errors="replace").strip() if available else None
            ),
        }

    def cleanup_stale(self) -> list[str]:
        docker_path = shutil.which("docker")
        if docker_path is None:
            raise RunnerCleanupError("Docker is unavailable for stale-container cleanup")
        try:
            listed = self._command_runner(
                [
                    docker_path,
                    "ps",
                    "-aq",
                    "--filter",
                    f"label={RUNNER_LABEL}",
                ],
                capture_output=True,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RunnerCleanupError("Runner stale-container listing failed") from error
        if listed.returncode != 0:
            raise RunnerCleanupError("Runner stale-container listing failed")
        ids = [
            item for item in listed.stdout.decode("utf-8", errors="replace").splitlines() if item
        ]
        removed: list[str] = []
        for container_id in ids:
            try:
                result = self._command_runner(
                    [docker_path, "rm", "-f", container_id],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise RunnerCleanupError("Runner stale-container cleanup failed") from error
            if result.returncode == 0:
                removed.append(container_id)
            else:
                raise RunnerCleanupError("Runner stale-container cleanup failed")
        return removed

    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        errors = sorted(self._invocation_validator.iter_errors(invocation), key=str)
        if errors:
            raise RunnerProtocolError(errors[0].message)
        profile = self._registry.get(
            invocation["runtime"]["id"],
            invocation["runtime"]["version"],
        )
        if invocation["runtime"]["image"] != profile["image"]:
            raise RunnerProtocolError("invocation image does not match the managed runtime")
        if invocation["runtime"]["language"] != profile["language"]:
            raise RunnerProtocolError("invocation language does not match the managed runtime")
        artifact_sha256 = hashlib.sha256(
            invocation["source"]["content"].encode("utf-8")
        ).hexdigest()
        if len(invocation["source"]["content"].encode("utf-8")) > OUTPUT_LIMIT_BYTES:
            raise RunnerProtocolError("source exceeds the 64 KiB byte limit")
        for test in invocation["tests"]:
            for field in ("stdin", "expected_stdout"):
                if len(test[field].encode("utf-8")) > OUTPUT_LIMIT_BYTES:
                    raise RunnerProtocolError(f"test {field} exceeds the 64 KiB byte limit")
        if artifact_sha256 != invocation["artifact_sha256"]:
            raise RunnerProtocolError("source content does not match artifact_sha256")
        if not self._execution_lock.acquire(blocking=False):
            return self._infrastructure_result(
                invocation,
                "infrastructure_error",
                "runner_busy",
                utc_iso(),
            )
        started_at = utc_iso()
        try:
            return self._execute_locked(invocation, started_at)
        finally:
            self._execution_lock.release()

    def _execute_locked(
        self,
        invocation: dict[str, Any],
        started_at: str,
    ) -> dict[str, Any]:
        availability = self.availability()
        if not availability["available"]:
            return self._infrastructure_result(
                invocation,
                "infrastructure_error",
                cast(str, availability["reason_code"]),
                started_at,
            )
        docker_path = cast(str, availability["docker_path"])
        image = cast(str, invocation["runtime"]["image"])
        inspected = self._command_runner(
            [docker_path, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if inspected.returncode != 0:
            return self._infrastructure_result(
                invocation,
                "infrastructure_error",
                "image_unavailable",
                started_at,
            )
        observed_image_id = inspected.stdout.decode("utf-8", errors="replace").strip()
        compiled: bytes | None = None
        if invocation["runtime"]["language"] == "cpp":
            compiled, compile_result = self._compile_cpp(
                docker_path,
                invocation,
            )
            if compile_result is not None:
                result = self._result(
                    invocation,
                    "failed",
                    "compile_failed",
                    observed_image_id,
                    [compile_result],
                    started_at,
                )
                self._result_validator.validate(result)
                return result
        test_results: list[dict[str, Any]] = []
        for test in invocation["tests"]:
            test_result = self._run_test(
                docker_path,
                invocation,
                cast(dict[str, str], test),
                compiled,
            )
            test_results.append(test_result)
            if test_result["status"] in {"timeout", "output_limit"}:
                break
        status = "passed" if all(item["status"] == "passed" for item in test_results) else "failed"
        failure_code: str | None = None
        if status == "failed":
            first = next(item for item in test_results if item["status"] != "passed")
            failure_code = {
                "wrong_output": "wrong_output",
                "runtime_failed": "runtime_failed",
                "timeout": "wall_timeout",
                "output_limit": "output_limit_exceeded",
            }[first["status"]]
            if first["status"] == "timeout":
                status = "timeout"
            if first["status"] == "output_limit":
                status = "output_limit"
        result = self._result(
            invocation,
            status,
            failure_code,
            observed_image_id,
            test_results,
            started_at,
        )
        self._result_validator.validate(result)
        return result

    def _compile_cpp(
        self,
        docker_path: str,
        invocation: dict[str, Any],
    ) -> tuple[bytes | None, dict[str, Any] | None]:
        audit_id = cast(str, invocation["audit_id"])
        name = f"cloud-study-{audit_id[:8]}-compile"
        command = [
            "/usr/local/bin/g++",
            "-std=c++20",
            "-O2",
            "-pipe",
            "-Wall",
            "-Wextra",
            "-pedantic",
            "/tmp/cloud-study/main.cpp",
            "-o",
            "/work/main",
        ]
        container_id = self._create_container(
            docker_path,
            name,
            invocation,
            phase="compile",
        )
        started = time.monotonic()
        try:
            self._start_container(docker_path, container_id)
            self._copy_submission(
                docker_path,
                container_id,
                {"main.cpp": invocation["source"]["content"].encode("utf-8")},
            )
            attached = self._exec_capped(
                docker_path,
                container_id,
                command,
                timeout_seconds=cast(int, invocation["limits"]["compile_wall_seconds"]),
            )
            duration_ms = round((time.monotonic() - started) * 1000)
            if attached["timed_out"]:
                return None, self._test_result(
                    "compile",
                    "timeout",
                    None,
                    attached,
                    duration_ms,
                )
            if attached["output_truncated"]:
                return None, self._test_result(
                    "compile",
                    "output_limit",
                    attached["exit_code"],
                    attached,
                    duration_ms,
                )
            if attached["exit_code"] != 0:
                return None, self._test_result(
                    "compile",
                    "compile_failed",
                    attached["exit_code"],
                    attached,
                    duration_ms,
                )
            copied = self._command_runner(
                [
                    docker_path,
                    "exec",
                    container_id,
                    "tar",
                    "-c",
                    "-C",
                    "/work",
                    "main",
                ],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if copied.returncode != 0 or len(copied.stdout) > COMPILED_ARTIFACT_LIMIT_BYTES:
                return None, self._test_result(
                    "compile",
                    "compile_failed",
                    copied.returncode,
                    {
                        "stdout": b"",
                        "stderr": copied.stderr,
                        "output_truncated": False,
                    },
                    duration_ms,
                )
            with tarfile.open(fileobj=io.BytesIO(copied.stdout), mode="r:*") as archive:
                member = next(item for item in archive.getmembers() if item.isfile())
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RunnerProtocolError("compiled artifact archive is empty")
                return extracted.read(), None
        finally:
            self._remove_container(docker_path, container_id)

    def _run_test(
        self,
        docker_path: str,
        invocation: dict[str, Any],
        test: dict[str, str],
        compiled: bytes | None,
    ) -> dict[str, Any]:
        audit_id = cast(str, invocation["audit_id"])
        name = f"cloud-study-{audit_id[:8]}-{test['id'][:20]}"
        language = invocation["runtime"]["language"]
        command = (
            [
                "/bin/sh",
                "-c",
                "exec /tmp/cloud-study/main < /tmp/cloud-study/input.txt",
            ]
            if language == "cpp"
            else [
                "/bin/sh",
                "-c",
                "exec /usr/local/bin/python -I -B /tmp/cloud-study/main.py "
                "< /tmp/cloud-study/input.txt",
            ]
        )
        files = {"input.txt": test["stdin"].encode("utf-8")}
        if language == "cpp":
            if compiled is None:
                raise RunnerProtocolError("compiled C++ artifact is missing")
            files["main"] = compiled
        else:
            files["main.py"] = invocation["source"]["content"].encode("utf-8")
        container_id = self._create_container(
            docker_path,
            name,
            invocation,
            phase="run",
        )
        started = time.monotonic()
        try:
            self._start_container(docker_path, container_id)
            self._copy_submission(docker_path, container_id, files)
            attached = self._exec_capped(
                docker_path,
                container_id,
                command,
                timeout_seconds=cast(int, invocation["limits"]["run_wall_seconds"]),
            )
            duration_ms = round((time.monotonic() - started) * 1000)
            if attached["timed_out"]:
                status = "timeout"
            elif attached["output_truncated"]:
                status = "output_limit"
            elif attached["exit_code"] != 0:
                status = "runtime_failed"
            elif self._normalize_output(attached["stdout"]) != self._normalize_output(
                test["expected_stdout"].encode("utf-8")
            ):
                status = "wrong_output"
            else:
                status = "passed"
            return self._test_result(
                test["id"],
                status,
                attached["exit_code"],
                attached,
                duration_ms,
            )
        finally:
            self._remove_container(docker_path, container_id)

    def _create_container(
        self,
        docker_path: str,
        name: str,
        invocation: dict[str, Any],
        *,
        phase: str,
    ) -> str:
        limits = invocation["limits"]
        memory = limits["compile_memory_mb"] if phase == "compile" else limits["run_memory_mb"]
        pids = limits["compile_pids"] if phase == "compile" else limits["run_pids"]
        args = [
            docker_path,
            "create",
            "--name",
            name,
            "--label",
            RUNNER_LABEL,
            "--label",
            f"cloud-study.audit-id={invocation['audit_id']}",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,exec,nosuid,nodev,mode=1777,size={limits['tmpfs_mb']}m",
            "--tmpfs",
            f"/work:rw,nosuid,nodev,mode=1777,size={limits['tmpfs_mb']}m",
            "--user",
            "65534:65534",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--security-opt",
            "seccomp=builtin",
            "--pids-limit",
            str(pids),
            "--memory",
            f"{memory}m",
            "--memory-swap",
            f"{memory}m",
            "--cpus",
            str(limits["cpus"]),
            "--pull",
            "never",
            "--platform",
            invocation["runtime"]["platform"],
            "--workdir",
            "/work",
            invocation["runtime"]["image"],
            "/bin/sh",
            "-c",
            "while :; do sleep 3600; done",
        ]
        created = self._command_runner(
            args,
            capture_output=True,
            check=False,
            timeout=15,
        )
        if created.returncode != 0:
            raise RunnerProtocolError(created.stderr.decode("utf-8", errors="replace")[:1000])
        return created.stdout.decode("utf-8", errors="replace").strip()

    def _copy_submission(
        self,
        docker_path: str,
        container_id: str,
        files: dict[str, bytes],
    ) -> None:
        archive_bytes = io.BytesIO()
        with tarfile.open(fileobj=archive_bytes, mode="w") as archive:
            for filename, content in files.items():
                info = tarfile.TarInfo(name=f"cloud-study/{filename}")
                info.size = len(content)
                info.mode = 0o555 if filename == "main" else 0o444
                info.uid = 65534
                info.gid = 65534
                archive.addfile(info, io.BytesIO(content))
        copied = self._command_runner(
            [
                docker_path,
                "exec",
                "-i",
                container_id,
                "tar",
                "-x",
                "-C",
                "/tmp",
            ],
            input=archive_bytes.getvalue(),
            capture_output=True,
            check=False,
            timeout=10,
        )
        if copied.returncode != 0:
            raise RunnerProtocolError(copied.stderr.decode("utf-8", errors="replace")[:1000])

    def _start_container(self, docker_path: str, container_id: str) -> None:
        started = self._command_runner(
            [docker_path, "start", container_id],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if started.returncode != 0:
            raise RunnerProtocolError(started.stderr.decode("utf-8", errors="replace")[:1000])

    def _exec_capped(
        self,
        docker_path: str,
        container_id: str,
        execution_command: list[str],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        command = [docker_path, "exec", container_id, *execution_command]
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        output_lock = threading.Lock()
        output_limit_reached = threading.Event()

        def read_stream(stream: Any, target: bytearray) -> None:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    return
                with output_lock:
                    remaining = OUTPUT_LIMIT_BYTES - len(stdout_buffer) - len(stderr_buffer)
                    if remaining > 0:
                        target.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        output_limit_reached.set()

        stdout_thread = threading.Thread(
            target=read_stream,
            args=(process.stdout, stdout_buffer),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=read_stream,
            args=(process.stderr, stderr_buffer),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        while process.poll() is None:
            if output_limit_reached.is_set():
                self._command_runner(
                    [docker_path, "kill", container_id],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                break
            if time.monotonic() >= deadline:
                timed_out = True
                self._command_runner(
                    [docker_path, "kill", container_id],
                    capture_output=True,
                    check=False,
                    timeout=10,
                )
                break
            time.sleep(0.01)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        stdout_thread.join(timeout=1)
        stderr_thread.join(timeout=1)
        return {
            "exit_code": process.returncode,
            "stdout": bytes(stdout_buffer),
            "stderr": bytes(stderr_buffer),
            "output_truncated": output_limit_reached.is_set(),
            "timed_out": timed_out,
        }

    def _remove_container(self, docker_path: str, container_id: str) -> None:
        removed = self._command_runner(
            [docker_path, "rm", "-f", container_id],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if removed.returncode != 0:
            raise RunnerCleanupError("Runner container cleanup failed")

    def _test_result(
        self,
        test_id: str,
        status: str,
        exit_code: int | None,
        attached: dict[str, Any],
        duration_ms: int,
    ) -> dict[str, Any]:
        return {
            "id": test_id,
            "status": status,
            "exit_code": exit_code,
            "stdout": cast(bytes, attached["stdout"]).decode("utf-8", errors="replace"),
            "stderr": cast(bytes, attached["stderr"]).decode("utf-8", errors="replace"),
            "output_truncated": bool(attached["output_truncated"]),
            "duration_ms": duration_ms,
        }

    def _result(
        self,
        invocation: dict[str, Any],
        status: str,
        failure_code: str | None,
        observed_image_id: str | None,
        tests: list[dict[str, Any]],
        started_at: str,
    ) -> dict[str, Any]:
        return {
            "protocol_version": RUNNER_PROTOCOL_VERSION,
            "audit_id": invocation["audit_id"],
            "artifact_sha256": invocation["artifact_sha256"],
            "status": status,
            "failure_code": failure_code,
            "runtime": {
                "id": invocation["runtime"]["id"],
                "version": invocation["runtime"]["version"],
                "image": invocation["runtime"]["image"],
                "observed_image_id": observed_image_id,
            },
            "tests": tests,
            "security": {
                "network": "none",
                "root_filesystem": "read_only",
                "user": "65534:65534",
                "capabilities": "dropped_all",
                "no_new_privileges": True,
                "seccomp": "builtin",
                "host_mounts": "none",
                "docker_socket": "not_mounted",
                "pull_policy": "never",
            },
            "started_at": started_at,
            "finished_at": utc_iso(),
        }

    def _infrastructure_result(
        self,
        invocation: dict[str, Any],
        status: str,
        failure_code: str,
        started_at: str,
    ) -> dict[str, Any]:
        result = self._result(
            invocation,
            status,
            failure_code,
            None,
            [],
            started_at,
        )
        self._result_validator.validate(result)
        return result

    @staticmethod
    def _normalize_output(value: bytes) -> str:
        return value.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip()

    @staticmethod
    def _tree_size_bytes(root: Path) -> int:
        if not root.exists():
            return 0
        if root.is_file():
            return root.stat().st_size
        total = 0
        for item in root.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
        return total
