from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel

from cloud_study_api.config import Settings
from cloud_study_api.database import read_schema_version, upgrade_database
from cloud_study_api.governance import validate_repository


class HealthResponse(BaseModel):
    status: str
    service: str
    database_schema_version: str
    registered_skill_packages: int


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_environment()
    packages = validate_repository(settings.repository_root)
    upgrade_database(settings.database_path, settings.repository_root)
    app.state.settings = settings
    app.state.registered_skill_packages = len(packages)
    yield


app = FastAPI(
    title="Cloud Study API",
    version="0.1.0",
    description="Local API for the AI skill learning platform.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service="cloud-study-api",
        database_schema_version=read_schema_version(settings.database_path),
        registered_skill_packages=request.app.state.registered_skill_packages,
    )
