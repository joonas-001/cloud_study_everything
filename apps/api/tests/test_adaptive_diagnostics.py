from pytest import MonkeyPatch

import cloud_study_api.adaptive_diagnostics as engine
from cloud_study_api.providers import (
    AdaptiveDiagnosticPolicy,
    DiagnosticCapability,
    DiagnosticDefinition,
    DiagnosticQuestion,
)


def _definition() -> DiagnosticDefinition:
    question = DiagnosticQuestion(
        question_id="question-a",
        prompt="prompt",
        reason="reason",
        response_type="single_choice",
        options=(("correct", "Correct"), ("wrong", "Wrong")),
        transitions={"answered": None, "skipped": None, "uncertain": None},
        capability_ids=("capability-a",),
        signal_kind="deterministic_choice",
        deterministic_answer_values=frozenset({"correct"}),
        critical_misconception_values=frozenset({"wrong"}),
        selection_reason_code="entry-baseline",
    )
    return DiagnosticDefinition(
        definition_id="definition-a",
        skill_id="test-skill",
        skill_version="1.0.0",
        start_question_id=question.question_id,
        questions={question.question_id: question},
        schema_version="2.0.0",
        policy=AdaptiveDiagnosticPolicy(
            policy_id="policy-a",
            version="1.0.0",
            session_question_max=10,
            session_minutes_max=20,
            fallback="managed_fixed_sequence",
            evidence_ceiling="diagnostic_signal_only",
        ),
        capabilities={
            "capability-a": DiagnosticCapability(
                capability_id="capability-a",
                prerequisite_capability_ids=(),
            )
        },
    )


def test_selection_failure_uses_managed_fixed_sequence(monkeypatch: MonkeyPatch) -> None:
    def fail_selection(*_args: object) -> tuple[str, str, str]:
        raise ValueError("simulated deterministic rule failure")

    monkeypatch.setattr(engine, "_select_candidate", fail_selection)
    decision = engine.decide(_definition(), {})

    assert decision.strategy == "managed_fixed_sequence"
    assert decision.selected_question_id == "question-a"
    assert decision.selection_reason_code == "managed-fallback"
    assert decision.state_sha256 == engine.decide(_definition(), {}).state_sha256
