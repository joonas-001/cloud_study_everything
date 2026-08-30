from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from cloud_study_api.providers import AnswerSnapshot, DiagnosticDefinition

ENGINE_VERSION = "deterministic-adaptive-v1"


class AdaptiveDiagnosticStateError(RuntimeError):
    """Raised when persisted or governed adaptive state cannot be interpreted safely."""


@dataclass(frozen=True, slots=True)
class CapabilityState:
    capability_id: str
    status: str
    positive_signal_count: int
    negative_signal_count: int
    inconclusive_signal_count: int
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AdaptiveDecision:
    engine_version: str
    state_sha256: str
    strategy: str
    selected_question_id: str | None
    selection_reason_code: str
    explanation: str
    stop_reason: str | None
    question_count: int
    estimated_minutes: int
    capability_states: tuple[CapabilityState, ...]


def decide(
    definition: DiagnosticDefinition,
    answers: dict[str, AnswerSnapshot],
) -> AdaptiveDecision:
    policy = definition.policy
    capabilities = definition.capabilities
    if definition.schema_version != "2.0.0" or policy is None or capabilities is None:
        raise AdaptiveDiagnosticStateError("adaptive definition metadata is incomplete")
    if policy.fallback != "managed_fixed_sequence":
        raise AdaptiveDiagnosticStateError("unsupported adaptive fallback policy")
    unknown_answers = sorted(set(answers) - set(definition.questions))
    if unknown_answers:
        raise AdaptiveDiagnosticStateError(
            f"answers reference unknown questions: {', '.join(unknown_answers)}"
        )

    _validate_definition_references(definition)
    state_sha256 = _state_sha256(definition, answers)
    question_count = len(answers)
    estimated_minutes = sum(
        definition.questions[question_id].estimated_minutes for question_id in answers
    )
    states = _classify(definition, answers)

    if question_count >= policy.session_question_max:
        return _stopped(
            state_sha256,
            question_count,
            estimated_minutes,
            states,
            "question_limit",
            "已达到受管题量上限。未充分覆盖的能力保持 inconclusive。",
        )

    candidates = _eligible_candidates(definition, answers, states)
    if candidates:
        try:
            selected, reason_code, explanation = _select_candidate(
                definition, answers, states, candidates
            )
            strategy = "adaptive"
        except AdaptiveDiagnosticStateError, KeyError, ValueError:
            selected = next(
                question_id for question_id in definition.questions if question_id in candidates
            )
            reason_code = "managed-fallback"
            explanation = "自适应排序规则未能安全完成。已按受管题目顺序选择稳定题目 ID。"
            strategy = "managed_fixed_sequence"
        return AdaptiveDecision(
            engine_version=ENGINE_VERSION,
            state_sha256=state_sha256,
            strategy=strategy,
            selected_question_id=selected,
            selection_reason_code=reason_code,
            explanation=explanation,
            stop_reason=None,
            question_count=question_count,
            estimated_minutes=estimated_minutes,
            capability_states=tuple(states.values()),
        )

    unresolved_unasked = [
        question_id for question_id in definition.questions if question_id not in answers
    ]
    if unresolved_unasked and not _all_remaining_blocked_or_terminal(
        definition, states, unresolved_unasked
    ):
        selected = unresolved_unasked[0]
        return AdaptiveDecision(
            engine_version=ENGINE_VERSION,
            state_sha256=state_sha256,
            strategy="managed_fixed_sequence",
            selected_question_id=selected,
            selection_reason_code="managed-fallback",
            explanation=("自适应规则未产生可安全解释的候选。已按受管题目顺序选择稳定题目 ID。"),
            stop_reason=None,
            question_count=question_count,
            estimated_minutes=estimated_minutes,
            capability_states=tuple(states.values()),
        )

    return _stopped(
        state_sha256,
        question_count,
        estimated_minutes,
        states,
        "all_capabilities_classified",
        "所有能力已得到路径状态。因前置补救或题目信号耗尽的能力明确保持 inconclusive。",
    )


