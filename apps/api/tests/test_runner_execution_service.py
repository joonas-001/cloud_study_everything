from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import (
    create_database_engine,
    create_database_url,
    create_session_factory,
    read_schema_version,
    upgrade_database,
)
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.execution import LearningExecutionError, LearningExecutionService
from cloud_study_api.governance import validate_repository
from cloud_study_api.learning import LearningService
from cloud_study_api.models import RunnerInvocation
from cloud_study_api.notifications import NotificationService
from cloud_study_api.runner import RunnerCleanupError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]

CPP_SOURCE = """#include <iostream>
#include <vector>
int main() {
  int n; if (!(std::cin >> n)) return 1;
  if (n == 0) { std::cout << "EMPTY\\n"; return 0; }
  std::vector<long long> a(n);
  for (auto &x : a) std::cin >> x;
  int best = 0;
  for (int i = 1; i < n; ++i) if (a[i] > a[best]) best = i;
  std::cout << a[best] << ' ' << best << '\\n';
}
"""
PYTHON_SOURCE = """import sys
data = list(map(int, sys.stdin.read().split()))
n = data[0]
if n == 0:
    print("EMPTY")
else:
    values = data[1:1+n]
    best = max(range(n), key=values.__getitem__)
    print(values[best], best)
"""


class FakeRunnerBackend:
    def __init__(self, status: str = "passed") -> None:
        self.status = status
        self.invocations: list[dict[str, Any]] = []
        self.cleanup_fails = False

    def availability(self) -> dict[str, Any]:
        return {
            "available": self.status != "infrastructure_error",
            "reason_code": (
                "docker_unavailable" if self.status == "infrastructure_error" else None
            ),
            "docker_path": "docker",
            "data_root": r"D:\CloudStudy\DockerData",
            "free_gb": 100.0,
            "used_gb": 1.0,
        }

    def cleanup_stale(self) -> list[str]:
        if self.cleanup_fails:
            raise RunnerCleanupError("stale cleanup failed")
        return []

    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(invocation)
        status = self.status
        failure_code = None
        tests: list[dict[str, Any]] = []
        if status == "passed":
            tests = [
                {
                    "id": test["id"],
                    "status": "passed",
                    "exit_code": 0,
                    "stdout": test["expected_stdout"],
                    "stderr": "",
                    "output_truncated": False,
                    "duration_ms": 5,
                }
                for test in invocation["tests"]
            ]
        elif status == "failed":
            failure_code = "wrong_output"
            tests = [
                {
                    "id": invocation["tests"][0]["id"],
                    "status": "wrong_output",
                    "exit_code": 0,
                    "stdout": "wrong\n",
                    "stderr": "",
                    "output_truncated": False,
                    "duration_ms": 5,
                }
            ]
        else:
            failure_code = "docker_unavailable"
        now = datetime.now(UTC).isoformat()
        return {
            "protocol_version": "1.1.0",
            "audit_id": invocation["audit_id"],
            "artifact_sha256": invocation["artifact_sha256"],
            "status": status,
            "failure_code": failure_code,
            "runtime": {
                "id": invocation["runtime"]["id"],
                "version": invocation["runtime"]["version"],
                "image": invocation["runtime"]["image"],
                "observed_image_id": (
                    "sha256:" + invocation["runtime"]["image"].rsplit("@sha256:", maxsplit=1)[1]
                    if status != "infrastructure_error"
                    else None
                ),
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
            "started_at": now,
            "finished_at": now,
        }


class TamperedRunnerBackend(FakeRunnerBackend):
    def __init__(self, tamper: str) -> None:
        super().__init__("passed")
        self.tamper = tamper

    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        result = super().execute(invocation)
        if self.tamper == "wrong-digest":
            result["runtime"]["observed_image_id"] = "sha256:" + "0" * 64
        elif self.tamper == "missing-test":
            result["tests"].pop()
        elif self.tamper == "wrong-output":
            result["tests"][0]["stdout"] = "wrong\n"
        elif self.tamper == "unsafe-security":
            result["security"]["network"] = "bridge"
        else:
            raise AssertionError(f"unsupported tamper mode: {self.tamper}")
        return result


def _migration_config(database_path: Path) -> Config:
    config = Config(str(REPOSITORY_ROOT / "apps" / "api" / "alembic.ini"))
    config.set_main_option(
        "script_location",
        str(REPOSITORY_ROOT / "apps" / "api" / "migrations"),
    )
    config.set_main_option(
        "sqlalchemy.url",
        create_database_url(database_path).replace("%", "%%"),
    )
    return config


def _services(
    tmp_path: Path,
    clock: list[datetime],
    backend: FakeRunnerBackend,
) -> tuple[DiagnosticService, LearningService, LearningExecutionService]:
    database_path = tmp_path / "runner-execution.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    packages = validate_repository(REPOSITORY_ROOT)
    diagnostics = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        now=lambda: clock[0],
    )
    notifications = NotificationService(
        session_factory=session_factory,
        credential_store=MemoryCredentialStore(),
        now=lambda: clock[0],
    )
    learning = LearningService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        notification_service=notifications,
        now=lambda: clock[0],
    )
    execution = LearningExecutionService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        runner_backend=backend,
        now=lambda: clock[0],
    )
    return diagnostics, learning, execution


