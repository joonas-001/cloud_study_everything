from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from cloud_study_api.diagnostics import DiagnosticError, DiagnosticService


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


router = APIRouter()


def get_diagnostic_service(request: Request) -> DiagnosticService:
    service: DiagnosticService = request.app.state.diagnostic_service
    return service


DiagnosticServiceDependency = Annotated[
    DiagnosticService,
    Depends(get_diagnostic_service),
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
