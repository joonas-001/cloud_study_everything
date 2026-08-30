from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from cloud_study_api.ai_configuration import (
    AiConfigurationError,
    AiConfigurationService,
)
from cloud_study_api.deployment import DeploymentCapabilityError, DeploymentGuard
from cloud_study_api.diagnostics import DiagnosticError, DiagnosticService
from cloud_study_api.execution import (
    LearningExecutionError,
    LearningExecutionService,
)
from cloud_study_api.experiments import ExperimentError, ExperimentService
from cloud_study_api.learning import LearningError, LearningService
from cloud_study_api.market_research import MarketResearchError, MarketResearchService
from cloud_study_api.notifications import NotificationError, NotificationService
from cloud_study_api.readiness import ReadinessError, ReadinessService


class PrivacySettingsResponse(BaseModel):
    external_ai_enabled: bool
    inactivity_timeout_minutes: int
    updated_at: datetime


class DeploymentStatusResponse(BaseModel):
    mode: Literal["local", "private_preview"]
    authentication_required: bool
    identity_provider: str | None
    owner_login_configured: bool
    region: str | None
    data_store: Literal["sqlite"]
    remote_runner_enabled: bool
    external_calls_enabled: bool
    monthly_budget_cny: int | None


class UpdatePrivacySettingsRequest(BaseModel):
    external_ai_enabled: bool


class CreateDiagnosticSessionRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=100)
    skill_version: str = Field(min_length=1, max_length=50)
    preview: bool
    provider_id: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=100)
    credential_reference: str | None = Field(default=None, max_length=255)
    external_ai_consent: bool


class SubmitAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    response_kind: Literal["answered", "skipped", "uncertain"]
    content: str | None = Field(default=None, max_length=20_000)


class CorrectAnswerRequest(BaseModel):
    response_kind: Literal["answered", "skipped", "uncertain"]
    content: str | None = Field(default=None, max_length=20_000)


class DiagnosticQuestionResponse(BaseModel):
    id: str
    prompt: str
    reason: str
    response_type: Literal["free_text", "code_text", "single_choice"]
    options: list[dict[str, str]]
    selection_reason_code: str | None = None
    selection_explanation: str | None = None


class DiagnosticDecisionResponse(BaseModel):
    engine_version: str
    state_sha256: str
    strategy: Literal["adaptive", "managed_fixed_sequence", "stopped"]
    selected_question_id: str | None
    selection_reason_code: str
    explanation: str
    stop_reason: str | None
    question_count: int
    estimated_minutes: int


class DiagnosticCapabilityStateResponse(BaseModel):
    capability_id: str
    status: Literal["ready", "remediation_required", "inconclusive"]
    positive_signal_count: int
    negative_signal_count: int
    inconclusive_signal_count: int
    reason_codes: list[str]


class DiagnosticLimitsResponse(BaseModel):
    question_max: int
    minutes_max: int
    evidence_ceiling: Literal["diagnostic_signal_only"]


class DiagnosticAnswerResponse(BaseModel):
    id: str
    question_id: str
    response_kind: Literal["answered", "skipped", "uncertain"]
    content: str | None
    response_type: Literal["free_text", "code_text", "single_choice"]
    options: list[dict[str, str]]
    revision: int
    on_current_path: bool
    created_at: datetime


class DiagnosticSessionResponse(BaseModel):
    id: str
    skill_id: str
    skill_version: str
    is_preview: bool
    provider_id: str
    model_id: str
    credential_reference: str | None
    external_ai_consent: bool
    external_ai_enabled: bool
    status: Literal["active", "ended", "failed", "plan_saved"]
    current_question: DiagnosticQuestionResponse | None
    answers: list[DiagnosticAnswerResponse]
    ready_to_end: bool
    can_generate_plan: bool
    diagnostic_mode: Literal["fixed_sequence", "deterministic_adaptive"]
    decision: DiagnosticDecisionResponse | None
    capability_states: list[DiagnosticCapabilityStateResponse]
    limits: DiagnosticLimitsResponse | None
    created_at: datetime
    last_activity_at: datetime
    ended_at: datetime | None
    end_reason: str | None


class CreatePlanningProposalRequest(BaseModel):
    diagnostic_session_id: str = Field(min_length=1, max_length=36)
    preview: bool
    provider_id: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=100)


class PlanningSourceResponse(BaseModel):
    id: str
    title: str
    publisher: str
    url: str
    authority_tier: int
    retrieved_at: str


class PlanningUnitResponse(BaseModel):
    id: str
    template_unit_id: str
    sequence: int
    title: str
    objective: str
    reason: str
    estimated_minutes: int
    completion_criteria: list[str]
    sources: list[PlanningSourceResponse]


class PlanningProposalResponse(BaseModel):
    id: str
    diagnostic_session_id: str
    skill_id: str
    skill_version: str
    template_id: str
    provider_id: str
    model_id: str
    is_preview: bool
    status: Literal["draft", "saved_preview", "rejected", "frozen_preview"]
    title: str
    rationale: str
    limitations: list[str]
    units: list[PlanningUnitResponse]
    created_at: datetime
    updated_at: datetime


class UpdatePlanningUnitRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    objective: str = Field(min_length=1, max_length=5000)
    reason: str = Field(min_length=1, max_length=5000)
    estimated_minutes: int = Field(ge=15, le=180)
    completion_criteria: list[str] = Field(min_length=1, max_length=20)


class UpdatePlanningStatusRequest(BaseModel):
    status: Literal["saved_preview", "rejected"]


class CreateSourceCheckRequest(BaseModel):
    skill_id: str = Field(min_length=1, max_length=100)
    skill_version: str = Field(min_length=1, max_length=50)
    manual: bool = False


class SourceCheckResultResponse(BaseModel):
    source_id: str
    source_title: str
    status: Literal[
        "baseline_created",
        "unchanged",
        "changed",
        "failed",
        "manual",
        "indeterminate",
    ]
    http_status: int | None
    error_message: str | None
    last_success_at: datetime | None
    checked_at: datetime


class SourceCheckRunResponse(BaseModel):
    id: str
    skill_id: str
    skill_version: str
    local_date: str
    trigger: Literal["automatic", "manual"]
    status: Literal["running", "completed", "completed_with_failures"]
    checked_count: int
    changed_count: int
    failed_count: int
    started_at: datetime
    completed_at: datetime | None
    reused: bool
    results: list[SourceCheckResultResponse]


class SourceChangeCandidateResponse(BaseModel):
    id: str
    skill_id: str
    skill_version: str
    source_id: str
    source_title: str
    status: Literal["pending", "dismissed", "accepted"]
    change_kind: str
    summary: str
    evidence: dict[str, object]
    created_at: datetime
    resolved_at: datetime | None


class ResolveSourceChangeRequest(BaseModel):
    decision: Literal["dismissed", "accepted"]


class NotificationPreferenceResponse(BaseModel):
    email_enabled: bool
    email_action_required: bool
    email_warning: bool
    email_delay_minutes: int
    recipient_email: str | None
    sender_email: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_username: str | None
    smtp_security: Literal["starttls", "ssl"]
    credential_reference: str | None
    updated_at: datetime


class UpdateNotificationPreferenceRequest(BaseModel):
    email_enabled: bool
    email_action_required: bool
    email_warning: bool
    email_delay_minutes: int = Field(ge=0, le=1440)
    recipient_email: str | None = Field(default=None, max_length=320)
    sender_email: str | None = Field(default=None, max_length=320)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=320)
    smtp_security: Literal["starttls", "ssl"]
    smtp_password: str | None = Field(default=None, min_length=1, max_length=2000)


