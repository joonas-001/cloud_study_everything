"""Run the opt-in live isolation matrix against the local Docker Runner.

This command executes only repository-owned probes. It is intentionally excluded
from CI and release-readiness because it requires the separately provisioned,
digest-pinned local Docker images.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from cloud_study_api.runner import DockerRunnerBackend

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIMITS = {
    "compile_wall_seconds": 15,
    "run_wall_seconds": 3,
    "compile_memory_mb": 768,
    "run_memory_mb": 256,
    "cpus": 1,
    "compile_pids": 64,
    "run_pids": 32,
    "output_bytes": 65536,
    "tmpfs_mb": 128,
}
RUNTIMES = {
    "cpp": {
        "id": "cpp-gcc-15-2",
        "version": "1.0.0",
        "language": "cpp",
        "platform": "linux/amd64",
        "image": (
            "gcc@sha256:"
            "c101370f78e4a30be178c11dd18aeee64c65d617908a98157db2392ca73ab04f"
        ),
    },
    "python": {
        "id": "python-3-14-3",
        "version": "1.0.0",
        "language": "python",
        "platform": "linux/amd64",
        "image": (
            "python@sha256:"
            "843ef86c4efef6d065c1767855730cc974e4998e66d65d6739449f0bc0ae4d93"
        ),
    },
}


def invocation(language: str, source: str, expected_stdout: str) -> dict[str, Any]:
    filename = "main.cpp" if language == "cpp" else "main.py"
    return {
        "protocol_version": "1.1.0",
        "audit_id": str(uuid4()),
        "artifact_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
        "runtime": RUNTIMES[language],
        "source": {"filename": filename, "content": source},
        "tests": [
            {
                "id": "live-probe",
                "stdin": "",
                "expected_stdout": expected_stdout,
            }
        ],
        "limits": LIMITS,
    }


def assert_case(
    backend: DockerRunnerBackend,
    *,
    name: str,
    language: str,
    source: str,
    expected_stdout: str,
    expected_status: str,
    expected_failure_code: str | None,
) -> dict[str, Any]:
    result = backend.execute(invocation(language, source, expected_stdout))
    if result["status"] != expected_status:
        raise RuntimeError(
            f"{name}: expected {expected_status}, got {result['status']}\n"
            f"{json.dumps(result, ensure_ascii=False, indent=2)}"
        )
    if result["failure_code"] != expected_failure_code:
        raise RuntimeError(
            f"{name}: expected failure {expected_failure_code}, "
            f"got {result['failure_code']}\n"
            f"{json.dumps(result, ensure_ascii=False, indent=2)}"
        )
    leftovers = backend.cleanup_stale()
    if leftovers:
        raise RuntimeError(f"{name}: Runner left containers behind: {leftovers}")
    return {
        "name": name,
        "status": result["status"],
        "failure_code": result["failure_code"],
        "security": result["security"],
    }


def main() -> int:
    backend = DockerRunnerBackend(REPOSITORY_ROOT)
    availability = backend.availability()
    if not availability["available"]:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": availability["reason_code"],
                    "availability": availability,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    stale_before = backend.cleanup_stale()
    if stale_before:
        print(f"Removed stale Runner containers before validation: {stale_before}")

    cases = [
        assert_case(
            backend,
            name="cpp-pass",
            language="cpp",
            source=(
                '#include <iostream>\nint main() { std::cout << "runner-ok\\n"; }\n'
            ),
            expected_stdout="runner-ok\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="python-pass",
            language="python",
            source="print('runner-ok')\n",
            expected_stdout="runner-ok\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="network-none",
            language="python",
            source=(
                "import socket\n"
                "try:\n"
                "    socket.create_connection(('1.1.1.1', 53), timeout=0.25)\n"
                "except OSError:\n"
                "    print('blocked')\n"
                "else:\n"
                "    print('reachable')\n"
            ),
            expected_stdout="blocked\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="read-only-root",
            language="python",
            source=(
                "try:\n"
                "    open('/cloud-study-write-probe', 'w', encoding='utf-8').write('x')\n"
                "except OSError:\n"
                "    print('blocked')\n"
                "else:\n"
                "    print('writable')\n"
            ),
            expected_stdout="blocked\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="no-host-repository-mount",
            language="python",
            source=(
                "from pathlib import Path\n"
                "print('exposed' if Path('/workspace/AGENTS.md').exists() else 'blocked')\n"
            ),
            expected_stdout="blocked\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="no-docker-socket",
            language="python",
            source=(
                "from pathlib import Path\n"
                "print('exposed' if Path('/var/run/docker.sock').exists() else 'blocked')\n"
            ),
            expected_stdout="blocked\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="process-limit",
            language="python",
            source=(
                "import subprocess\n"
                "import sys\n"
                "children = []\n"
                "try:\n"
                "    for _ in range(64):\n"
                "        children.append(subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(2)']))\n"
                "except OSError:\n"
                "    print('blocked')\n"
                "else:\n"
                "    print('unrestricted')\n"
                "finally:\n"
                "    for child in children:\n"
                "        child.terminate()\n"
                "    for child in children:\n"
                "        child.wait()\n"
            ),
            expected_stdout="blocked\n",
            expected_status="passed",
            expected_failure_code=None,
        ),
        assert_case(
            backend,
            name="wall-timeout",
            language="python",
            source="while True:\n    pass\n",
            expected_stdout="",
            expected_status="timeout",
            expected_failure_code="wall_timeout",
        ),
        assert_case(
            backend,
            name="combined-output-limit",
            language="python",
            source=(
                "import sys\n"
                "sys.stdout.write('x' * 40000)\n"
                "sys.stderr.write('y' * 40000)\n"
            ),
            expected_stdout="",
            expected_status="output_limit",
            expected_failure_code="output_limit_exceeded",
        ),
        assert_case(
            backend,
            name="memory-limit",
            language="python",
            source="payload = bytearray(512 * 1024 * 1024)\nprint(len(payload))\n",
            expected_stdout="",
            expected_status="failed",
            expected_failure_code="runtime_failed",
        ),
    ]
    print(
        json.dumps({"ok": True, "availability": availability, "cases": cases}, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
