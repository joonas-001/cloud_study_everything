from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cloud_study_api.ai_configuration import AiConfigurationService
from cloud_study_api.capability_profiles import CapabilityProfileService
from cloud_study_api.config import Settings
from cloud_study_api.content_locking import validate_or_backfill_persisted_content_locks
from cloud_study_api.credentials import create_credential_store
from cloud_study_api.database import (
    create_session_factory,
    upgrade_database,
)
from cloud_study_api.deployment import DeploymentGuard
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.execution import LearningExecutionService
from cloud_study_api.experiments import ExperimentService
from cloud_study_api.governance import validate_repository
from cloud_study_api.issue_reporting import IssueReportService
from cloud_study_api.learning import LearningService
from cloud_study_api.market_research import MarketResearchService
from cloud_study_api.notifications import NotificationService
from cloud_study_api.providers import ProviderRegistry
from cloud_study_api.readiness import ReadinessService
from cloud_study_api.routes import router
from cloud_study_api.runner import UnixSocketRunnerBackend
from cloud_study_api.security import enforce_deployment_security


class HealthResponse(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_environment()
    packages = validate_repository(settings.repository_root)
    upgrade_database(settings.database_path, settings.repository_root)
    session_factory = create_session_factory(settings.database_path)
    validate_or_backfill_persisted_content_locks(session_factory, packages)
    credential_store = create_credential_store()
    notification_service = NotificationService(
        session_factory=session_factory,
        credential_store=credential_store,
    )
    app.state.settings = settings
    app.state.deployment_guard = DeploymentGuard(settings.deployment)
    app.state.diagnostic_service = DiagnosticService(
        repository_root=settings.repository_root,
        packages=packages,
        session_factory=session_factory,
        provider_registry=ProviderRegistry(),
    )
    app.state.notification_service = notification_service
    app.state.issue_report_service = IssueReportService(
        repository_root=settings.repository_root,
        session_factory=session_factory,
        deployment_status=app.state.deployment_guard.status(),
    )
    app.state.learning_service = LearningService(
        repository_root=settings.repository_root,
        packages=packages,
        session_factory=session_factory,
        notification_service=notification_service,
    )
    runner_backend = None
    if settings.deployment.mode == "private_preview" and settings.deployment.remote_runner_enabled:
        runner_socket_path = settings.deployment.runner_socket_path
        if runner_socket_path is None:
            raise RuntimeError("remote Runner is enabled without a broker socket")
        runner_backend = UnixSocketRunnerBackend(runner_socket_path)
    learning_execution_service = LearningExecutionService(
        repository_root=settings.repository_root,
        packages=packages,
        session_factory=session_factory,
        notification_service=notification_service,
        runner_execution_enabled=(
            settings.deployment.mode == "local" or settings.deployment.remote_runner_enabled
        ),
        runner_backend=runner_backend,
    )
    learning_execution_service.recover_stale_runner_invocations()
    app.state.learning_execution_service = learning_execution_service
    app.state.capability_profile_service = CapabilityProfileService(
        repository_root=settings.repository_root,
        packages=packages,
        session_factory=session_factory,
    )
    app.state.readiness_service = ReadinessService(
        repository_root=settings.repository_root,
        packages=packages,
        session_factory=session_factory,
    )
    app.state.ai_configuration_service = AiConfigurationService(
        session_factory=session_factory,
        credential_store=credential_store,
    )
    app.state.market_research_service = MarketResearchService(
        repository_root=settings.repository_root,
        session_factory=session_factory,
        credential_store=credential_store,
    )
    app.state.experiment_service = ExperimentService(
        repository_root=settings.repository_root,
        packages=packages,
        session_factory=session_factory,
    )
    try:
        yield
    finally:
        session_factory.kw["bind"].dispose()


app = FastAPI(
    title="云奕学 API",
    version="0.1.0",
    description="Local or owner-only private API for the AI skill learning platform.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"http://(?:localhost|127\.0\.0\.1)(?::\d+)?$",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type"],
)
app.middleware("http")(enforce_deployment_security)
app.include_router(router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")