class NotificationResponse(BaseModel):
    id: str
    category: str
    severity: Literal["required", "action_required", "warning", "info"]
    title: str
    message: str
    related_type: str | None
    related_id: str | None
    created_at: datetime
    read_at: datetime | None
    archived_at: datetime | None
    email_status: Literal["queued", "sent", "cancelled", "failed"] | None


class EmailOutboxProcessResponse(BaseModel):
    sent: int
    cancelled: int
    failed: int


class AiProviderResponse(BaseModel):
    id: str
    display_name: str
    default_base_url: str | None
    is_external: bool
    executable: bool
    models: list[str]
    capabilities: dict[str, bool]
    status_note: str


class CreateAiProviderProfileRequest(BaseModel):
    provider_id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    model_id: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, max_length=2000)
    api_key: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool = True


class AiProviderProfileResponse(BaseModel):
    id: str
    provider_id: str
    display_name: str
    model_id: str | None
    base_url: str | None
    credential_reference: str | None
    enabled: bool
    executable: bool
    status_note: str
    created_at: datetime
    updated_at: datetime


class PlanningOptionResponse(BaseModel):
    id: str
    title: str
    diagnostic_session_id: str
    diagnostic_created_at: datetime | None
    saved_at: datetime
    is_historical: bool
    has_newer_diagnostic: bool
    has_newer_plan: bool
    source_review_pending: bool


class CreateLearningRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planning_proposal_id: str = Field(min_length=1, max_length=36)
    preview: bool = True
    code_execution: bool = False
    external_ai: bool = False
    confirm_historical_plan: bool = False
    reuse_from_run_id: str | None = Field(default=None, max_length=36)
    confirm_reuse: bool = False


class SubmissionFieldResponse(BaseModel):
    id: str
    kind: Literal["text", "code", "choice", "confirmation"]
    label: str
    required: bool
    min_length: int
    max_length: int
    options: list[str] | None = None


class ActivityEvaluationResponse(BaseModel):
    id: str
    method: Literal[
        "deterministic",
        "self_review",
        "review_pending",
        "not_executable",
        "runner",
    ]
    result: Literal[
        "passed",
        "failed",
        "submitted",
        "uncertain",
        "review_pending",
        "not_executable",
    ]
    rubric_id: str | None
    detail: dict[str, object]
    created_at: datetime


class RunnerInvocationResponse(BaseModel):
    id: str
    protocol_version: str
    task_id: str
    runtime_profile_id: str
    runtime_profile_version: str
    runtime_image: str
    artifact_sha256: str
    request_sha256: str
    status: Literal[
        "queued",
        "running",
        "passed",
        "failed",
        "timeout",
        "output_limit",
        "infrastructure_error",
    ]
    failure_code: str | None
    result: dict[str, object] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ActivityAttemptResponse(BaseModel):
    id: str
    revision: int
    submission: dict[str, str]
    corrects_attempt_id: str | None
    evaluations: list[ActivityEvaluationResponse]
    runner_invocations: list[RunnerInvocationResponse]
    created_at: datetime


class LearningActivityResponse(BaseModel):
    id: str
    template_activity_id: str
    type: Literal[
        "study",
        "explanation",
        "structured_check",
        "code_text",
        "transfer",
        "correction",
        "project_evidence",
        "review",
    ]
    sequence: int
    title: str
    prompt: str
    reason: str
    estimated_minutes: int
    required: bool
    status: Literal["pending", "available", "completed", "correction_required"]
    completion_rule: Literal[
        "confirmation",
        "valid_submission",
        "deterministic_pass",
        "runner_pass",
    ]
    submission_fields: list[SubmissionFieldResponse]
    source_ids: list[str]
    available_at: datetime | None
    overdue: bool
    attempts: list[ActivityAttemptResponse]
    completed_at: datetime | None
    runner_task_id: str | None


class MasteryDimensionResponse(BaseModel):
    dimension: Literal[
        "understanding",
        "operation",
        "transfer",
        "artifact",
        "retention",
        "correction",
    ]
    evidence_level: Literal["none", "limited", "supported", "verified", "retained"]
    review_flags: list[
        Literal[
            "manual_review_pending",
            "retention_due",
            "source_review_pending",
        ]
    ]
    evidence_count: int
    updated_at: datetime


class ReviewTaskResponse(BaseModel):
    id: str
    activity_id: str | None
    checkpoint_index: int
    attempt_number: int
    interval_days: int
    due_at: datetime
    status: Literal["scheduled", "available", "passed", "failed"]
    overdue: bool
    policy_id: str
    policy_version: str
    completed_at: datetime | None


class LearningRunResponse(BaseModel):
    id: str
    planning_proposal_id: str
    diagnostic_session_id: str
    skill_id: str
    skill_version: str
    status: Literal["active", "retention_pending", "completed", "ended"]
    is_preview: bool
    code_execution: Literal["disabled", "enabled"]
    external_ai: Literal["disabled"]
    selected_historical_plan: bool
    reused_from_run_id: str | None
    lock_sha256: str
    engine_protocol_version: str
    runner_protocol_version: str
    evidence_limitations: list[str]
    activities: list[LearningActivityResponse]
    dimensions: list[MasteryDimensionResponse]
    reviews: list[ReviewTaskResponse]
    next_actions: list[str]
    created_at: datetime
    updated_at: datetime
    retention_started_at: datetime | None
    completed_at: datetime | None
    ended_at: datetime | None
    end_reason: str | None


class TodayLearningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_minutes: int = Field(default=120, ge=15, le=480)


class TodayLearningResponse(BaseModel):
    run_id: str
    generated_at: datetime
    available_minutes: int
    estimated_minutes: int
    tasks: list[LearningActivityResponse]
    reason: str


class SubmitActivityAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submission: dict[str, str]
    corrects_attempt_id: str | None = Field(default=None, max_length=36)
    mark_uncertain: bool = False


class ActivityAttemptSubmissionResponse(BaseModel):
    attempt: ActivityAttemptResponse
    activity: LearningActivityResponse
    run: LearningRunResponse


class RunnerAvailabilityResponse(BaseModel):
    available: bool
    reason_code: str | None
    docker_path: str | None
    data_root: str
    free_gb: float | None
    used_gb: float | None
    server_version: str | None = None


class ExecuteRunnerAttemptResponse(BaseModel):
    invocation: RunnerInvocationResponse
    attempt: ActivityAttemptResponse
    activity: LearningActivityResponse
    run: LearningRunResponse


class SelfReviewAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric_id: str = Field(min_length=1, max_length=100)
    result: Literal["not_yet", "uncertain", "meets"]


class SelfReviewAttemptResponse(BaseModel):
    attempt: ActivityAttemptResponse
    activity: LearningActivityResponse
    run: LearningRunResponse


class MasteryEvidenceItemResponse(BaseModel):
    id: str
    activity_id: str
    attempt_id: str
    criterion_id: str
    dimension: str
    method: str
    result: str
    strength: Literal["limited", "supported", "retained_limited"]
    review_flags: list[str]
    created_at: datetime
    superseded_at: datetime | None


class LearningEvidenceResponse(BaseModel):
    run_id: str
    limitations: list[str]
    dimensions: list[MasteryDimensionResponse]
    evidence: list[MasteryEvidenceItemResponse]


class StartReviewResponse(BaseModel):
    review: ReviewTaskResponse
    activity: LearningActivityResponse


GoalKind = Literal[
    "learning",
    "exam",
    "employment",
    "freelancing",
    "productization",
    "other",
]
ReadinessStatus = Literal[
    "not_applicable",
    "not_ready",
    "review_required",
    "comparison_ready",
    "experiment_ready",
]


