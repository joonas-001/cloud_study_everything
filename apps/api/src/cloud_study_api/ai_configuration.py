# ruff: noqa: RUF001

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.credentials import CredentialStore, CredentialStoreError
from cloud_study_api.models import AiProviderProfile, utc_now


class AiConfigurationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "local-deterministic",
        "display_name": "本地确定性",
        "default_base_url": None,
        "is_external": False,
        "executable": True,
        "models": ["diagnostic-v1", "planner-sim-v1"],
        "capabilities": {
            "streaming": False,
            "tools": False,
            "structured_output": True,
            "model_discovery": False,
        },
        "status_note": "只根据版本化规则生成可复现的诊断路径和规划预览。",
    },
    {
        "id": "openai",
        "display_name": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "is_external": True,
        "executable": False,
        "models": [],
        "capabilities": {
            "streaming": True,
            "tools": True,
            "structured_output": True,
            "model_discovery": True,
        },
        "status_note": "接口已准备；首批模型和费用策略确认前禁止真实调用。",
    },
    {
        "id": "deepseek",
        "display_name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com",
        "is_external": True,
        "executable": False,
        "models": [],
        "capabilities": {
            "streaming": True,
            "tools": True,
            "structured_output": False,
            "model_discovery": True,
        },
        "status_note": "独立适配器接口；不得因为部分格式兼容而复用 OpenAI 语义。",
    },
    {
        "id": "moonshot",
        "display_name": "Moonshot AI（Kimi）",
        "default_base_url": "https://api.moonshot.cn/v1",
        "is_external": True,
        "executable": False,
        "models": [],
        "capabilities": {
            "streaming": True,
            "tools": True,
            "structured_output": False,
            "model_discovery": True,
        },
        "status_note": "独立适配器接口；首批模型确认前禁止真实调用。",
    },
)


class AiConfigurationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        credential_store: CredentialStore,
        now: Callable[[], Any] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._credential_store = credential_store
        self._now = now
        self._providers = {provider["id"]: provider for provider in PROVIDERS}

    def list_providers(self) -> list[dict[str, Any]]:
        return [dict(provider) for provider in PROVIDERS]

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            profiles = database.scalars(
                select(AiProviderProfile).order_by(AiProviderProfile.created_at)
            ).all()
            return [self._profile_payload(profile) for profile in profiles]

    def create_profile(
        self,
        *,
        provider_id: str,
        display_name: str,
        base_url: str | None,
        api_key: str | None,
        enabled: bool,
    ) -> dict[str, Any]:
        provider = self._providers.get(provider_id)
        if provider is None:
            raise AiConfigurationError(
                422,
                "unsupported_provider",
                "The selected AI provider is not supported.",
            )
        if provider_id == "local-deterministic" and api_key:
            raise AiConfigurationError(
                422,
                "local_provider_forbids_credentials",
                "The local deterministic provider does not use credentials.",
            )
        profile_id = str(uuid4())
        credential_reference: str | None = None
        if api_key:
            credential_reference = f"cloud-study/ai/{profile_id}"
            try:
                self._credential_store.put(
                    credential_reference,
                    api_key,
                    display_name,
                )
            except CredentialStoreError as error:
                raise AiConfigurationError(
                    409,
                    "credential_store_unavailable",
                    str(error),
                ) from error
        now = self._now()
        with self._session_factory() as database:
            profile = AiProviderProfile(
                id=profile_id,
                provider_id=provider_id,
                display_name=display_name.strip(),
                base_url=(base_url or provider["default_base_url"]),
                credential_reference=credential_reference,
                enabled=enabled,
                created_at=now,
                updated_at=now,
            )
            database.add(profile)
            try:
                database.commit()
            except Exception:
                if credential_reference:
                    with suppress(CredentialStoreError):
                        self._credential_store.delete(credential_reference)
                raise
            return self._profile_payload(profile)

    def _profile_payload(self, profile: AiProviderProfile) -> dict[str, Any]:
        provider = self._providers[profile.provider_id]
        return {
            "id": profile.id,
            "provider_id": profile.provider_id,
            "display_name": profile.display_name,
            "base_url": profile.base_url,
            "credential_reference": profile.credential_reference,
            "enabled": profile.enabled,
            "executable": provider["executable"],
            "status_note": provider["status_note"],
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }
