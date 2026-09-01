from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.execution import LearningExecutionError, LearningExecutionService
from cloud_study_api.governance import validate_repository
from cloud_study_api.learning import LearningService
from cloud_study_api.main import app
from cloud_study_api.models import LearningRun
from cloud_study_api.notifications import NotificationService
from cloud_study_api.runner import RunnerBackend

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class PassingRunnerBackend(RunnerBackend):
    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        image = invocation["runtime"]["image"]
        observed = "sha256:" + image.rsplit("@sha256:", maxsplit=1)[1]
        return {
            "protocol_version": invocation["protocol_version"],
            "audit_id": invocation["audit_id"],
            "artifact_sha256": invocation["artifact_sha256"],
            "status": "passed",
            "failure_code": None,
            "runtime": {
                "id": invocation["runtime"]["id"],
                "version": invocation["runtime"]["version"],
                "image": invocation["runtime"]["image"],
                "observed_image_id": observed,
            },
            "tests": [
                {
                    "id": item["id"],
                    "status": "passed",
                    "exit_code": 0,
                    "stdout": item["expected_stdout"],
                    "stderr": "",
                    "output_truncated": False,
                    "duration_ms": 5,
                }
                for item in invocation["tests"]
            ],
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
            "started_at": datetime.now(UTC).isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
        }


def _services(
    tmp_path: Path,
    clock: list[datetime],
) -> tuple[DiagnosticService, LearningService, LearningExecutionService]:
    database_path = tmp_path / "milestone-8d.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    packages = [
        replace(package, intake="open") if package.version == "0.3.0" else package
        for package in validate_repository(REPOSITORY_ROOT)
    ]
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
        notification_service=notifications,
        runner_backend=PassingRunnerBackend(),
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
        skill_version="0.3.0",
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
    values: dict[str, str] = {}
    deterministic = {
        item["field_id"]: item["accepted_values"][0]
        for item in [activity.get("deterministic_check")]
        if item
    }
    for field in activity["submission_fields"]:
        if field["id"] in deterministic:
            values[field["id"]] = deterministic[field["id"]]
        elif field["kind"] == "confirmation":
            values[field["id"]] = "true"
        elif field["kind"] == "choice":
            values[field["id"]] = field["options"][0]
        elif field["kind"] == "code":
            values[field["id"]] = "int main(){return 0;}"
        else:
            values[field["id"]] = "证" * max(20, field["min_length"])
    return values


def test_common_core_daily_budget_pause_stage_and_scoped_gate(tmp_path: Path) -> None:
    clock = [datetime(2026, 8, 30, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock)
    run = _create_run(diagnostics, learning, execution)

    assert run["engine_protocol_version"] == "0.4.0"
    assert run["skill_version"] == "0.3.0"
    assert any(item["capability_ids"] for item in run["activities"])

    with pytest.raises(LearningExecutionError) as overtime:
        execution.today(run["id"], 121)
    assert overtime.value.code == "daily_overtime_confirmation_required"

    today = execution.today(
        run["id"],
        121,
        allow_overtime=True,
        overtime_reason="今天明确增加一分钟完成当前检查",
    )
    assert today["overtime"] is True
    assert today["estimated_minutes"] <= 121
    assert today["deferred_tasks"]
    assert all(item["meaning"].endswith("不记为能力失败。") for item in today["deferred_tasks"])

    paused = execution.pause_run(run["id"], "今天临时中断")
    assert paused["status"] == "paused"
    assert execution.today(run["id"], 120)["tasks"] == []
    resumed = execution.resume_run(run["id"])
    assert resumed["status"] == "active"

    checkpoints = execution.get_stage_checkpoints(run["id"])
    assert len(checkpoints) == 12
    assert checkpoints[0]["status"] == "in_progress"
    assert all("不表示" in item["meaning"] for item in checkpoints)

    structured = next(
        item
        for item in resumed["activities"]
        if item["template_activity_id"] == "p-structured-check"
    )
    execution.submit_attempt(structured["id"], submission={"result": "checked"})
    scoped = execution.get_evidence(run["id"])["evidence"]
    supported = next(item for item in scoped if item["strength"] == "supported")
    assert "p-control-flow" in supported["capability_ids"]
    assert supported["language"] == "none"

    with pytest.raises(LearningExecutionError) as future_review:
        execution.add_independent_review(
            run["id"],
            activity_id=structured["id"],
            capability_ids=["p-control-flow"],
            dimension="understanding",
            reviewer_relationship="同事",
            rubric_id="understanding-rubric",
            rubric_version="1.0.0",
            conclusion="meets",
            reviewed_at=clock[0] + timedelta(seconds=1),
        )
    assert future_review.value.code == "independent_review_future_dated"

    with pytest.raises(LearningExecutionError) as blank_relationship:
        execution.add_independent_review(
            run["id"],
            activity_id=structured["id"],
            capability_ids=["p-control-flow"],
            dimension="understanding",
            reviewer_relationship="   ",
            rubric_id="understanding-rubric",
            rubric_version="1.0.0",
            conclusion="meets",
            reviewed_at=clock[0],
        )
    assert blank_relationship.value.code == "independent_review_relationship_required"

    review = execution.add_independent_review(
        run["id"],
        activity_id=structured["id"],
        capability_ids=["p-control-flow"],
        dimension="understanding",
        reviewer_relationship="同事",
        rubric_id="understanding-rubric",
        rubric_version="1.0.0",
        conclusion="meets",
        reviewed_at=clock[0],
    )
    assert review["expires_at"] == clock[0] + timedelta(days=90)
    assert review["attachments_stored"] is False

    gate_result = execution.get_branch_gates(run["id"])
    assert gate_result["selected_branch_id"] is None
    assert len(gate_result["gates"]) == 4
    assert all(item["status"] == "blocked" for item in gate_result["gates"])
    assert all(
        "source_review_pending" in item["blocking_review_flags"] for item in gate_result["gates"]
    )


def test_delayed_same_scope_runner_pass_is_the_only_retained_path(tmp_path: Path) -> None:
    clock = [datetime(2026, 8, 30, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock)
    run = _create_run(diagnostics, learning, execution)
    runner = next(
        item for item in run["activities"] if item["template_activity_id"] == "p-runner-cpp"
    )
    submitted = execution.submit_attempt(runner["id"], submission={"source": "int main(){}"})
    executed = execution.execute_attempt(submitted["attempt"]["id"])
    assert executed["invocation"]["status"] == "passed"
    initial = execution.get_evidence(run["id"])["evidence"]
    assert any(item["strength"] == "verified" for item in initial)
    assert all(item["strength"] != "retained" for item in initial)

    with execution._session_factory() as database:
        stored_run = database.get(LearningRun, run["id"])
        assert stored_run is not None
        stored_run.status = "retention_pending"
        stored_run.retention_started_at = clock[0]
        execution._schedule_review(
            database,
            stored_run,
            checkpoint_index=1,
            attempt_number=1,
            now=clock[0],
        )
        database.commit()

    clock[0] += timedelta(days=1)
    refreshed = execution.get_run(run["id"])
    replay = next(
        item
        for item in refreshed["activities"]
        if "runner_retention" in item["activity_roles"]
        and item["template_activity_id"].startswith("p-runner-cpp:retention:")
    )
    today = execution.today(run["id"], 120)
    assert today["tasks"][0]["daily_priority"] == "due_retention"
    replay_submission = execution.submit_attempt(
        replay["id"], submission={"source": "int main(){}"}
    )
    execution.execute_attempt(replay_submission["attempt"]["id"])
    evidence = execution.get_evidence(run["id"])["evidence"]
    retained = next(item for item in evidence if item["strength"] == "retained")
    assert retained["dimension"] == "retention"
    assert retained["capability_ids"] == ["p-control-flow"]
    assert retained["language"] == "cpp"


def test_milestone_8d_routes_preserve_confirmation_pause_and_gate_contracts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    clock = [datetime(2026, 8, 30, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock)
    run = _create_run(diagnostics, learning, execution)
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(tmp_path / "route-api.db"))

    with TestClient(app) as client:
        app.state.diagnostic_service = diagnostics
        app.state.learning_service = learning
        app.state.learning_execution_service = execution

        rejected = client.post(
            f"/learning-runs/{run['id']}/today",
            json={"available_minutes": 121},
        )
        assert rejected.status_code == 422
        assert rejected.json()["detail"]["code"] == "daily_overtime_confirmation_required"

        today = client.post(
            f"/learning-runs/{run['id']}/today",
            json={
                "available_minutes": 121,
                "allow_overtime": True,
                "overtime_reason": "今天明确延长一分钟",
            },
        )
        assert today.status_code == 200
        assert today.json()["overtime"] is True
        assert today.json()["deferred_tasks"]

        paused = client.post(
            f"/learning-runs/{run['id']}/pause",
            json={"reason": "临时中断"},
        )
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        assert paused.json()["pause_reason"] == "临时中断"

        while_paused = client.post(
            f"/learning-runs/{run['id']}/today",
            json={"available_minutes": 120},
        )
        assert while_paused.status_code == 200
        assert while_paused.json()["tasks"] == []

        resumed = client.post(f"/learning-runs/{run['id']}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["status"] == "active"

        checkpoints = client.get(f"/learning-runs/{run['id']}/stage-checkpoints")
        assert checkpoints.status_code == 200
        assert len(checkpoints.json()) == 12

        gates = client.get(f"/learning-runs/{run['id']}/branch-gates")
        assert gates.status_code == 200
        assert gates.json()["selected_branch_id"] is None
        assert len(gates.json()["gates"]) == 4

        structured = next(
            item
            for item in resumed.json()["activities"]
            if item["template_activity_id"] == "p-structured-check"
        )
        review = client.post(
            f"/learning-runs/{run['id']}/independent-reviews",
            json={
                "activity_id": structured["id"],
                "capability_ids": ["p-control-flow"],
                "dimension": "understanding",
                "reviewer_relationship": "同事",
                "rubric_id": "understanding-rubric",
                "rubric_version": "1.0.0",
                "conclusion": "meets",
                "reviewed_at": clock[0].isoformat(),
            },
        )
        assert review.status_code == 201
        assert review.json()["attachments_stored"] is False