class CapabilityScopeResponse(BaseModel):
    learning_run_id: str
    learning_run_status: Literal["active", "retention_pending", "completed", "ended"]
    skill_id: str
    skill_version: str
    capability_scope_id: str
    scope_statement: str
    dimensions: list[str]
    created_at: datetime


class SelectUserGoalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(min_length=1, max_length=100)
    skill_version: str = Field(min_length=1, max_length=50)
    capability_scope_id: str = Field(min_length=1, max_length=100)
    goal_kind: GoalKind
    custom_label: str | None = Field(default=None, min_length=1, max_length=200)


class UserGoalResponse(BaseModel):
    schema_version: Literal["1.0.0"]
    id: str
    skill_id: str
    skill_version: str
    capability_scope_id: str
    goal_kind: GoalKind
    custom_label: str | None
    market_comparison_applicable: bool
    created_at: datetime
    superseded_at: datetime | None


class MarketSnapshotResponse(BaseModel):
    id: str
    fixture_id: str
    fixture_version: str
    label: str
    synthetic: Literal[True]
    freshness_status: Literal["current", "stale", "conflicted", "indeterminate"]
    as_of: datetime
    limitations: list[str]
    source_count: int
    created_at: datetime


class CreateReadinessEvaluationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_selection_id: str = Field(min_length=1, max_length=36)
    learning_run_id: str | None = Field(default=None, max_length=36)
    market_snapshot_id: str | None = Field(default=None, max_length=36)


class ReadinessEvaluationResponse(BaseModel):
    schema_version: Literal["1.0.0"]
    id: str
    goal_selection_id: str
    learning_run_id: str | None
    policy_id: str
    policy_version: str
    market_snapshot_id: str | None
    status: ReadinessStatus
    reason_codes: list[str]
    evidence_snapshot: dict[str, object]
    limitations: list[str]
    input_sha256: str
    created_at: datetime


class CreatePathComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_id: str = Field(min_length=1, max_length=36)


class PathComparisonDecisionResponse(BaseModel):
    id: str
    comparison_id: str
    revision: int
    decision: Literal["accepted", "rejected", "deferred"]
    reason: str | None
    created_at: datetime


class PathComparisonResponse(BaseModel):
    schema_version: Literal["1.0.0"]
    id: str
    evaluation_id: str
    market_snapshot_id: str
    synthetic: Literal[True]
    paths: list[dict[str, object]]
    limitations: list[str]
    created_at: datetime
    payload_sha256: str
    decisions: list[PathComparisonDecisionResponse]


class DecidePathComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected", "deferred"]
    reason: str | None = Field(default=None, max_length=2000)


class ReadinessHistoryResponse(BaseModel):
    goal: UserGoalResponse
    evaluations: list[ReadinessEvaluationResponse]
    comparisons: list[PathComparisonResponse]
    events: list[dict[str, object]]


MarketResearchStatus = Literal[
    "source_pending",
    "synthesis_pending",
    "synthesis_in_progress",
    "recovery_required",
    "review_pending",
    "completed",
    "blocked",
    "failed",
]


class CreateMarketResearchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_profile_id: str = Field(min_length=1, max_length=36)
    goal_selection_id: str = Field(min_length=1, max_length=36)
    catalog_id: str = Field(min_length=1, max_length=100)
    catalog_version: str = Field(min_length=1, max_length=50)
    readiness_evaluation_id: str | None = Field(default=None, max_length=36)
    confirm_external_sources: bool


class SynthesizeMarketResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_external_ai: bool


class RecoverPreDispatchMarketResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_recovery: bool


class ReviewMarketResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


class ReconcileMarketResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_end: bool
    note: str | None = Field(default=None, max_length=2000)


class RedactMarketSourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_redaction: bool
    reason: str = Field(min_length=1, max_length=1000)


class MarketResearchRunResponse(BaseModel):
    id: str
    catalog_id: str
    catalog_version: str
    catalog_sha256: str
    skill_id: str
    skill_version: str
    capability_scope_id: str
    goal_selection_id: str
    goal_kind: Literal["employment", "freelancing", "productization"]
    goal_snapshot: dict[str, object]
    readiness_evaluation_id: str | None
    budget_policy_id: str
    budget_policy_version: str
    budget_policy_sha256: str
    scope: dict[str, object]
    status: MarketResearchStatus
    provider_profile_id: str
    provider_id: Literal["deepseek"]
    model_id: Literal["deepseek-v4-flash"]
    response_model_id: str | None
    external_ai_consent: bool
    sources: list[dict[str, object]]
    outbound_material_preview: dict[str, object]
    synthesis: dict[str, object] | None
    synthesis_valid: bool
    synthesis_invalidated_at: datetime | None
    review_status: Literal[
        "not_ready",
        "not_requested",
        "pending",
        "accepted",
        "rejected",
    ]
    review_note: str | None
    estimated_cost_micros: int
    actual_cost_micros: int
    accounted_cost_micros: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    failure_code: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class SourceAccessStateResponse(BaseModel):
    source_id: str
    latest_attempt_at: datetime | None
    latest_attempt_run_id: str | None
    latest_attempt_status: Literal["succeeded", "failed"] | None
    latest_attempt_error_code: str | None
    latest_success_at: datetime | None
    latest_success_run_id: str | None
    next_allowed_at: datetime | None
    cooldown_kind: (
        Literal[
            "successful_refresh_interval",
            "failed_access_cooldown",
        ]
        | None
    )
    cooling_down: bool


class SourceAccessPolicyResponse(BaseModel):
    success_refresh_interval_days: int
    failure_cooldown_hours: int
    manual_bypass_allowed: bool
    blocked: bool
    blocking_reason: (
        Literal[
            "successful_refresh_interval",
            "failed_access_cooldown",
        ]
        | None
    )
    next_allowed_at: datetime | None
    remaining_seconds: int
    eligible_source_ids: list[str]
    blocked_source_ids: list[str]
    latest_research_attempt_at: datetime | None
    latest_research_attempt_run_id: str | None
    latest_research_attempt_status: str | None
    sources: list[SourceAccessStateResponse]


class MarketResearchOverviewResponse(BaseModel):
    catalog: dict[str, object]
    budget: dict[str, object]
    source_access_policy: SourceAccessPolicyResponse
    available_contexts: list[dict[str, object]]
    latest_run: MarketResearchRunResponse | None


class MarketResearchEventResponse(BaseModel):
    id: int
    run_id: str
    event_type: str
    payload: dict[str, object]
    occurred_at: datetime


class MarketResearchHistoryResponse(BaseModel):
    runs: list[MarketResearchRunResponse]
    events: list[MarketResearchEventResponse]


ExperimentStatus = Literal[
    "draft",
    "rejected",
    "blocked",
    "approved",
    "active",
    "paused",
    "ended",
    "completed",
]
ExperimentGateLevel = Literal["draft_only", "local_ready", "action_ready", "blocked"]


class ExperimentPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = "1.0.0"
    path: Literal["employment", "freelancing", "productization"]
    title: str = Field(min_length=1, max_length=200)
    target_audience: str = Field(min_length=1, max_length=500)
    hypothesis: str = Field(min_length=1, max_length=3000)
    planned_action: str = Field(min_length=1, max_length=3000)
    success_metric: str = Field(min_length=1, max_length=2000)
    time_budget_minutes: int = Field(ge=1, le=100_000)
    cost_cap_minor: int = Field(ge=0, le=100_000_000)
    stop_conditions: list[str] = Field(min_length=1, max_length=20)
    non_offerings: list[str] = Field(min_length=1, max_length=20)
    compliance_todos: list[str] = Field(default_factory=list, max_length=20)
    review_on: date


class CreateExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_selection_id: str = Field(min_length=1, max_length=36)
    learning_run_id: str = Field(min_length=1, max_length=36)
    market_research_run_id: str | None = Field(default=None, max_length=36)
    plan: ExperimentPlanRequest


class ExperimentReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: Literal["transfer", "artifact"]
    reviewer_relationship: Literal[
        "peer",
        "mentor",
        "instructor",
        "employer",
        "client",
        "other",
    ]
    review_scope: str = Field(min_length=1, max_length=2000)
    rubric_id: str = Field(min_length=1, max_length=100)
    rubric_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    conclusion: Literal["passed", "needs_work"]
    reviewed_at: datetime


class ExperimentTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["approve", "start", "pause", "resume", "complete", "end", "reject"]
    confirm: bool


class ExperimentActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_kind: Literal[
        "application",
        "interview",
        "networking",
        "portfolio_share",
        "other",
    ]
    description: str = Field(min_length=1, max_length=3000)
    result: Literal[
        "pending",
        "response",
        "no_response",
        "interview",
        "rejected",
        "offer",
        "withdrawn",
        "other",
    ]
    occurred_at: datetime
    confirm_completed_outside_product: bool


class ExperimentOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hypothesis_result: Literal["supported", "not_supported", "inconclusive"]
    observable_result: str = Field(min_length=1, max_length=5000)
    learning_gap_dimension: (
        Literal[
            "understanding",
            "operation",
            "transfer",
            "artifact",
            "retention",
            "correction",
        ]
        | None
    ) = None


class IncomeValuesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = Field(pattern=r"^[A-Z]{3}$")
    amount_basis: Literal["tax_inclusive", "pre_tax"]
    gross_amount_minor: int = Field(ge=0, le=100_000_000_000)
    platform_fee_minor: int = Field(ge=0, le=100_000_000_000)
    direct_cost_minor: int = Field(ge=0, le=100_000_000_000)
    received_amount_minor: int = Field(ge=0, le=100_000_000_000)
    verification_level: Literal["self_reported", "platform_record", "received"]
    note: str | None = Field(default=None, max_length=2000)
    occurred_on: date


class CreateIncomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: IncomeValuesRequest
    confirm_manual_record: bool


class ReviseIncomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: IncomeValuesRequest
    confirm_revision: bool


class RedactIncomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm_redaction: bool


class CreateFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome_id: str | None = Field(default=None, max_length=36)
    suggestion_type: Literal[
        "diagnostic_question",
        "correction",
        "review",
        "project",
        "supplemental_unit",
        "replanning",
        "source_review",
        "pause_path",
    ]
    reason: str = Field(min_length=1, max_length=3000)
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    estimated_minutes: int = Field(ge=0, le=100_000)
    plan_impact: str = Field(min_length=1, max_length=3000)


class DecideFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted", "rejected", "withdrawn"]
    note: str | None = Field(default=None, max_length=2000)


class ExportExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    export_format: Literal["json", "csv"]
    confirm_sensitive_export: bool


class ExperimentReviewResponse(BaseModel):
    id: str
    dimension: Literal["transfer", "artifact"]
    reviewer_relationship: str
    review_scope: str
    rubric_id: str
    rubric_version: str
    conclusion: Literal["passed", "needs_work"]
    reviewed_at: datetime
    created_at: datetime


class ExperimentActionResponse(BaseModel):
    id: str
    action_kind: str
    description: str
    result: str
    occurred_at: datetime
    created_at: datetime
    execution_mode: Literal["completed_outside_product"]


class ExperimentOutcomeResponse(BaseModel):
    id: str
    hypothesis_result: Literal["supported", "not_supported", "inconclusive"]
    observable_result: str
    learning_gap_dimension: str | None
    recorded_at: datetime


class IncomeRevisionResponse(BaseModel):
    id: str
    revision: int
    currency: str | None
    amount_basis: str | None
    gross_amount_minor: int | None
    platform_fee_minor: int | None
    direct_cost_minor: int | None
    received_amount_minor: int | None
    verification_level: str | None
    note: str | None
    occurred_on: str | None
    created_at: datetime


class IncomeRecordResponse(BaseModel):
    id: str
    current_revision: int
    redacted: bool
    amounts_hidden: bool
    revisions: list[IncomeRevisionResponse]
    created_at: datetime
    updated_at: datetime
    redacted_at: datetime | None


class FeedbackSuggestionResponse(BaseModel):
    id: str
    outcome_id: str | None
    suggestion_type: str
    reason: str
    evidence_refs: list[str]
    estimated_minutes: int
    plan_impact: str
    status: Literal["pending", "accepted", "rejected", "withdrawn"]
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None
    auto_applied: Literal[False]


class ExperimentEventResponse(BaseModel):
    id: int
    event_type: str
    payload: dict[str, object]
    occurred_at: datetime


class ExperimentResponse(BaseModel):
    schema_version: Literal["1.0.0"]
    id: str
    goal_selection_id: str
    learning_run_id: str
    market_research_run_id: str | None
    policy_id: str
    policy_version: str
    skill_id: str
    skill_version: str
    skill_manifest_sha256: str
    capability_scope_id: str
    path: Literal["employment", "freelancing", "productization"]
    plan: dict[str, object]
    status: ExperimentStatus
    gate_level: ExperimentGateLevel
    gate_reason_codes: list[str]
    evidence_snapshot: dict[str, object]
    evidence_sha256: str
    external_action_mode: Literal["manual_record_only"]
    reviews: list[ExperimentReviewResponse]
    actions: list[ExperimentActionResponse]
    outcomes: list[ExperimentOutcomeResponse]
    income_records: list[IncomeRecordResponse]
    income_amounts_visible: bool
    feedback_suggestions: list[FeedbackSuggestionResponse]
    events: list[ExperimentEventResponse]
    limitations: list[str]
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None


router = APIRouter()


def get_diagnostic_service(request: Request) -> DiagnosticService:
    service: DiagnosticService = request.app.state.diagnostic_service
    return service


DiagnosticServiceDependency = Annotated[
    DiagnosticService,
    Depends(get_diagnostic_service),
]


def get_learning_service(request: Request) -> LearningService:
    service: LearningService = request.app.state.learning_service
    return service


LearningServiceDependency = Annotated[
    LearningService,
    Depends(get_learning_service),
]


def get_learning_execution_service(request: Request) -> LearningExecutionService:
    service: LearningExecutionService = request.app.state.learning_execution_service
    return service


LearningExecutionServiceDependency = Annotated[
    LearningExecutionService,
    Depends(get_learning_execution_service),
]


def get_readiness_service(request: Request) -> ReadinessService:
    service: ReadinessService = request.app.state.readiness_service
    return service


ReadinessServiceDependency = Annotated[
    ReadinessService,
    Depends(get_readiness_service),
]


def get_notification_service(request: Request) -> NotificationService:
    service: NotificationService = request.app.state.notification_service
    return service


NotificationServiceDependency = Annotated[
    NotificationService,
    Depends(get_notification_service),
]


def get_ai_configuration_service(request: Request) -> AiConfigurationService:
    service: AiConfigurationService = request.app.state.ai_configuration_service
    return service


AiConfigurationServiceDependency = Annotated[
    AiConfigurationService,
    Depends(get_ai_configuration_service),
]


def get_market_research_service(request: Request) -> MarketResearchService:
    service: MarketResearchService = request.app.state.market_research_service
    return service


MarketResearchServiceDependency = Annotated[
    MarketResearchService,
    Depends(get_market_research_service),
]


def get_experiment_service(request: Request) -> ExperimentService:
    service: ExperimentService = request.app.state.experiment_service
    return service


ExperimentServiceDependency = Annotated[
    ExperimentService,
    Depends(get_experiment_service),
]