def _create_run(
    diagnostics: DiagnosticService,
    learning: LearningService,
    execution: LearningExecutionService,
) -> dict[str, Any]:
    diagnostic = diagnostics.create_session(
        skill_id="algorithm",
        skill_version="0.2.1",
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )
    diagnostics.end_session(diagnostic["id"])
    proposal = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )
    saved = learning.set_proposal_status(proposal["id"], "saved_preview")
    return execution.create_run(
        planning_proposal_id=saved["id"],
        preview=True,
        code_execution=True,
        external_ai=False,
        confirm_historical_plan=True,
        reuse_from_run_id=None,
        confirm_reuse=False,
    )


def _submission(activity: dict[str, Any]) -> dict[str, str]:
    accepted = {
        "programming-check": "check-empty-first",
        "complexity-check": "n-nlogn-n2",
        "structure-check": "dynamic-array",
        "checkpoint-correction": "linked-list-needs-traversal",
    }
    template_id = activity["template_activity_id"].split(":", maxsplit=1)[0]
    result: dict[str, str] = {}
    for field in activity["submission_fields"]:
        if field["kind"] == "confirmation":
            result[field["id"]] = "true"
        elif field["kind"] == "choice":
            result[field["id"]] = accepted.get(template_id, field["options"][0])
        elif field["kind"] == "code":
            runner_task_id = activity["runner_task_id"] or ""
            result[field["id"]] = PYTHON_SOURCE if "python" in runner_task_id else CPP_SOURCE
        else:
            result[field["id"]] = "证" * field["min_length"]
    return result


def _advance_to_runner(
    execution: LearningExecutionService,
    run_id: str,
    task_id: str,
) -> dict[str, Any]:
    for _ in range(40):
        run = execution.get_run(run_id)
        activity = next(
            (
                item
                for item in run["activities"]
                if item["status"] == "available" and item["type"] != "review"
            ),
            None,
        )
        assert activity is not None
        if activity["runner_task_id"] == task_id:
            return activity
        execution.submit_attempt(activity["id"], submission=_submission(activity))
    raise AssertionError(f"Runner task {task_id} did not become available")


def _submit_and_execute(
    execution: LearningExecutionService,
    activity: dict[str, Any],
) -> dict[str, Any]:
    submitted = execution.submit_attempt(
        activity["id"],
        submission=_submission(activity),
    )
    return execution.execute_attempt(submitted["attempt"]["id"])


