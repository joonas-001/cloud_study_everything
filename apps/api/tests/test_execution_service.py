from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.execution import LearningExecutionError, LearningExecutionService
from cloud_study_api.governance import validate_repository
from cloud_study_api.learning import LearningService
from cloud_study_api.notifications import NotificationService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _services(
    tmp_path: Path,
    clock: list[datetime],
) -> tuple[DiagnosticService, LearningService, LearningExecutionService]:
    database_path = tmp_path / "execution.db"
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
        now=lambda: clock[0],
    )
    return diagnostics, learning, execution


def _saved_plan(
    diagnostics: DiagnosticService,
    learning: LearningService,
) -> dict[str, Any]:
    diagnostic = diagnostics.create_session(
        skill_id="algorithm",
        skill_version="0.2.0",
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
    return learning.set_proposal_status(proposal["id"], "saved_preview")


def _create_run(
    execution: LearningExecutionService,
    proposal_id: str,
    *,
    reuse_from_run_id: str | None = None,
    confirm_reuse: bool = False,
) -> dict[str, Any]:
    return execution.create_run(
        planning_proposal_id=proposal_id,
        preview=True,
        code_execution=False,
        external_ai=False,
        confirm_historical_plan=True,
        reuse_from_run_id=reuse_from_run_id,
        confirm_reuse=confirm_reuse,
    )


def _submission(activity: dict[str, Any], *, pass_check: bool = True) -> dict[str, str]:
    accepted = {
        "programming-check": "check-empty-first",
        "complexity-check": "n-nlogn-n2",
        "structure-check": "dynamic-array",
        "checkpoint-correction": "linked-list-needs-traversal",
        "retention-review-template": "o-n",
    }
    values: dict[str, str] = {}
    template_id = activity["template_activity_id"].split(":", maxsplit=1)[0]
    for field in activity["submission_fields"]:
        if field["kind"] == "confirmation":
            values[field["id"]] = "true"
        elif field["kind"] == "choice":
            if pass_check:
                values[field["id"]] = accepted[template_id]
            else:
                values[field["id"]] = next(
                    option for option in field["options"] if option != accepted[template_id]
                )
        else:
            values[field["id"]] = "证" * field["min_length"]
    return values


def _finish_initial_learning(execution: LearningExecutionService, run_id: str) -> dict[str, Any]:
    for _ in range(30):
        run = execution.get_run(run_id)
        if run["status"] != "active":
            return run
        activity = next(
            (
                item
                for item in run["activities"]
                if item["status"] == "available" and item["type"] != "review"
            ),
            None,
        )
        assert activity is not None
        execution.submit_attempt(
            activity["id"],
            submission=_submission(activity),
        )
    raise AssertionError("initial learning did not reach retention_pending")


def test_run_locks_content_rejects_parallel_run_and_requires_confirmed_reuse(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 7, 28, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock)
    proposal = _saved_plan(diagnostics, learning)

    run = _create_run(execution, proposal["id"])
    assert run["status"] == "active"
    assert run["skill_version"] == "0.2.0"
    assert run["lock_sha256"]
    assert run["code_execution"] == "disabled"
    assert run["external_ai"] == "disabled"

    with pytest.raises(LearningExecutionError) as parallel:
        _create_run(execution, proposal["id"])
    assert parallel.value.code == "nonterminal_learning_run_exists"

    ended = execution.end_run(run["id"])
    assert ended["status"] == "ended"
    with pytest.raises(LearningExecutionError) as unconfirmed:
        _create_run(
            execution,
            proposal["id"],
            reuse_from_run_id=ended["id"],
        )
    assert unconfirmed.value.code == "learning_run_reuse_confirmation_required"

    reused = _create_run(
        execution,
        proposal["id"],
        reuse_from_run_id=ended["id"],
        confirm_reuse=True,
    )
    assert reused["reused_from_run_id"] == ended["id"]
    assert reused["id"] != ended["id"]


def test_historical_saved_plan_is_visible_and_requires_explicit_confirmation(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 7, 28, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock)
    old_plan = _saved_plan(diagnostics, learning)
    clock[0] += timedelta(minutes=1)
    new_plan = _saved_plan(diagnostics, learning)

    options = execution.list_planning_options("algorithm", "0.2.0")
    assert {option["id"] for option in options} == {old_plan["id"], new_plan["id"]}
    historical = next(option for option in options if option["id"] == old_plan["id"])
    assert historical["is_historical"] is True
    assert historical["has_newer_diagnostic"] is True
    assert historical["has_newer_plan"] is True

    with pytest.raises(LearningExecutionError) as unconfirmed:
        execution.create_run(
            planning_proposal_id=old_plan["id"],
            preview=True,
            code_execution=False,
            external_ai=False,
            confirm_historical_plan=False,
            reuse_from_run_id=None,
            confirm_reuse=False,
        )
    assert unconfirmed.value.code == "historical_plan_confirmation_required"

    created = _create_run(execution, old_plan["id"])
    assert created["selected_historical_plan"] is True


def test_initial_completion_review_failure_correction_and_next_day_retry(
    tmp_path: Path,
) -> None:
    clock = [datetime(2026, 7, 28, 8, 0, tzinfo=UTC)]
    diagnostics, learning, execution = _services(tmp_path, clock)
    proposal = _saved_plan(diagnostics, learning)
    created = _create_run(execution, proposal["id"])

    run = _finish_initial_learning(execution, created["id"])
    assert run["status"] == "retention_pending"
    assert run["completed_at"] is None
    assert [review["interval_days"] for review in run["reviews"]] == [1]

    evidence = execution.get_evidence(run["id"])
    dimensions = {item["dimension"]: item for item in evidence["dimensions"]}
    assert set(dimensions) == {
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    }
    assert dimensions["correction"]["evidence_level"] == "supported"
    assert dimensions["retention"]["evidence_level"] == "none"

    clock[0] += timedelta(days=2)
    overdue = execution.get_reviews(run["id"])[0]
    assert overdue["status"] == "available"
    assert overdue["overdue"] is True

    started = execution.start_review(overdue["id"])
    failed = execution.submit_attempt(
        started["activity"]["id"],
        submission=_submission(started["activity"], pass_check=False),
    )
    assert failed["run"]["status"] == "retention_pending"
    assert failed["run"]["reviews"][0]["status"] == "failed"
    correction = next(
        activity
        for activity in failed["run"]["activities"]
        if activity["type"] == "correction"
        and activity["template_activity_id"].startswith("review-correction:")
    )

    corrected = execution.submit_attempt(
        correction["id"],
        submission=_submission(
            {
                **correction,
                "template_activity_id": "retention-review-template",
            }
        ),
    )
    retry = corrected["run"]["reviews"][-1]
    assert retry["checkpoint_index"] == 1
    assert retry["attempt_number"] == 2
    assert retry["status"] == "scheduled"
    assert retry["due_at"].replace(tzinfo=UTC) == clock[0] + timedelta(days=1)

    clock[0] += timedelta(days=1)
    retry_started = execution.start_review(retry["id"])
    passed = execution.submit_attempt(
        retry_started["activity"]["id"],
        submission=_submission(retry_started["activity"]),
    )
    assert passed["run"]["status"] == "retention_pending"
    assert passed["run"]["reviews"][-1]["checkpoint_index"] == 2
