from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from cloud_study_api.ai_configuration import (
    AiConfigurationError,
    AiConfigurationService,
)
from cloud_study_api.diagnostics import DiagnosticError, DiagnosticService
from cloud_study_api.learning import LearningError, LearningService
from cloud_study_api.notifications import NotificationError, NotificationService


class PrivacySettingsResponse(BaseModel):
    external_ai_enabled: bool
    inactivity_timeout_minutes: int
    updated_at: datetime


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
    response_type: Literal["free_text", "code_text"]


class DiagnosticAnswerResponse(BaseModel):
    id: str
    question_id: str
    response_kind: Literal["answered", "skipped", "uncertain"]
    content: str | None
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
    status: Literal["draft", "saved_preview", "rejected"]
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
    status: Literal["baseline_created", "unchanged", "changed", "failed", "manual"]
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
    base_url: str | None = Field(default=None, max_length=2000)
    api_key: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool = True


class AiProviderProfileResponse(BaseModel):
    id: str
    provider_id: str
    display_name: str
    base_url: str | None
    credential_reference: str | None
    enabled: bool
    executable: bool
    status_note: str
    created_at: datetime
    updated_at: datetime


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
    error: LearningError | NotificationError | AiConfigurationError,
) -> None:
    context = error.context if isinstance(error, LearningError) else {}
    raise HTTPException(
        status_code=error.status_code,
        detail={
            "code": error.code,
            "message": str(error),
            "context": context,
        },
    ) from error


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
) -> PrivacySettingsResponse:
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
) -> DiagnosticSessionResponse:
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
) -> SourceCheckRunResponse:
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
) -> NotificationPreferenceResponse:
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
) -> NotificationResponse:
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
) -> EmailOutboxProcessResponse:
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