def get_deployment_guard(request: Request) -> DeploymentGuard:
    guard: DeploymentGuard = request.app.state.deployment_guard
    return guard


DeploymentGuardDependency = Annotated[
    DeploymentGuard,
    Depends(get_deployment_guard),
]


def _require_external_calls(guard: DeploymentGuard) -> None:
    try:
        guard.require_external_calls()
    except DeploymentCapabilityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": error.code, "message": str(error), "context": {}},
        ) from error


def _raise_http(error: DiagnosticError) -> None:
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": str(error),
            "context": error.context,
        },
    ) from error


def _raise_service_http(
    error: (
        LearningError
        | LearningExecutionError
        | NotificationError
        | AiConfigurationError
        | ReadinessError
        | MarketResearchError
        | ExperimentError
    ),
) -> None:
    context = (
        error.context
        if isinstance(
            error,
            (
                LearningError,
                LearningExecutionError,
                ReadinessError,
                MarketResearchError,
                ExperimentError,
            ),
        )
        else {}
    )
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": str(error),
            "context": context,
        },
    ) from error


@router.get(
    "/deployment/status",
    response_model=DeploymentStatusResponse,
    tags=["deployment-6a"],
)
def get_deployment_status(
    guard: DeploymentGuardDependency,
) -> DeploymentStatusResponse:
    return DeploymentStatusResponse.model_validate(guard.status())


@router.get(
    "/settings/privacy",
    response_model=PrivacySettingsResponse,
    tags=["settings"],
)
def get_privacy_settings(
    service: DiagnosticServiceDependency,
) -> PrivacySettingsResponse:
    return PrivacySettingsResponse.model_validate(service.get_privacy_settings())


@router.put(
    "/settings/privacy",
    response_model=PrivacySettingsResponse,
    tags=["settings"],
)
def update_privacy_settings(
    payload: UpdatePrivacySettingsRequest,
    service: DiagnosticServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> PrivacySettingsResponse:
    if payload.external_ai_enabled:
        _require_external_calls(deployment_guard)
    return PrivacySettingsResponse.model_validate(
        service.update_privacy_settings(payload.external_ai_enabled)
    )


@router.post(
    "/diagnostic-sessions",
    response_model=DiagnosticSessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["diagnostics"],
)
def create_diagnostic_session(
    payload: CreateDiagnosticSessionRequest,
    service: DiagnosticServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> DiagnosticSessionResponse:
    if payload.external_ai_consent:
        _require_external_calls(deployment_guard)
    try:
        result = service.create_session(**payload.model_dump())
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.get(
    "/diagnostic-sessions/active",
    response_model=DiagnosticSessionResponse,
    tags=["diagnostics"],
)
def get_active_diagnostic_session(
    service: DiagnosticServiceDependency,
    skill_id: Annotated[str, Query(min_length=1, max_length=100)],
    skill_version: Annotated[str, Query(min_length=1, max_length=50)],
) -> DiagnosticSessionResponse:
    try:
        result = service.get_active_session(skill_id, skill_version)
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.get(
    "/diagnostic-sessions/latest",
    response_model=DiagnosticSessionResponse,
    tags=["diagnostics"],
)
def get_latest_diagnostic_session(
    service: DiagnosticServiceDependency,
    skill_id: Annotated[str, Query(min_length=1, max_length=100)],
    skill_version: Annotated[str, Query(min_length=1, max_length=50)],
) -> DiagnosticSessionResponse:
    try:
        result = service.get_latest_session(skill_id, skill_version)
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.get(
    "/diagnostic-sessions/{session_id}",
    response_model=DiagnosticSessionResponse,
    tags=["diagnostics"],
)
def get_diagnostic_session(
    session_id: str,
    service: DiagnosticServiceDependency,
) -> DiagnosticSessionResponse:
    try:
        result = service.get_session(session_id)
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.post(
    "/diagnostic-sessions/{session_id}/answers",
    response_model=DiagnosticSessionResponse,
    tags=["diagnostics"],
)
def submit_diagnostic_answer(
    session_id: str,
    payload: SubmitAnswerRequest,
    service: DiagnosticServiceDependency,
) -> DiagnosticSessionResponse:
    try:
        result = service.submit_answer(session_id, **payload.model_dump())
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.post(
    "/diagnostic-sessions/{session_id}/answers/{question_id}/corrections",
    response_model=DiagnosticSessionResponse,
    tags=["diagnostics"],
)
def correct_diagnostic_answer(
    session_id: str,
    question_id: str,
    payload: CorrectAnswerRequest,
    service: DiagnosticServiceDependency,
) -> DiagnosticSessionResponse:
    try:
        result = service.correct_answer(
            session_id,
            question_id,
            **payload.model_dump(),
        )
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.post(
    "/diagnostic-sessions/{session_id}/end",
    response_model=DiagnosticSessionResponse,
    tags=["diagnostics"],
)
def end_diagnostic_session(
    session_id: str,
    service: DiagnosticServiceDependency,
) -> DiagnosticSessionResponse:
    try:
        result = service.end_session(session_id)
    except DiagnosticError as error:
        _raise_http(error)
    return DiagnosticSessionResponse.model_validate(result)


@router.post(
    "/planning-proposals",
    response_model=PlanningProposalResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["planning"],
)
def create_planning_proposal(
    payload: CreatePlanningProposalRequest,
    service: LearningServiceDependency,
) -> PlanningProposalResponse:
    try:
        result = service.create_planning_proposal(**payload.model_dump())
    except LearningError as error:
        _raise_service_http(error)
    return PlanningProposalResponse.model_validate(result)


@router.get(
    "/planning-proposals/latest",
    response_model=PlanningProposalResponse,
    tags=["planning"],
)
def get_latest_planning_proposal(
    service: LearningServiceDependency,
    skill_id: Annotated[str, Query(min_length=1, max_length=100)],
    skill_version: Annotated[str, Query(min_length=1, max_length=50)],
) -> PlanningProposalResponse:
    try:
        result = service.get_latest_proposal(skill_id, skill_version)
    except LearningError as error:
        _raise_service_http(error)
    return PlanningProposalResponse.model_validate(result)


@router.get(
    "/planning-proposals/{proposal_id}",
    response_model=PlanningProposalResponse,
    tags=["planning"],
)
def get_planning_proposal(
    proposal_id: str,
    service: LearningServiceDependency,
) -> PlanningProposalResponse:
    try:
        result = service.get_proposal(proposal_id)
    except LearningError as error:
        _raise_service_http(error)
    return PlanningProposalResponse.model_validate(result)


@router.put(
    "/planning-proposals/{proposal_id}/units/{unit_id}",
    response_model=PlanningProposalResponse,
    tags=["planning"],
)
def update_planning_unit(
    proposal_id: str,
    unit_id: str,
    payload: UpdatePlanningUnitRequest,
    service: LearningServiceDependency,
) -> PlanningProposalResponse:
    try:
        result = service.update_planning_unit(
            proposal_id,
            unit_id,
            **payload.model_dump(),
        )
    except LearningError as error:
        _raise_service_http(error)
    return PlanningProposalResponse.model_validate(result)


@router.post(
    "/planning-proposals/{proposal_id}/status",
    response_model=PlanningProposalResponse,
    tags=["planning"],
)
def update_planning_status(
    proposal_id: str,
    payload: UpdatePlanningStatusRequest,
    service: LearningServiceDependency,
) -> PlanningProposalResponse:
    try:
        result = service.set_proposal_status(proposal_id, payload.status)
    except LearningError as error:
        _raise_service_http(error)
    return PlanningProposalResponse.model_validate(result)


@router.post(
    "/source-check-runs",
    response_model=SourceCheckRunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["sources"],
)
def create_source_check_run(
    payload: CreateSourceCheckRequest,
    service: LearningServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> SourceCheckRunResponse:
    _require_external_calls(deployment_guard)
    try:
        result = service.check_sources(**payload.model_dump())
    except LearningError as error:
        _raise_service_http(error)
    return SourceCheckRunResponse.model_validate(result)


@router.get(
    "/source-change-candidates",
    response_model=list[SourceChangeCandidateResponse],
    tags=["sources"],
)
def list_source_change_candidates(
    service: LearningServiceDependency,
    skill_id: Annotated[str, Query(min_length=1, max_length=100)],
    skill_version: Annotated[str, Query(min_length=1, max_length=50)],
) -> list[SourceChangeCandidateResponse]:
    return [
        SourceChangeCandidateResponse.model_validate(item)
        for item in service.list_change_candidates(skill_id, skill_version)
    ]


@router.post(
    "/source-change-candidates/{candidate_id}/decision",
    response_model=SourceChangeCandidateResponse,
    tags=["sources"],
)
def resolve_source_change_candidate(
    candidate_id: str,
    payload: ResolveSourceChangeRequest,
    service: LearningServiceDependency,
) -> SourceChangeCandidateResponse:
    try:
        result = service.resolve_change_candidate(candidate_id, payload.decision)
    except LearningError as error:
        _raise_service_http(error)
    return SourceChangeCandidateResponse.model_validate(result)


@router.get(
    "/settings/notifications",
    response_model=NotificationPreferenceResponse,
    tags=["settings"],
)
def get_notification_preferences(
    service: NotificationServiceDependency,
) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse.model_validate(service.get_preferences())


@router.put(
    "/settings/notifications",
    response_model=NotificationPreferenceResponse,
    tags=["settings"],
)
def update_notification_preferences(
    payload: UpdateNotificationPreferenceRequest,
    service: NotificationServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> NotificationPreferenceResponse:
    if payload.email_enabled:
        _require_external_calls(deployment_guard)
    try:
        result = service.update_preferences(**payload.model_dump())
    except NotificationError as error:
        _raise_service_http(error)
    return NotificationPreferenceResponse.model_validate(result)


@router.post(
    "/settings/notifications/test-email",
    response_model=NotificationResponse,
    tags=["settings"],
)
def send_test_email(
    service: NotificationServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> NotificationResponse:
    _require_external_calls(deployment_guard)
    try:
        result = service.send_test_email()
    except NotificationError as error:
        _raise_service_http(error)
    return NotificationResponse.model_validate(result)


@router.get(
    "/notifications",
    response_model=list[NotificationResponse],
    tags=["notifications"],
)
def list_notifications(
    service: NotificationServiceDependency,
    include_archived: bool = False,
) -> list[NotificationResponse]:
    return [
        NotificationResponse.model_validate(item)
        for item in service.list_notifications(include_archived)
    ]


@router.post(
    "/notifications/email-outbox/process",
    response_model=EmailOutboxProcessResponse,
    tags=["notifications"],
)
def process_email_outbox(
    service: NotificationServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> EmailOutboxProcessResponse:
    _require_external_calls(deployment_guard)
    return EmailOutboxProcessResponse.model_validate(service.process_outbox())


@router.post(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    tags=["notifications"],
)
def mark_notification_read(
    notification_id: str,
    service: NotificationServiceDependency,
) -> NotificationResponse:
    try:
        result = service.mark_read(notification_id)
    except NotificationError as error:
        _raise_service_http(error)
    return NotificationResponse.model_validate(result)


@router.post(
    "/notifications/{notification_id}/archive",
    response_model=NotificationResponse,
    tags=["notifications"],
)
def archive_notification(
    notification_id: str,
    service: NotificationServiceDependency,
) -> NotificationResponse:
    try:
        result = service.archive(notification_id)
    except NotificationError as error:
        _raise_service_http(error)
    return NotificationResponse.model_validate(result)


@router.get(
    "/ai/providers",
    response_model=list[AiProviderResponse],
    tags=["ai-configuration"],
)
def list_ai_providers(
    service: AiConfigurationServiceDependency,
) -> list[AiProviderResponse]:
    return [AiProviderResponse.model_validate(item) for item in service.list_providers()]


@router.get(
    "/ai/provider-profiles",
    response_model=list[AiProviderProfileResponse],
    tags=["ai-configuration"],
)
def list_ai_provider_profiles(
    service: AiConfigurationServiceDependency,
) -> list[AiProviderProfileResponse]:
    return [AiProviderProfileResponse.model_validate(item) for item in service.list_profiles()]


@router.post(
    "/ai/provider-profiles",
    response_model=AiProviderProfileResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["ai-configuration"],
)
def create_ai_provider_profile(
    payload: CreateAiProviderProfileRequest,
    service: AiConfigurationServiceDependency,
) -> AiProviderProfileResponse:
    try:
        result = service.create_profile(**payload.model_dump())
    except AiConfigurationError as error:
        _raise_service_http(error)
    return AiProviderProfileResponse.model_validate(result)


@router.get(
    "/learning-plan-options",
    response_model=list[PlanningOptionResponse],
    tags=["learning-execution"],
)
def list_learning_planning_options(
    service: LearningExecutionServiceDependency,
    skill_id: str = Query(min_length=1, max_length=100),
    skill_version: str = Query(min_length=1, max_length=50),
) -> list[PlanningOptionResponse]:
    try:
        result = service.list_planning_options(skill_id, skill_version)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return [PlanningOptionResponse.model_validate(item) for item in result]


@router.post(
    "/learning-runs",
    response_model=LearningRunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["learning-execution"],
)
def create_learning_run(
    payload: CreateLearningRunRequest,
    service: LearningExecutionServiceDependency,
) -> LearningRunResponse:
    try:
        result = service.create_run(**payload.model_dump())
    except LearningExecutionError as error:
        _raise_service_http(error)
    return LearningRunResponse.model_validate(result)


@router.get(
    "/learning-runs/active",
    response_model=LearningRunResponse,
    tags=["learning-execution"],
)
def get_active_learning_run(
    service: LearningExecutionServiceDependency,
    skill_id: str = Query(min_length=1, max_length=100),
    skill_version: str = Query(min_length=1, max_length=50),
) -> LearningRunResponse:
    try:
        result = service.get_active_run(skill_id, skill_version)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return LearningRunResponse.model_validate(result)


@router.get(
    "/learning-run-latest",
    response_model=LearningRunResponse,
    tags=["learning-execution"],
)
def get_latest_learning_run(
    service: LearningExecutionServiceDependency,
    skill_id: str = Query(min_length=1, max_length=100),
    skill_version: str = Query(min_length=1, max_length=50),
) -> LearningRunResponse:
    try:
        result = service.get_latest_run(skill_id, skill_version)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return LearningRunResponse.model_validate(result)


@router.get(
    "/learning-runs/{run_id}",
    response_model=LearningRunResponse,
    tags=["learning-execution"],
)
def get_learning_run(
    run_id: str,
    service: LearningExecutionServiceDependency,
) -> LearningRunResponse:
    try:
        result = service.get_run(run_id)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return LearningRunResponse.model_validate(result)


@router.post(
    "/learning-runs/{run_id}/today",
    response_model=TodayLearningResponse,
    tags=["learning-execution"],
)
def generate_today_learning(
    run_id: str,
    payload: TodayLearningRequest,
    service: LearningExecutionServiceDependency,
) -> TodayLearningResponse:
    try:
        result = service.today(run_id, payload.available_minutes)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return TodayLearningResponse.model_validate(result)


@router.post(
    "/learning-activities/{activity_id}/attempts",
    response_model=ActivityAttemptSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["learning-execution"],
)
def submit_learning_activity_attempt(
    activity_id: str,
    payload: SubmitActivityAttemptRequest,
    service: LearningExecutionServiceDependency,
) -> ActivityAttemptSubmissionResponse:
    try:
        result = service.submit_attempt(activity_id, **payload.model_dump())
    except LearningExecutionError as error:
        _raise_service_http(error)
    return ActivityAttemptSubmissionResponse.model_validate(result)


@router.get(
    "/runner/availability",
    response_model=RunnerAvailabilityResponse,
    tags=["runner-4b"],
)
def get_runner_availability(
    service: LearningExecutionServiceDependency,
) -> RunnerAvailabilityResponse:
    return RunnerAvailabilityResponse.model_validate(service.runner_availability())


@router.post(
    "/activity-attempts/{attempt_id}/execute",
    response_model=ExecuteRunnerAttemptResponse,
    tags=["runner-4b"],
)
def execute_runner_attempt(
    attempt_id: str,
    service: LearningExecutionServiceDependency,
) -> ExecuteRunnerAttemptResponse:
    try:
        result = service.execute_attempt(attempt_id)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return ExecuteRunnerAttemptResponse.model_validate(result)


@router.post(
    "/learning-activities/{activity_id}/attempts/{attempt_id}/corrections",
    response_model=ActivityAttemptSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["learning-execution"],
)
def correct_learning_activity_attempt(
    activity_id: str,
    attempt_id: str,
    payload: SubmitActivityAttemptRequest,
    service: LearningExecutionServiceDependency,
) -> ActivityAttemptSubmissionResponse:
    try:
        result = service.submit_attempt(
            activity_id,
            submission=payload.submission,
            corrects_attempt_id=attempt_id,
            mark_uncertain=payload.mark_uncertain,
        )
    except LearningExecutionError as error:
        _raise_service_http(error)
    return ActivityAttemptSubmissionResponse.model_validate(result)


@router.post(
    "/activity-attempts/{attempt_id}/self-review",
    response_model=SelfReviewAttemptResponse,
    tags=["learning-execution"],
)
def self_review_activity_attempt(
    attempt_id: str,
    payload: SelfReviewAttemptRequest,
    service: LearningExecutionServiceDependency,
) -> SelfReviewAttemptResponse:
    try:
        result = service.self_review_attempt(attempt_id, **payload.model_dump())
    except LearningExecutionError as error:
        _raise_service_http(error)
    return SelfReviewAttemptResponse.model_validate(result)


@router.get(
    "/learning-runs/{run_id}/evidence",
    response_model=LearningEvidenceResponse,
    tags=["learning-execution"],
)
def get_learning_evidence(
    run_id: str,
    service: LearningExecutionServiceDependency,
) -> LearningEvidenceResponse:
    try:
        result = service.get_evidence(run_id)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return LearningEvidenceResponse.model_validate(result)


@router.get(
    "/learning-runs/{run_id}/reviews",
    response_model=list[ReviewTaskResponse],
    tags=["learning-execution"],
)
def get_learning_reviews(
    run_id: str,
    service: LearningExecutionServiceDependency,
) -> list[ReviewTaskResponse]:
    try:
        result = service.get_reviews(run_id)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return [ReviewTaskResponse.model_validate(item) for item in result]


@router.post(
    "/review-tasks/{review_id}/start",
    response_model=StartReviewResponse,
    tags=["learning-execution"],
)
def start_learning_review(
    review_id: str,
    service: LearningExecutionServiceDependency,
) -> StartReviewResponse:
    try:
        result = service.start_review(review_id)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return StartReviewResponse.model_validate(result)


@router.post(
    "/learning-runs/{run_id}/end",
    response_model=LearningRunResponse,
    tags=["learning-execution"],
)
def end_learning_run(
    run_id: str,
    service: LearningExecutionServiceDependency,
) -> LearningRunResponse:
    try:
        result = service.end_run(run_id)
    except LearningExecutionError as error:
        _raise_service_http(error)
    return LearningRunResponse.model_validate(result)


@router.get(
    "/readiness/scopes",
    response_model=list[CapabilityScopeResponse],
    tags=["readiness-5a"],
)
def list_readiness_scopes(
    service: ReadinessServiceDependency,
) -> list[CapabilityScopeResponse]:
    return [CapabilityScopeResponse.model_validate(item) for item in service.list_scopes()]


@router.post(
    "/readiness/goals",
    response_model=UserGoalResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["readiness-5a"],
)
def select_readiness_goal(
    payload: SelectUserGoalRequest,
    service: ReadinessServiceDependency,
) -> UserGoalResponse:
    try:
        result = service.select_goal(**payload.model_dump())
    except ReadinessError as error:
        _raise_service_http(error)
    return UserGoalResponse.model_validate(result)


@router.get(
    "/readiness/goals/current",
    response_model=UserGoalResponse | None,
    tags=["readiness-5a"],
)
def get_current_readiness_goal(
    service: ReadinessServiceDependency,
    skill_id: str = Query(min_length=1, max_length=100),
    skill_version: str = Query(min_length=1, max_length=50),
    capability_scope_id: str = Query(min_length=1, max_length=100),
) -> UserGoalResponse | None:
    result = service.get_current_goal(
        skill_id,
        skill_version,
        capability_scope_id,
    )
    return None if result is None else UserGoalResponse.model_validate(result)


@router.get(
    "/readiness/market-snapshots",
    response_model=list[MarketSnapshotResponse],
    tags=["readiness-5a"],
)
def list_readiness_market_snapshots(
    service: ReadinessServiceDependency,
) -> list[MarketSnapshotResponse]:
    return [MarketSnapshotResponse.model_validate(item) for item in service.list_market_snapshots()]


@router.post(
    "/readiness/evaluations",
    response_model=ReadinessEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["readiness-5a"],
)
def create_readiness_evaluation(
    payload: CreateReadinessEvaluationRequest,
    service: ReadinessServiceDependency,
) -> ReadinessEvaluationResponse:
    try:
        result = service.evaluate(**payload.model_dump())
    except ReadinessError as error:
        _raise_service_http(error)
    return ReadinessEvaluationResponse.model_validate(result)


@router.post(
    "/readiness/comparisons",
    response_model=PathComparisonResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["readiness-5a"],
)
def create_path_comparison(
    payload: CreatePathComparisonRequest,
    service: ReadinessServiceDependency,
) -> PathComparisonResponse:
    try:
        result = service.create_comparison(payload.evaluation_id)
    except ReadinessError as error:
        _raise_service_http(error)
    return PathComparisonResponse.model_validate(result)


@router.post(
    "/readiness/comparisons/{comparison_id}/decisions",
    response_model=PathComparisonDecisionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["readiness-5a"],
)
def decide_path_comparison(
    comparison_id: str,
    payload: DecidePathComparisonRequest,
    service: ReadinessServiceDependency,
) -> PathComparisonDecisionResponse:
    try:
        result = service.decide_comparison(comparison_id, **payload.model_dump())
    except ReadinessError as error:
        _raise_service_http(error)
    return PathComparisonDecisionResponse.model_validate(result)


@router.get(
    "/readiness/goals/{goal_selection_id}/history",
    response_model=ReadinessHistoryResponse,
    tags=["readiness-5a"],
)
def get_readiness_history(
    goal_selection_id: str,
    service: ReadinessServiceDependency,
) -> ReadinessHistoryResponse:
    try:
        result = service.get_history(goal_selection_id)
    except ReadinessError as error:
        _raise_service_http(error)
    return ReadinessHistoryResponse.model_validate(result)


@router.get(
    "/market-research/overview",
    response_model=MarketResearchOverviewResponse,
    tags=["market-research-5b"],
)
def get_market_research_overview(
    service: MarketResearchServiceDependency,
    goal_selection_id: str | None = Query(default=None, max_length=36),
) -> MarketResearchOverviewResponse:
    return MarketResearchOverviewResponse.model_validate(
        service.overview(goal_selection_id=goal_selection_id)
    )


@router.get(
    "/market-research/history",
    response_model=MarketResearchHistoryResponse,
    tags=["market-research-5b"],
)
def get_market_research_history(
    service: MarketResearchServiceDependency,
    limit: int = Query(default=20, ge=1, le=100),
) -> MarketResearchHistoryResponse:
    return MarketResearchHistoryResponse.model_validate(service.history(limit=limit))


@router.post(
    "/market-research/runs",
    response_model=MarketResearchRunResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["market-research-5b"],
)
def create_market_research_run(
    payload: CreateMarketResearchRunRequest,
    service: MarketResearchServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> MarketResearchRunResponse:
    _require_external_calls(deployment_guard)
    try:
        result = service.create_run(**payload.model_dump())
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.get(
    "/market-research/runs/{run_id}",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def get_market_research_run(
    run_id: str,
    service: MarketResearchServiceDependency,
) -> MarketResearchRunResponse:
    try:
        result = service.get_run(run_id)
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.post(
    "/market-research/runs/{run_id}/synthesis",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def synthesize_market_research_run(
    run_id: str,
    payload: SynthesizeMarketResearchRequest,
    service: MarketResearchServiceDependency,
    deployment_guard: DeploymentGuardDependency,
) -> MarketResearchRunResponse:
    _require_external_calls(deployment_guard)
    try:
        result = service.synthesize(run_id, **payload.model_dump())
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.post(
    "/market-research/runs/{run_id}/recover-pre-dispatch",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def recover_pre_dispatch_market_research_run(
    run_id: str,
    payload: RecoverPreDispatchMarketResearchRequest,
    service: MarketResearchServiceDependency,
) -> MarketResearchRunResponse:
    try:
        result = service.recover_pre_dispatch_failure(
            run_id,
            **payload.model_dump(),
        )
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.post(
    "/market-research/runs/{run_id}/complete-metadata-only",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def complete_market_research_metadata_only(
    run_id: str,
    service: MarketResearchServiceDependency,
) -> MarketResearchRunResponse:
    try:
        result = service.complete_metadata_only(run_id)
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.post(
    "/market-research/runs/{run_id}/review",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def review_market_research_run(
    run_id: str,
    payload: ReviewMarketResearchRequest,
    service: MarketResearchServiceDependency,
) -> MarketResearchRunResponse:
    try:
        result = service.review(run_id, **payload.model_dump())
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.post(
    "/market-research/runs/{run_id}/sources/{source_id}/redact",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def redact_market_research_source(
    run_id: str,
    source_id: str,
    payload: RedactMarketSourceRequest,
    service: MarketResearchServiceDependency,
) -> MarketResearchRunResponse:
    try:
        result = service.redact_source_excerpt(
            run_id,
            source_id,
            **payload.model_dump(),
        )
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.post(
    "/market-research/runs/{run_id}/reconcile-recovery",
    response_model=MarketResearchRunResponse,
    tags=["market-research-5b"],
)
def reconcile_market_research_recovery(
    run_id: str,
    payload: ReconcileMarketResearchRequest,
    service: MarketResearchServiceDependency,
) -> MarketResearchRunResponse:
    try:
        result = service.reconcile_recovery(run_id, **payload.model_dump())
    except MarketResearchError as error:
        _raise_service_http(error)
    return MarketResearchRunResponse.model_validate(result)


@router.get(
    "/experiments",
    response_model=list[ExperimentResponse],
    tags=["experiments-5c"],
)
def list_experiments(
    service: ExperimentServiceDependency,
    goal_selection_id: str | None = Query(default=None, max_length=36),
) -> list[ExperimentResponse]:
    return [
        ExperimentResponse.model_validate(item)
        for item in service.list_experiments(goal_selection_id)
    ]


@router.post(
    "/experiments",
    response_model=ExperimentResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["experiments-5c"],
)
def create_experiment(
    payload: CreateExperimentRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.create_experiment(
            goal_selection_id=payload.goal_selection_id,
            learning_run_id=payload.learning_run_id,
            market_research_run_id=payload.market_research_run_id,
            plan=payload.plan.model_dump(mode="json"),
        )
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.get(
    "/experiments/{experiment_id}",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def get_experiment(
    experiment_id: str,
    service: ExperimentServiceDependency,
    reveal_income: bool = Query(default=False),
) -> ExperimentResponse:
    try:
        result = service.get_experiment(experiment_id, reveal_income=reveal_income)
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/reviews",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def add_experiment_review(
    experiment_id: str,
    payload: ExperimentReviewRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.add_independent_review(experiment_id, **payload.model_dump())
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/gate-evaluations",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def reevaluate_experiment_gate(
    experiment_id: str,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.reevaluate_gate(experiment_id)
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/transitions",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def transition_experiment(
    experiment_id: str,
    payload: ExperimentTransitionRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.transition(experiment_id, **payload.model_dump())
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/actions",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def record_experiment_action(
    experiment_id: str,
    payload: ExperimentActionRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.record_external_action(experiment_id, **payload.model_dump())
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/outcomes",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def record_experiment_outcome(
    experiment_id: str,
    payload: ExperimentOutcomeRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.record_outcome(experiment_id, **payload.model_dump())
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/income",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def create_experiment_income(
    experiment_id: str,
    payload: CreateIncomeRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.create_income(
            experiment_id,
            values=payload.values.model_dump(mode="json"),
            confirm_manual_record=payload.confirm_manual_record,
        )
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/income/{income_record_id}/revisions",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def revise_experiment_income(
    experiment_id: str,
    income_record_id: str,
    payload: ReviseIncomeRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.revise_income(
            experiment_id,
            income_record_id,
            values=payload.values.model_dump(mode="json"),
            confirm_revision=payload.confirm_revision,
        )
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/income/{income_record_id}/redact",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def redact_experiment_income(
    experiment_id: str,
    income_record_id: str,
    payload: RedactIncomeRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.redact_income(
            experiment_id,
            income_record_id,
            **payload.model_dump(),
        )
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/feedback",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def create_experiment_feedback(
    experiment_id: str,
    payload: CreateFeedbackRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.create_feedback(experiment_id, **payload.model_dump())
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/feedback/{feedback_id}/decisions",
    response_model=ExperimentResponse,
    tags=["experiments-5c"],
)
def decide_experiment_feedback(
    experiment_id: str,
    feedback_id: str,
    payload: DecideFeedbackRequest,
    service: ExperimentServiceDependency,
) -> ExperimentResponse:
    try:
        result = service.decide_feedback(
            experiment_id,
            feedback_id,
            **payload.model_dump(),
        )
    except ExperimentError as error:
        _raise_service_http(error)
    return ExperimentResponse.model_validate(result)


@router.post(
    "/experiments/{experiment_id}/exports",
    response_class=Response,
    tags=["experiments-5c"],
)
def export_experiment(
    experiment_id: str,
    payload: ExportExperimentRequest,
    service: ExperimentServiceDependency,
) -> Response:
    try:
        media_type, content = service.export_experiment(
            experiment_id,
            **payload.model_dump(),
        )
    except ExperimentError as error:
        _raise_service_http(error)
    extension = "json" if payload.export_format == "json" else "csv"
    return Response(
        content=content.encode("utf-8-sig") if extension == "csv" else content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="cloud-study-experiment-{experiment_id}.{extension}"'
            )
        },
    )