def test_runner_pass_creates_only_scoped_verified_evidence(tmp_path: Path) -> None:
    backend = FakeRunnerBackend("passed")
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    run = _create_run(diagnostics, learning, execution)
    activity = _advance_to_runner(execution, run["id"], "max-index-cpp-v1")

    result = _submit_and_execute(execution, activity)
    evidence = execution.get_evidence(run["id"])
    operation = next(item for item in evidence["dimensions"] if item["dimension"] == "operation")

    assert result["invocation"]["status"] == "passed"
    assert result["activity"]["status"] == "completed"
    assert operation["evidence_level"] == "verified"
    assert result["run"]["status"] == "active"
    assert backend.invocations[0]["runtime"]["id"] == "cpp-gcc-15-2"
    assert backend.invocations[0]["limits"]["run_wall_seconds"] == 3
    assert "scope_criteria_met" not in result["run"]
    assert "mastered" not in result["run"]
    assert all("代码文本未执行" not in item for item in evidence["limitations"])
    assert any("锁定 Runner" in item for item in evidence["limitations"])
    assert any("5C 门禁解除" in item for item in evidence["limitations"])


@pytest.mark.parametrize(
    "tamper",
    ["wrong-digest", "missing-test", "wrong-output", "unsafe-security"],
)
def test_untrusted_runner_pass_is_cross_checked_before_evidence(
    tmp_path: Path,
    tamper: str,
) -> None:
    backend = TamperedRunnerBackend(tamper)
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    run = _create_run(diagnostics, learning, execution)
    activity = _advance_to_runner(execution, run["id"], "max-index-cpp-v1")

    result = _submit_and_execute(execution, activity)
    evidence = execution.get_evidence(run["id"])

    assert result["invocation"]["status"] == "infrastructure_error"
    assert result["invocation"]["failure_code"] == "protocol_invalid"
    assert result["activity"]["status"] == "available"
    assert all(
        item["evidence_level"] not in {"verified", "retained"} for item in evidence["dimensions"]
    )


@pytest.mark.parametrize(
    ("backend_status", "expected_activity_status"),
    [("failed", "correction_required"), ("infrastructure_error", "available")],
)
def test_runner_failure_never_creates_verified_evidence(
    tmp_path: Path,
    backend_status: str,
    expected_activity_status: str,
) -> None:
    backend = FakeRunnerBackend(backend_status)
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    run = _create_run(diagnostics, learning, execution)
    activity = _advance_to_runner(execution, run["id"], "max-index-cpp-v1")

    result = _submit_and_execute(execution, activity)
    evidence = execution.get_evidence(run["id"])

    assert result["activity"]["status"] == expected_activity_status
    assert result["invocation"]["status"] == backend_status
    assert all(
        item["evidence_level"] not in {"verified", "retained"} for item in evidence["dimensions"]
    )


def test_delayed_runner_retest_is_required_for_retained_evidence(tmp_path: Path) -> None:
    backend = FakeRunnerBackend("passed")
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    run = _create_run(diagnostics, learning, execution)

    for task_id in ("max-index-cpp-v1", "max-index-python-v1"):
        activity = _advance_to_runner(execution, run["id"], task_id)
        _submit_and_execute(execution, activity)
    for _ in range(40):
        current = execution.get_run(run["id"])
        if current["status"] == "retention_pending":
            break
        activity = next(
            item
            for item in current["activities"]
            if item["status"] == "available" and item["type"] != "review"
        )
        execution.submit_attempt(activity["id"], submission=_submission(activity))
    else:
        raise AssertionError("initial learning did not reach retention_pending")

    before = execution.get_evidence(run["id"])
    retention_before = next(
        item for item in before["dimensions"] if item["dimension"] == "retention"
    )
    assert retention_before["evidence_level"] != "retained"

    clock[0] += timedelta(days=1)
    review = execution.get_reviews(run["id"])[0]
    started = execution.start_review(review["id"])
    result = _submit_and_execute(execution, started["activity"])
    after = execution.get_evidence(run["id"])
    retention_after = next(item for item in after["dimensions"] if item["dimension"] == "retention")

    assert result["invocation"]["status"] == "passed"
    assert retention_after["evidence_level"] == "retained"
    assert result["run"]["status"] == "retention_pending"
    assert len(result["run"]["reviews"]) == 2