def _validate_definition_references(definition: DiagnosticDefinition) -> None:
    assert definition.capabilities is not None
    known = set(definition.capabilities)
    for capability in definition.capabilities.values():
        unknown = set(capability.prerequisite_capability_ids) - known
        if unknown:
            raise AdaptiveDiagnosticStateError(
                f"capability {capability.capability_id} has unknown prerequisites"
            )
    for question in definition.questions.values():
        if not question.capability_ids or set(question.capability_ids) - known:
            raise AdaptiveDiagnosticStateError(
                f"question {question.question_id} has invalid capability scope"
            )
        if question.signal_kind == "deterministic_choice" and not (
            question.deterministic_answer_values or question.critical_misconception_values
        ):
            raise AdaptiveDiagnosticStateError(
                f"question {question.question_id} has no deterministic signal values"
            )


def _state_sha256(
    definition: DiagnosticDefinition,
    answers: dict[str, AnswerSnapshot],
) -> str:
    assert definition.policy is not None
    payload = {
        "engine_version": ENGINE_VERSION,
        "definition_id": definition.definition_id,
        "skill_id": definition.skill_id,
        "skill_version": definition.skill_version,
        "policy_id": definition.policy.policy_id,
        "policy_version": definition.policy.version,
        "answers": [
            {
                "question_id": answer.question_id,
                "response_kind": answer.response_kind,
                "content": answer.content,
                "revision": answer.revision,
            }
            for answer in sorted(answers.values(), key=lambda item: item.question_id)
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _classify(
    definition: DiagnosticDefinition,
    answers: dict[str, AnswerSnapshot],
) -> dict[str, CapabilityState]:
    assert definition.capabilities is not None
    raw_counts: dict[str, tuple[int, int, int]] = {}
    for capability_id in definition.capabilities:
        positive = negative = inconclusive = 0
        for question in definition.questions.values():
            if capability_id not in question.capability_ids:
                continue
            answer = answers.get(question.question_id)
            if answer is None:
                continue
            if answer.response_kind != "answered":
                inconclusive += 1
            elif answer.content in question.deterministic_answer_values:
                positive += 1
            elif answer.content in question.critical_misconception_values:
                negative += 1
            else:
                inconclusive += 1
        raw_counts[capability_id] = (positive, negative, inconclusive)

    states: dict[str, CapabilityState] = {}
    pending = set(definition.capabilities)
    while pending:
        progressed = False
        for capability_id in sorted(pending):
            capability = definition.capabilities[capability_id]
            if any(
                prerequisite in pending for prerequisite in capability.prerequisite_capability_ids
            ):
                continue
            positive, negative, inconclusive = raw_counts[capability_id]
            prerequisite_states = [
                states[item].status for item in capability.prerequisite_capability_ids
            ]
            reasons: list[str] = []
            if negative >= 1:
                status = "remediation_required"
                reasons.append("critical-negative-signal")
            elif positive >= 2 and "remediation_required" not in prerequisite_states:
                status = "ready"
                reasons.append("two-independent-positive-signals")
            else:
                status = "inconclusive"
                if "remediation_required" in prerequisite_states:
                    reasons.append("prerequisite-remediation-block")
                if positive == 1:
                    reasons.append("single-positive-signal")
                if inconclusive:
                    reasons.append("skip-uncertain-or-nondeterministic")
                if not reasons:
                    reasons.append("insufficient-signal")
            states[capability_id] = CapabilityState(
                capability_id=capability_id,
                status=status,
                positive_signal_count=positive,
                negative_signal_count=negative,
                inconclusive_signal_count=inconclusive,
                reason_codes=tuple(reasons),
            )
            pending.remove(capability_id)
            progressed = True
        if not progressed:
            raise AdaptiveDiagnosticStateError("capability prerequisites contain a cycle")
    return states


def _eligible_candidates(
    definition: DiagnosticDefinition,
    answers: dict[str, AnswerSnapshot],
    states: dict[str, CapabilityState],
) -> list[str]:
    assert definition.capabilities is not None
    candidates: list[str] = []
    for question_id, question in definition.questions.items():
        if question_id in answers:
            continue
        if all(
            states[item].status in {"ready", "remediation_required"}
            for item in question.capability_ids
        ):
            continue
        prerequisites = {
            prerequisite
            for capability_id in question.capability_ids
            for prerequisite in definition.capabilities[capability_id].prerequisite_capability_ids
        }
        if any(states[item].status == "remediation_required" for item in prerequisites):
            continue
        candidates.append(question_id)
    return candidates


def _select_candidate(
    definition: DiagnosticDefinition,
    answers: dict[str, AnswerSnapshot],
    states: dict[str, CapabilityState],
    candidates: list[str],
) -> tuple[str, str, str]:
    descendants = _descendant_counts(definition)

    def score(question_id: str) -> tuple[int, int, int, str]:
        question = definition.questions[question_id]
        blocker_score = max(descendants[item] for item in question.capability_ids)
        signal_count = max(
            states[item].positive_signal_count + states[item].negative_signal_count
            for item in question.capability_ids
        )
        distinguishes = 1 if signal_count == 1 else 0
        prior_questions = sum(
            1
            for answered_id in answers
            if set(definition.questions[answered_id].capability_ids) & set(question.capability_ids)
        )
        return (-blocker_score, -distinguishes, prior_questions, question_id)

    selected = min(candidates, key=score)
    question = definition.questions[selected]
    blocker_score = max(descendants[item] for item in question.capability_ids)
    has_one_signal = any(
        states[item].positive_signal_count + states[item].negative_signal_count == 1
        for item in question.capability_ids
    )
    reason_code = (
        "distinguish-remediation-or-ready"
        if has_one_signal
        else (
            "downstream-blocking"
            if blocker_score > 0
            else (question.selection_reason_code or "stable-id")
        )
    )
    explanation = (
        f"按下游阻断度 {blocker_score}、区分价值、重复次数和稳定题目 ID 依次排序。"
        f"选择 {selected}。只形成 {', '.join(question.capability_ids)} 的诊断信号。"
    )
    return selected, reason_code, explanation


def _descendant_counts(definition: DiagnosticDefinition) -> dict[str, int]:
    assert definition.capabilities is not None
    children: dict[str, set[str]] = {item: set() for item in definition.capabilities}
    for capability in definition.capabilities.values():
        for prerequisite in capability.prerequisite_capability_ids:
            children[prerequisite].add(capability.capability_id)

    def descendants(capability_id: str) -> set[str]:
        result: set[str] = set()
        stack = list(children[capability_id])
        while stack:
            child = stack.pop()
            if child in result:
                continue
            result.add(child)
            stack.extend(children[child])
        return result

    return {item: len(descendants(item)) for item in children}


def _all_remaining_blocked_or_terminal(
    definition: DiagnosticDefinition,
    states: dict[str, CapabilityState],
    question_ids: list[str],
) -> bool:
    assert definition.capabilities is not None
    for question_id in question_ids:
        question = definition.questions[question_id]
        if all(
            states[item].status in {"ready", "remediation_required"}
            for item in question.capability_ids
        ):
            continue
        prerequisites = {
            prerequisite
            for capability_id in question.capability_ids
            for prerequisite in definition.capabilities[capability_id].prerequisite_capability_ids
        }
        if not any(states[item].status == "remediation_required" for item in prerequisites):
            return False
    return True


def _stopped(
    state_sha256: str,
    question_count: int,
    estimated_minutes: int,
    states: dict[str, CapabilityState],
    stop_reason: str,
    explanation: str,
) -> AdaptiveDecision:
    return AdaptiveDecision(
        engine_version=ENGINE_VERSION,
        state_sha256=state_sha256,
        strategy="stopped",
        selected_question_id=None,
        selection_reason_code=stop_reason.replace("_", "-"),
        explanation=explanation,
        stop_reason=stop_reason,
        question_count=question_count,
        estimated_minutes=estimated_minutes,
        capability_states=tuple(states.values()),
    )
