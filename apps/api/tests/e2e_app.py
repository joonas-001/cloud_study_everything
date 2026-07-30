# ruff: noqa: RUF001

"""Offline-only FastAPI host for Playwright market-research flows."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body
from sqlalchemy import delete

import cloud_study_api.main as production_main
from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.market_research import HttpResponse, MarketResearchService
from cloud_study_api.models import (
    MarketResearchEvent,
    MarketResearchRun,
    MarketResearchSynthesisAttempt,
)

OFFLINE_CREDENTIAL = "-".join(("offline", "e2e", "credential"))


class OfflineE2EMarketTransport:
    """Deterministic transport that never opens a network connection."""

    def __init__(self) -> None:
        self.response_mode = "success"

    def get(self, url: str, allowed_hosts: set[str]) -> HttpResponse:
        assert url.startswith("https://")
        assert any(host in url for host in allowed_hosts)
        if url.endswith("/robots.txt"):
            return HttpResponse(
                status=404,
                headers={"content-type": "text/plain"},
                body=b"",
                final_url=url,
            )
        if "api-docs.deepseek.com" in url:
            body = (
                "<html><body><table>"
                "<tr><th>模型</th><th>deepseek-v4-flash</th></tr>"
                "<tr><td>百万tokens输入（缓存命中）</td><td>0.02元</td></tr>"
                "<tr><td>百万tokens输入（缓存未命中）</td><td>1元</td></tr>"
                "<tr><td>百万tokens输出</td><td>2元</td></tr>"
                "</table></body></html>"
            )
            return HttpResponse(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=body.encode(),
                final_url=url,
            )
        source_id = url.rsplit("/", 1)[-1] or "official"
        return HttpResponse(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=(
                "<html><body>官方公开市场背景与岗位统计，"
                f"离线测试来源 {source_id}，初级 C++ 后端与算法应用工程。</body></html>"
            ).encode(),
            final_url=url,
        )

    def post_json(
        self,
        url: str,
        *,
        api_key: str,
        payload: dict[str, Any],
        allowed_hosts: set[str],
    ) -> HttpResponse:
        assert url == "https://api.deepseek.com/chat/completions"
        assert api_key == OFFLINE_CREDENTIAL
        assert payload["model"] == "deepseek-v4-flash"
        assert allowed_hosts == {"api.deepseek.com"}
        synthesis = {
            "background_summaries": [
                {
                    "path": path,
                    "summary": "离线官方材料只显示宏观背景。",
                    "source_ids": ["cn-nbs-data"],
                    "uncertainty": "不能据此判断具体岗位、订单或产品需求。",
                }
                for path in ("employment", "freelancing", "productization")
            ],
            "limitations": ["离线替身只验证产品闭环，不代表真实市场结论。"],
        }
        response = {
            "model": (
                "deepseek-v4-flash"
                if self.response_mode == "success"
                else "unexpected-offline-model"
            ),
            "choices": [{"message": {"content": json.dumps(synthesis, ensure_ascii=False)}}],
            "usage": {
                "prompt_tokens": 1_000,
                "prompt_cache_hit_tokens": 100,
                "completion_tokens": 200,
            },
        }
        return HttpResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=json.dumps(response, ensure_ascii=False).encode(),
            final_url=url,
        )


credential_store = MemoryCredentialStore()
transport = OfflineE2EMarketTransport()
original_lifespan = production_main.lifespan


@asynccontextmanager
async def offline_e2e_lifespan(app: Any) -> AsyncIterator[None]:
    original_store_factory = production_main.create_credential_store
    production_main.create_credential_store = lambda: credential_store
    try:
        async with original_lifespan(app):
            profile_service = app.state.ai_configuration_service
            profiles = profile_service.list_profiles()
            if not any(profile["provider_id"] == "deepseek" for profile in profiles):
                profile_service.create_profile(
                    provider_id="deepseek",
                    display_name="离线 E2E DeepSeek",
                    model_id="deepseek-v4-flash",
                    base_url="https://api.deepseek.com",
                    api_key=OFFLINE_CREDENTIAL,
                    enabled=True,
                )
            session_factory = profile_service._session_factory
            app.state.market_research_service = MarketResearchService(
                repository_root=app.state.settings.repository_root,
                session_factory=session_factory,
                credential_store=credential_store,
                transport=transport,
            )
            app.state.e2e_session_factory = session_factory
            yield
    finally:
        production_main.create_credential_store = original_store_factory


app = production_main.app
app.router.lifespan_context = offline_e2e_lifespan


@app.post("/__e2e__/market-reset", include_in_schema=False)
def reset_market_research(mode: str = Body(embed=True)) -> dict[str, str]:
    if mode not in {"success", "model_mismatch"}:
        raise ValueError("unsupported offline E2E mode")
    with app.state.e2e_session_factory() as database:
        database.execute(delete(MarketResearchEvent))
        database.execute(delete(MarketResearchSynthesisAttempt))
        database.execute(delete(MarketResearchRun))
        database.commit()
    transport.response_mode = mode
    return {"mode": mode}