def test_new_runner_package_requires_explicit_code_execution_confirmation(
    tmp_path: Path,
) -> None:
    backend = FakeRunnerBackend("passed")
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    diagnostic = diagnostics.create_session(
        skill_id="algorithm",
        skill_version="0.2.1",
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )
    diagnostics.end_session(diagnostic["id"])
    proposal = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )
    saved = learning.set_proposal_status(proposal["id"], "saved_preview")

    with pytest.raises(LearningExecutionError) as error:
        execution.create_run(
            planning_proposal_id=saved["id"],
            preview=True,
            code_execution=False,
            external_ai=False,
            confirm_historical_plan=True,
            reuse_from_run_id=None,
            confirm_reuse=False,
        )

    assert error.value.code == "code_execution_confirmation_required"


def test_stale_invocation_remains_active_until_container_cleanup_succeeds(
    tmp_path: Path,
) -> None:
    backend = FakeRunnerBackend("passed")
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    run = _create_run(diagnostics, learning, execution)
    activity = _advance_to_runner(execution, run["id"], "max-index-cpp-v1")
    submitted = execution.submit_attempt(
        activity["id"],
        submission=_submission(activity),
    )
    invocation_id = str(uuid4())
    with execution._session_factory() as database:
        database.add(
            RunnerInvocation(
                id=invocation_id,
                singleton_key=1,
                run_id=run["id"],
                activity_id=activity["id"],
                attempt_id=submitted["attempt"]["id"],
                protocol_version="1.1.0",
                task_id="max-index-cpp-v1",
                runtime_profile_id="cpp-gcc-15-2",
                runtime_profile_version="1.0.0",
                runtime_image=(
                    "gcc@sha256:c101370f78e4a30be178c11dd18aeee64c65d617908a98157db2392ca73ab04f"
                ),
                artifact_sha256="1" * 64,
                request_sha256="2" * 64,
                status="running",
                created_at=clock[0],
                started_at=clock[0],
            )
        )
        database.commit()

    backend.cleanup_fails = True
    with pytest.raises(RunnerCleanupError, match="stale cleanup failed"):
        execution.recover_stale_runner_invocations()
    with execution._session_factory() as database:
        record = database.scalar(
            select(RunnerInvocation).where(RunnerInvocation.id == invocation_id)
        )
        assert record is not None
        assert record.status == "running"

    backend.cleanup_fails = False
    assert execution.recover_stale_runner_invocations() == 1
    with execution._session_factory() as database:
        record = database.scalar(
            select(RunnerInvocation).where(RunnerInvocation.id == invocation_id)
        )
        assert record is not None
        assert record.status == "infrastructure_error"
        assert record.failure_code == "cleanup_failed"


def test_runner_migration_downgrade_removes_strong_evidence_without_inventing_support(
    tmp_path: Path,
) -> None:
    backend = FakeRunnerBackend("passed")
    clock = [datetime(2026, 8, 1, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock, backend)
    run = _create_run(diagnostics, learning, execution)
    activity = _advance_to_runner(execution, run["id"], "max-index-cpp-v1")
    _submit_and_execute(execution, activity)
    before = execution.get_evidence(run["id"])
    operation_before = next(
        item for item in before["dimensions"] if item["dimension"] == "operation"
    )
    assert operation_before["evidence_level"] == "verified"

    database_path = tmp_path / "runner-execution.db"
    bind = execution._session_factory.kw["bind"]
    bind.dispose()
    config = _migration_config(database_path)
    command.downgrade(config, "0008")

    assert read_schema_version(database_path) == "0008"
    engine = create_database_engine(database_path)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'runner_invocations'"
                    )
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text("SELECT COUNT(*) FROM activity_evaluations WHERE method = 'runner'")
                ).scalar_one()
                == 0
            )
            assert (
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM mastery_evidence "
                        "WHERE strength IN ('verified', 'retained')"
                    )
                ).scalar_one()
                == 0
            )
            snapshot = connection.execute(
                text(
                    "SELECT evidence_level, evidence_count FROM mastery_snapshots "
                    "WHERE run_id = :run_id AND dimension = 'operation'"
                ),
                {"run_id": run["id"]},
            ).one()
            assert snapshot == ("none", 0)
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    assert read_schema_version(database_path) == "0009"
