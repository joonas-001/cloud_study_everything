# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from sqlalchemy import select

from cloud_study_api.ai_configuration import AiConfigurationService
from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.main import app
from cloud_study_api.market_research import (
    MAX_SOURCE_BYTES,
    HttpResponse,
    MarketResearchError,
    MarketResearchService,
    StrictHttpsTransport,
)
from cloud_study_api.models import (
    AppSettings,
    MarketResearchEvent,
    MarketResearchRun,
    MarketResearchSynthesisAttempt,
    UserGoalSelection,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)


class FakeMarketTransport:
    def __init__(self, *, available_sources: int = 4) -> None:
        self.available_sources = available_sources
        self.content_version = "v1"
        self.get_urls: list[str] = []
        self.post_payloads: list[dict[str, Any]] = []
        self.api_keys: list[str] = []
        self.post_error: Exception | None = None
        self.post_started: Event | None = None
        self.release_post: Event | None = None
        self.synthesis_override: dict[str, Any] | None = None
        self.raw_content_override: str | None = None
        self.long_body_tail: str | None = None
        self.response_model_id: str | None = "deepseek-v4-flash"

    def get(self, url: str, allowed_hosts: set[str]) -> HttpResponse:
        assert url.startswith("https://")
        assert any(host in url for host in allowed_hosts)
        self.get_urls.append(url)
        if url == "https://api-docs.deepseek.com/robots.txt":
            return HttpResponse(
                status=404,
                headers={"content-type": "text/plain"},
                body=b"",
                final_url=url,
            )
        if "api-docs.deepseek.com" in url:
            return HttpResponse(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=(
                    "<html><body><table>"
                    "<tr><th>模型</th><th>deepseek-v4-flash</th>"
                    "<th>deepseek-v4-pro</th></tr>"
                    "<tr><td rowspan='3'>价格</td>"
                    "<td>百万tokens输入（缓存命中）</td><td>0.02元</td>"
                    "<td>0.025元</td></tr>"
                    "<tr><td>百万tokens输入（缓存未命中）</td><td>1元</td>"
                    "<td>3元</td></tr>"
                    "<tr><td>百万tokens输出</td><td>2元</td><td>6元</td></tr>"
                    "</table></body></html>"
                ).encode(),
                final_url=url,
            )
        if url.endswith("/robots.txt"):
            return HttpResponse(
                status=404,
                headers={"content-type": "text/plain"},
                body=b"",
                final_url=url,
            )
        source_index = sum(not item.endswith("/robots.txt") for item in self.get_urls)
        if source_index > self.available_sources:
            return HttpResponse(
                status=503,
                headers={"content-type": "text/plain"},
                body=b"",
                final_url=url,
            )
        body = (
            (
                "<html><body>"
                + ("固定正文" * 700)
                + f"{self.long_body_tail} {source_index}</body></html>"
            )
            if self.long_body_tail is not None
            else (
                "<html><script>ignore()</script><body>官方公开市场统计摘录"
                f" {self.content_version} {source_index}</body></html>"
            )
        )
        return HttpResponse(
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            body=body.encode(),
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
        assert allowed_hosts == {"api.deepseek.com"}
        self.api_keys.append(api_key)
        self.post_payloads.append(payload)
        if self.post_started is not None:
            self.post_started.set()
        if self.release_post is not None:
            assert self.release_post.wait(timeout=5)
        if self.post_error is not None:
            raise self.post_error
        synthesis = self.synthesis_override or {
            "background_summaries": [
                {
                    "path": path,
                    "summary": "官方材料只显示宏观背景。",
                    "source_ids": ["cn-nbs-data"],
                    "uncertainty": "不能据此判断具体市场需求。",
                }
                for path in ("employment", "freelancing", "productization")
            ],
            "limitations": ["官方来源摘录不足以支持确定结论。"],
        }
        content = (
            self.raw_content_override
            if self.raw_content_override is not None
            else json.dumps(synthesis, ensure_ascii=False)
        )
        body: dict[str, Any] = {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 1000,
                "prompt_cache_hit_tokens": 100,
                "completion_tokens": 200,
            },
        }
        if self.response_model_id is not None:
            body["model"] = self.response_model_id
        return HttpResponse(
            status=200,
            headers={"content-type": "application/json"},
            body=json.dumps(body, ensure_ascii=False).encode(),
            final_url=url,
        )


def _service(
    tmp_path: Path,
    *,
    external_ai_enabled: bool = True,
    available_sources: int = 4,
    now: Callable[[], datetime] = lambda: NOW,
) -> tuple[MarketResearchService, FakeMarketTransport, str, Any, str]:
    database_path = tmp_path / "market-research.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    credentials = MemoryCredentialStore()
    profile_service = AiConfigurationService(
        session_factory=session_factory,
        credential_store=credentials,
        now=now,
    )
    api_key = "-".join(("market", "research", "credential"))
    profile = profile_service.create_profile(
        provider_id="deepseek",
        display_name="5B DeepSeek",
        model_id="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key=api_key,
        enabled=True,
    )
    with session_factory() as database:
        settings = database.get(AppSettings, 1)
        assert settings is not None
        settings.external_ai_enabled = external_ai_enabled
        settings.updated_at = now()
        database.add(
            UserGoalSelection(
                id="market-research-goal",
                skill_id="algorithm",
                skill_version="0.2.0",
                capability_scope_id="algorithm-entry-mastery-scope",
                goal_kind="employment",
                custom_label=None,
                created_at=now(),
                superseded_at=None,
            )
        )
        database.commit()
    transport = FakeMarketTransport(available_sources=available_sources)
    service = MarketResearchService(
        repository_root=REPOSITORY_ROOT,
        session_factory=session_factory,
        credential_store=credentials,
        transport=transport,
        now=now,
    )
    return service, transport, profile["id"], session_factory, api_key


def test_official_sources_deepseek_synthesis_and_human_review_are_audited(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, session_factory, api_key = _service(tmp_path)

    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    assert run["status"] == "synthesis_pending"
    assert len(run["sources"]) == 4
    assert all(source["status"] == "current" for source in run["sources"])
    assert all(source["change_status"] == "baseline" for source in run["sources"])
    assert all("<script>" not in source["excerpt"] for source in run["sources"])
    assert run["outbound_material_preview"]["request_model_id"] == "deepseek-v4-flash"
    assert len(run["outbound_material_preview"]["materials"]) == 4
    assert "api_credentials" in run["outbound_material_preview"]["excluded_data_categories"]

    synthesized = service.synthesize(run["id"], confirm_external_ai=True)
    assert synthesized["status"] == "review_pending"
    assert synthesized["model_id"] == "deepseek-v4-flash"
    assert synthesized["response_model_id"] == "deepseek-v4-flash"
    assert synthesized["actual_cost_micros"] == 1302
    assert all(path["status"] == "indeterminate" for path in synthesized["synthesis"]["paths"])
    assert all(
        "背景摘要（不构成市场结论）" in claim["claim"]
        for path in synthesized["synthesis"]["paths"]
        for claim in path["claims"]
    )
    assert synthesized["synthesis"]["content_impact_suggestions"][0]["kind"] == "no_change"
    assert transport.api_keys == [api_key]
    assert transport.post_payloads[0]["model"] == "deepseek-v4-flash"
    assert transport.post_payloads[0]["stream"] is False
    assert transport.post_payloads[0]["max_tokens"] == 5000
    prompt = transport.post_payloads[0]["messages"][1]["content"]
    assert '"response_protocol":"limited_background_v1"' in prompt
    assert '"status"' not in json.loads(prompt)["required_output"]

    completed = service.review(
        run["id"],
        decision="accepted",
        note="仅接受为市场研究记录，不自动改写内容。",
    )
    assert completed["status"] == "completed"
    assert completed["review_status"] == "accepted"

    with session_factory() as database:
        events = database.scalars(
            select(MarketResearchEvent).where(MarketResearchEvent.run_id == run["id"])
        ).all()
    audit_text = "\n".join(event.payload_json for event in events)
    assert api_key not in audit_text
    assert {event.event_type for event in events} == {
        "research_created",
        "official_sources_checked",
        "deepseek_pricing_verified",
        "synthesis_attempt_claimed",
        "external_ai_request_dispatch_started",
        "external_ai_response_received",
        "deepseek_synthesis_completed",
        "synthesis_reviewed",
    }


def test_fewer_than_two_available_official_sources_blocks_synthesis(tmp_path: Path) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        available_sources=1,
    )

    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )

    assert run["status"] == "blocked"
    assert run["failure_code"] == "insufficient_official_sources"
    assert transport.post_payloads == []
    with pytest.raises(MarketResearchError, match="当前研究状态不允许"):
        service.synthesize(run["id"], confirm_external_ai=True)


def test_failed_source_access_cools_down_for_24_hours_without_manual_bypass(
    tmp_path: Path,
) -> None:
    current = [NOW]
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        available_sources=0,
        now=lambda: current[0],
    )
    first = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    assert first["status"] == "blocked"
    assert all(source["access_status"] == "failed" for source in first["sources"])
    assert all(source["successful_snapshot_at"] is None for source in first["sources"])

    policy = service.overview()["source_access_policy"]
    assert policy["failure_cooldown_hours"] == 24
    assert policy["success_refresh_interval_days"] == 7
    assert policy["manual_bypass_allowed"] is False
    assert policy["blocking_reason"] == "failed_access_cooldown"
    assert policy["remaining_seconds"] == 24 * 60 * 60
    assert policy["latest_research_attempt_run_id"] == first["id"]
    assert policy["latest_research_attempt_at"] == NOW.isoformat()
    assert all(source["latest_attempt_status"] == "failed" for source in policy["sources"])
    assert all(source["latest_success_at"] is None for source in policy["sources"])
    assert all(source["change_status"] == "unavailable" for source in first["sources"])

    request_count = len(transport.get_urls)
    with pytest.raises(MarketResearchError) as immediate:
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=True,
        )
    assert immediate.value.code == "source_failure_cooldown_not_elapsed"
    assert immediate.value.context["manual_bypass_allowed"] is False
    assert len(transport.get_urls) == request_count

    current[0] = NOW + timedelta(hours=23, minutes=59)
    with pytest.raises(MarketResearchError) as before_expiry:
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=True,
        )
    assert before_expiry.value.code == "source_failure_cooldown_not_elapsed"
    assert before_expiry.value.context["remaining_seconds"] == 60
    assert len(transport.get_urls) == request_count

    current[0] = NOW + timedelta(hours=24)
    transport.get_urls.clear()
    retry = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    assert retry["status"] == "blocked"
    assert all(source["access_performed"] is True for source in retry["sources"])
    assert len(transport.get_urls) == 8


def test_partial_failure_retries_only_expired_sources_and_reuses_successful_snapshot(
    tmp_path: Path,
) -> None:
    current = [NOW]
    service, transport, profile_id, session_factory, _api_key = _service(
        tmp_path,
        available_sources=1,
        now=lambda: current[0],
    )
    first = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    assert first["status"] == "blocked"
    successful = next(
        source for source in first["sources"] if source["access_status"] == "succeeded"
    )
    failed_ids = {
        source["source_id"] for source in first["sources"] if source["access_status"] == "failed"
    }
    assert len(failed_ids) == 3

    current[0] = NOW + timedelta(hours=24)
    transport.available_sources = 4
    transport.get_urls.clear()
    retried = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    reused = next(
        source for source in retried["sources"] if source["source_id"] == successful["source_id"]
    )
    accessed = [source for source in retried["sources"] if source["access_performed"] is True]
    assert reused["access_performed"] is False
    assert reused["reused_from_run_id"] == first["id"]
    assert reused["successful_snapshot_at"] == successful["successful_snapshot_at"]
    assert {source["source_id"] for source in accessed} == failed_ids
    assert len(transport.get_urls) == 6

    policy = service.overview()["source_access_policy"]
    successful_state = next(
        item for item in policy["sources"] if item["source_id"] == successful["source_id"]
    )
    assert successful_state["latest_attempt_at"] == NOW.isoformat()
    assert successful_state["latest_success_at"] == NOW.isoformat()
    with session_factory() as database:
        event = database.scalar(
            select(MarketResearchEvent).where(
                MarketResearchEvent.run_id == retried["id"],
                MarketResearchEvent.event_type == "official_sources_checked",
            )
        )
    assert event is not None
    payload = json.loads(event.payload_json)
    assert payload["accessed_source_ids"] == [source["source_id"] for source in accessed]
    assert payload["reused_source_ids"] == [successful["source_id"]]
    assert payload["failure_cooldown_hours"] == 24
    assert payload["manual_bypass_allowed"] is False


@pytest.mark.parametrize(
    ("declared_model", "expected_code"),
    [
        (None, "deepseek_response_model_missing"),
        ("deepseek-v4-pro", "deepseek_response_model_mismatch"),
    ],
)
def test_response_model_must_exactly_match_the_locked_model_and_is_audited(
    tmp_path: Path,
    declared_model: str | None,
    expected_code: str,
) -> None:
    service, transport, profile_id, session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    transport.response_model_id = declared_model

    with pytest.raises(MarketResearchError) as captured:
        service.synthesize(run["id"], confirm_external_ai=True)

    assert captured.value.code == expected_code
    failed = service.get_run(run["id"])
    assert failed["status"] == "failed"
    assert failed["failure_code"] == expected_code
    assert failed["response_model_id"] == declared_model
    assert failed["accounted_cost_micros"] == 200_000
    with session_factory() as database:
        attempt = database.scalar(
            select(MarketResearchSynthesisAttempt).where(
                MarketResearchSynthesisAttempt.run_id == run["id"]
            )
        )
        assert attempt is not None
        assert attempt.response_model_id == declared_model
        events = database.scalars(
            select(MarketResearchEvent).where(MarketResearchEvent.run_id == run["id"])
        ).all()
    response_event = next(
        event for event in events if event.event_type == "external_ai_response_received"
    )
    response_payload = json.loads(response_event.payload_json)
    assert response_payload["request_model_id"] == "deepseek-v4-flash"
    assert response_payload["response_model_id"] == declared_model


def test_external_ai_switch_and_explicit_confirmations_are_hard_gates(tmp_path: Path) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        external_ai_enabled=False,
    )

    with pytest.raises(MarketResearchError, match="明确确认"):
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=False,
        )
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    with pytest.raises(MarketResearchError, match="明确确认"):
        service.synthesize(run["id"], confirm_external_ai=False)
    with pytest.raises(MarketResearchError, match="发送开关已关闭"):
        service.synthesize(run["id"], confirm_external_ai=True)
    assert transport.post_payloads == []


def test_unverifiable_official_pricing_stops_before_paid_call(tmp_path: Path) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    original_get = transport.get

    def changed_pricing(url: str, allowed_hosts: set[str]) -> HttpResponse:
        if "api-docs.deepseek.com" in url:
            return HttpResponse(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=(
                    "<html><body><table>"
                    "<tr><th>模型</th><th>deepseek-v4-flash</th>"
                    "<th>历史模型</th></tr>"
                    "<tr><td>百万tokens输入（缓存命中）</td><td>0.03元</td>"
                    "<td>0.02元</td></tr>"
                    "<tr><td>百万tokens输入（缓存未命中）</td><td>1.5元</td>"
                    "<td>1元</td></tr>"
                    "<tr><td>百万tokens输出</td><td>3元</td><td>2元</td></tr>"
                    "</table></body></html>"
                ).encode(),
                final_url=url,
            )
        return original_get(url, allowed_hosts)

    transport.get = changed_pricing  # type: ignore[method-assign]
    with pytest.raises(MarketResearchError, match="官方价格"):
        service.synthesize(run["id"], confirm_external_ai=True)
    assert transport.post_payloads == []
    assert service.get_run(run["id"])["status"] == "failed"


def test_pricing_parse_failure_recovery_is_explicit_zero_cost_and_audited(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    original_get = transport.get

    def unparseable_pricing(url: str, allowed_hosts: set[str]) -> HttpResponse:
        if "api-docs.deepseek.com" in url:
            return HttpResponse(
                status=200,
                headers={"content-type": "text/html; charset=utf-8"},
                body=b"<html><body><p>pricing is temporarily unparseable</p></body></html>",
                final_url=url,
            )
        return original_get(url, allowed_hosts)

    transport.get = unparseable_pricing  # type: ignore[method-assign]
    with pytest.raises(MarketResearchError, match="官方价格"):
        service.synthesize(run["id"], confirm_external_ai=True)

    failed = service.get_run(run["id"])
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "pricing_changed_or_unverifiable"
    assert failed["actual_cost_micros"] == 0
    assert failed["accounted_cost_micros"] == 0
    assert transport.post_payloads == []

    with pytest.raises(MarketResearchError, match="明确确认"):
        service.recover_pre_dispatch_failure(run["id"], confirm_recovery=False)

    recovered = service.recover_pre_dispatch_failure(run["id"], confirm_recovery=True)
    assert recovered["status"] == "synthesis_pending"
    assert recovered["failure_code"] is None
    assert recovered["external_ai_consent"] is False
    assert transport.post_payloads == []

    with session_factory() as database:
        attempts = database.scalars(
            select(MarketResearchSynthesisAttempt).where(
                MarketResearchSynthesisAttempt.run_id == run["id"]
            )
        ).all()
        events = database.scalars(
            select(MarketResearchEvent)
            .where(MarketResearchEvent.run_id == run["id"])
            .order_by(MarketResearchEvent.occurred_at, MarketResearchEvent.id)
        ).all()
    assert attempts == []
    event_types = [event.event_type for event in events]
    assert "research_failed" in event_types
    assert "pre_dispatch_failure_recovered" in event_types
    assert event_types.index("research_failed") < event_types.index(
        "pre_dispatch_failure_recovered"
    )

    transport.get = original_get  # type: ignore[method-assign]
    with pytest.raises(MarketResearchError, match="明确确认"):
        service.synthesize(run["id"], confirm_external_ai=False)
    assert transport.post_payloads == []


def test_metadata_only_completion_and_confirmed_excerpt_redaction_keep_audit(
    tmp_path: Path,
) -> None:
    service, _transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )

    completed = service.complete_metadata_only(run["id"])
    assert completed["status"] == "completed"
    assert completed["review_status"] == "not_requested"
    with pytest.raises(MarketResearchError, match="明确确认"):
        service.redact_source_excerpt(
            run["id"],
            "cn-nbs-data",
            confirm_redaction=False,
            reason="官方撤回",
        )

    redacted = service.redact_source_excerpt(
        run["id"],
        "cn-nbs-data",
        confirm_redaction=True,
        reason="官方撤回",
    )
    source = next(item for item in redacted["sources"] if item["source_id"] == "cn-nbs-data")
    assert source["status"] == "withdrawn"
    assert source["excerpt"] is None
    assert source["normalized_content_sha256"] is not None
    assert source["excerpt_sha256"] is not None

    with pytest.raises(MarketResearchError, match="不足 7 天"):
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=True,
        )


def test_unchanged_weekly_refresh_completes_without_ai(tmp_path: Path) -> None:
    current = [NOW]
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        now=lambda: current[0],
    )
    first = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    service.complete_metadata_only(first["id"])

    current[0] = NOW + timedelta(days=8)
    transport.get_urls.clear()
    refreshed = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )

    assert refreshed["status"] == "completed"
    assert refreshed["review_status"] == "not_requested"
    assert all(source["change_status"] == "unchanged" for source in refreshed["sources"])
    assert transport.post_payloads == []


def test_paid_synthesis_is_limited_to_once_per_rolling_30_days(tmp_path: Path) -> None:
    current = [NOW]
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        now=lambda: current[0],
    )
    first = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    service.synthesize(first["id"], confirm_external_ai=True)
    service.review(first["id"], decision="accepted", note=None)

    current[0] = NOW + timedelta(days=8)
    transport.get_urls.clear()
    transport.content_version = "v2"
    changed = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    assert changed["status"] == "synthesis_pending"
    with pytest.raises(MarketResearchError, match="不足 30 天"):
        service.synthesize(changed["id"], confirm_external_ai=True)
    assert len(transport.post_payloads) == 1


def test_timeout_after_dispatch_reserves_worst_case_budget_without_retry(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    transport.post_error = MarketResearchError(
        504,
        "external_timeout",
        "外部请求超时，本次研究已停止且不会自动重试。",
    )

    with pytest.raises(MarketResearchError, match="不会自动重试"):
        service.synthesize(run["id"], confirm_external_ai=True)

    failed = service.get_run(run["id"])
    assert failed["status"] == "failed"
    assert failed["actual_cost_micros"] == 0
    assert failed["accounted_cost_micros"] == 60_000
    assert service.overview()["budget"]["daily_used_micros"] == 60_000
    assert len(transport.post_payloads) == 1
    with pytest.raises(MarketResearchError) as unsafe_recovery:
        service.recover_pre_dispatch_failure(run["id"], confirm_recovery=True)
    assert unsafe_recovery.value.code == "pre_dispatch_failure_not_recoverable"
    source_request_count = len(transport.get_urls)
    with pytest.raises(MarketResearchError) as repeated:
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=True,
        )
    assert repeated.value.code == "metadata_refresh_interval_not_elapsed"
    assert len(transport.get_urls) == source_request_count


def test_concurrent_synthesis_requests_dispatch_only_once(tmp_path: Path) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    transport.post_started = Event()
    transport.release_post = Event()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            service.synthesize,
            run["id"],
            confirm_external_ai=True,
        )
        assert transport.post_started.wait(timeout=5)
        second = executor.submit(
            service.synthesize,
            run["id"],
            confirm_external_ai=True,
        )
        with pytest.raises(MarketResearchError, match="状态不允许"):
            second.result(timeout=5)
        transport.release_post.set()
        assert first.result(timeout=5)["status"] == "review_pending"

    assert len(transport.post_payloads) == 1


def test_input_preflight_blocks_before_paid_dispatch(tmp_path: Path) -> None:
    service, transport, profile_id, session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    with session_factory() as database:
        stored = database.get(MarketResearchRun, run["id"])
        assert stored is not None
        sources = json.loads(stored.source_results_json)
        for source in sources:
            if source["status"] == "current":
                source["excerpt"] = "测" * 15_000
        stored.source_results_json = json.dumps(sources, ensure_ascii=False)
        database.commit()

    with pytest.raises(MarketResearchError, match="保守 token 上界"):
        service.synthesize(run["id"], confirm_external_ai=True)

    assert transport.post_payloads == []
    assert service.get_run(run["id"])["failure_code"] == "synthesis_input_preflight_exceeded"


def test_synthesis_rejects_unavailable_or_path_mismatched_citations(tmp_path: Path) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        available_sources=3,
    )
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    transport.synthesis_override = {
        "background_summaries": [
            {
                "path": "employment",
                "summary": "目标岗位存在需求。",
                "source_ids": ["cn-public-recruitment", "cn-miit-data"],
                "uncertainty": "第四个来源本次不可用。",
            }
        ],
        "limitations": ["材料有限。"],
    }

    with pytest.raises(MarketResearchError, match="受限协议"):
        service.synthesize(run["id"], confirm_external_ai=True)

    failed = service.get_run(run["id"])
    assert failed["status"] == "failed"
    assert failed["failure_code"] == "deepseek_limited_protocol_invalid"
    assert failed["actual_cost_micros"] == 1302
    assert failed["accounted_cost_micros"] == 1302
    assert failed["input_tokens"] == 1000
    assert failed["cached_input_tokens"] == 100
    assert failed["output_tokens"] == 200
    with _session_factory() as database:
        event = database.scalar(
            select(MarketResearchEvent)
            .where(
                MarketResearchEvent.run_id == run["id"],
                MarketResearchEvent.event_type == "research_failed",
            )
            .order_by(MarketResearchEvent.id.desc())
        )
    assert event is not None
    payload = json.loads(event.payload_json)
    assert payload["usage"] == {
        "input_tokens": 1000,
        "cached_input_tokens": 100,
        "output_tokens": 200,
    }
    assert payload["diagnostic"] == {
        "response_protocol": "limited_background_v1",
        "failure_stage": "limited_protocol_validation",
        "validation_category": "background_summary_sources_invalid",
        "parsed_json_kind": "object",
        "recognized_top_level_keys": ["background_summaries", "limitations"],
        "missing_top_level_keys": [],
        "unexpected_top_level_key_count": 0,
        "raw_response_saved": False,
    }
    assert "目标岗位存在需求" not in event.payload_json


def test_non_json_model_content_records_hash_and_usage_without_raw_text(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    raw_content = '```json\n{"private-looking-text":"不得保存"}\n```'
    transport.raw_content_override = raw_content

    with pytest.raises(MarketResearchError, match="不是有效 JSON"):
        service.synthesize(run["id"], confirm_external_ai=True)

    failed = service.get_run(run["id"])
    assert failed["failure_code"] == "deepseek_content_not_json"
    assert failed["actual_cost_micros"] == 1302
    assert failed["accounted_cost_micros"] == 1302
    assert failed["input_tokens"] == 1000
    assert failed["cached_input_tokens"] == 100
    assert failed["output_tokens"] == 200
    with session_factory() as database:
        event = database.scalar(
            select(MarketResearchEvent)
            .where(
                MarketResearchEvent.run_id == run["id"],
                MarketResearchEvent.event_type == "research_failed",
            )
            .order_by(MarketResearchEvent.id.desc())
        )
    assert event is not None
    payload = json.loads(event.payload_json)
    assert payload["diagnostic"]["failure_stage"] == "content_json_parse"
    assert payload["diagnostic"]["validation_category"] == "json_decode_error"
    assert payload["diagnostic"]["content_length"] == len(raw_content)
    assert (
        payload["diagnostic"]["content_sha256"] == hashlib.sha256(raw_content.encode()).hexdigest()
    )
    assert payload["diagnostic"]["raw_response_saved"] is False
    assert raw_content not in event.payload_json


def test_unknown_protocol_fields_are_counted_without_saving_names_or_values(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    transport.synthesis_override = {
        "paths": [{"status": "supported", "private": "不得保存"}],
        "limitations": ["材料有限。"],
    }

    with pytest.raises(MarketResearchError, match="受限协议"):
        service.synthesize(run["id"], confirm_external_ai=True)

    with session_factory() as database:
        event = database.scalar(
            select(MarketResearchEvent)
            .where(
                MarketResearchEvent.run_id == run["id"],
                MarketResearchEvent.event_type == "research_failed",
            )
            .order_by(MarketResearchEvent.id.desc())
        )
    assert event is not None
    payload = json.loads(event.payload_json)
    assert payload["diagnostic"] == {
        "response_protocol": "limited_background_v1",
        "failure_stage": "limited_protocol_validation",
        "validation_category": "top_level_keys_invalid",
        "parsed_json_kind": "object",
        "recognized_top_level_keys": ["limitations"],
        "missing_top_level_keys": ["background_summaries"],
        "unexpected_top_level_key_count": 1,
        "raw_response_saved": False,
    }
    assert "paths" not in event.payload_json
    assert "supported" not in event.payload_json
    assert "不得保存" not in event.payload_json


def test_redaction_invalidates_pending_synthesis_and_blocks_review(tmp_path: Path) -> None:
    service, _transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    synthesized = service.synthesize(run["id"], confirm_external_ai=True)
    assert synthesized["synthesis_valid"] is True

    redacted = service.redact_source_excerpt(
        run["id"],
        "cn-nbs-data",
        confirm_redaction=True,
        reason="官方撤回",
    )
    assert redacted["status"] == "blocked"
    assert redacted["synthesis_valid"] is False
    assert redacted["synthesis_invalidated_at"] is not None
    with pytest.raises(MarketResearchError, match="当前无需复核"):
        service.review(run["id"], decision="accepted", note=None)


def test_same_version_catalog_and_budget_mutations_are_rejected(tmp_path: Path) -> None:
    service, _transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    service._catalog["scope"]["employment"].append("原地修改")
    with pytest.raises(MarketResearchError, match="来源目录同一版本"):
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=True,
        )

    service._catalog["scope"]["employment"].pop()
    service._budget["limits"]["daily"] = 0.4
    with pytest.raises(MarketResearchError, match="预算策略同一版本"):
        service.create_run(
            provider_profile_id=profile_id,
            confirm_external_sources=True,
        )


def test_market_research_history_exposes_runs_and_sanitized_events(tmp_path: Path) -> None:
    service, _transport, profile_id, _session_factory, api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    history = service.history(limit=20)

    assert [item["id"] for item in history["runs"]] == [run["id"]]
    assert {event["event_type"] for event in history["events"]} == {
        "research_created",
        "official_sources_checked",
    }
    assert api_key not in json.dumps(history, ensure_ascii=False, default=str)


def test_full_normalized_body_change_after_excerpt_is_not_reported_unchanged(
    tmp_path: Path,
) -> None:
    current = [NOW]
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        now=lambda: current[0],
    )
    transport.long_body_tail = "尾部版本一"
    first = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    service.complete_metadata_only(first["id"])

    current[0] = NOW + timedelta(days=8)
    transport.get_urls.clear()
    transport.long_body_tail = "尾部版本二"
    refreshed = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )

    assert refreshed["status"] == "synthesis_pending"
    for previous, current_source in zip(
        first["sources"],
        refreshed["sources"],
        strict=True,
    ):
        assert previous["excerpt"] == current_source["excerpt"]
        assert previous["excerpt_sha256"] == current_source["excerpt_sha256"]
        assert previous["normalized_content_sha256"] != current_source["normalized_content_sha256"]
        assert previous["raw_response_sha256"] != current_source["raw_response_sha256"]
        assert current_source["change_status"] == "changed"


def test_raw_template_change_with_same_normalized_body_is_audited_separately(
    tmp_path: Path,
) -> None:
    current = [NOW]
    service, transport, profile_id, _session_factory, _api_key = _service(
        tmp_path,
        now=lambda: current[0],
    )
    template_version = ["v1"]
    original_get = transport.get

    def templated_get(url: str, allowed_hosts: set[str]) -> HttpResponse:
        response = original_get(url, allowed_hosts)
        if (
            response.status == 200
            and not url.endswith("/robots.txt")
            and "api-docs.deepseek.com" not in url
        ):
            return HttpResponse(
                status=response.status,
                headers=response.headers,
                body=response.body.replace(
                    b"<body>",
                    f"<body data-template='{template_version[0]}'>".encode(),
                ),
                final_url=response.final_url,
            )
        return response

    transport.get = templated_get  # type: ignore[method-assign]
    first = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    service.complete_metadata_only(first["id"])
    current[0] = NOW + timedelta(days=8)
    transport.get_urls.clear()
    template_version[0] = "v2"

    refreshed = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )

    assert refreshed["status"] == "completed"
    assert all(source["change_status"] == "metadata_changed" for source in refreshed["sources"])
    assert all(
        before["normalized_content_sha256"] == after["normalized_content_sha256"]
        for before, after in zip(first["sources"], refreshed["sources"], strict=True)
    )
    assert all(
        before["raw_response_sha256"] != after["raw_response_sha256"]
        for before, after in zip(first["sources"], refreshed["sources"], strict=True)
    )


def test_conclusive_evidence_requires_independent_groups_and_relevant_direct_signal(
    tmp_path: Path,
) -> None:
    service, _transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    catalog = json.loads(json.dumps(service._catalog))
    catalog["path_evidence_capabilities"]["employment"]["coverage"] = "conclusive_supported"
    sources = run["sources"]
    direct = next(source for source in sources if source["source_id"] == "cn-public-recruitment")
    direct["evidence_role"] = "direct_signal"
    direct["relevant_paths"] = ["employment"]
    synthesis = {
        "paths": [
            {
                "path": "employment",
                "status": "supported",
                "claims": [
                    {
                        "claim": "目标岗位信号存在。",
                        "source_ids": [
                            "cn-mohrss-statistics",
                            "cn-public-recruitment",
                        ],
                        "uncertainty": "仅限本次材料。",
                    }
                ],
            },
            {"path": "freelancing", "status": "indeterminate", "claims": []},
            {"path": "productization", "status": "indeterminate", "claims": []},
        ],
        "limitations": ["受限。"],
        "content_impact_suggestions": [
            {
                "kind": "no_change",
                "summary": "保持不变。",
                "source_ids": ["cn-nbs-data"],
            }
        ],
    }

    with pytest.raises(ValueError, match="independent"):
        service._validate_synthesis(synthesis, sources, catalog)

    direct["independence_group"] = "independent-recruitment-owner"
    direct["relevant_paths"] = []
    with pytest.raises(ValueError, match="not relevant"):
        service._validate_synthesis(synthesis, sources, catalog)


def test_registry_can_bind_a_second_skill_without_changing_core_service(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, session_factory, _api_key = _service(tmp_path)
    repository = tmp_path / "second-skill-repository"
    (repository / "readiness" / "sources").mkdir(parents=True)
    (repository / "readiness" / "policies").mkdir(parents=True)
    catalog = json.loads(
        (REPOSITORY_ROOT / "readiness" / "sources" / "official-cn-market-v1.json").read_text(
            encoding="utf-8"
        )
    )
    catalog["catalog_id"] = "official-cn-test-skill-market"
    catalog["version"] = "1.0.0"
    catalog["research_context"] = {
        "skill_id": "test-skill",
        "skill_version": "1.0.0",
        "capability_scope_id": "test-skill-entry",
        "research_topic": "综合测试技能的受管市场背景",
        "allowed_goal_kinds": ["employment"],
        "allowed_paths": ["employment", "freelancing", "productization"],
    }
    (repository / "readiness" / "sources" / "test-skill.json").write_text(
        json.dumps(catalog, ensure_ascii=False),
        encoding="utf-8",
    )
    shutil.copy(
        REPOSITORY_ROOT / "readiness" / "policies" / "deepseek-v4-flash-budget-v1.json",
        repository / "readiness" / "policies" / "budget.json",
    )
    (repository / "readiness" / "market-research-registry-v1.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "registrations": [
                    {
                        "catalog_id": catalog["catalog_id"],
                        "catalog_version": catalog["version"],
                        "catalog_path": "readiness/sources/test-skill.json",
                        "budget_policy_id": service._budget["policy_id"],
                        "budget_policy_version": service._budget["version"],
                        "budget_policy_path": "readiness/policies/budget.json",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with session_factory() as database:
        database.add(
            UserGoalSelection(
                id="second-skill-goal",
                skill_id="test-skill",
                skill_version="1.0.0",
                capability_scope_id="test-skill-entry",
                goal_kind="employment",
                custom_label=None,
                created_at=NOW,
                superseded_at=None,
            )
        )
        database.commit()
    second_service = MarketResearchService(
        repository_root=repository,
        session_factory=session_factory,
        credential_store=MemoryCredentialStore(),
        transport=transport,
        now=lambda: NOW,
    )

    run = second_service.create_run(
        provider_profile_id=profile_id,
        goal_selection_id="second-skill-goal",
        catalog_id=catalog["catalog_id"],
        catalog_version=catalog["version"],
        confirm_external_sources=True,
    )

    assert run["skill_id"] == "test-skill"
    assert run["skill_version"] == "1.0.0"
    assert run["capability_scope_id"] == "test-skill-entry"
    assert "综合测试技能的受管市场背景" in second_service._synthesis_prompt(run["id"])


def test_expired_dispatched_attempt_requires_recovery_and_conservative_accounting(
    tmp_path: Path,
) -> None:
    current = [NOW]
    service, transport, profile_id, session_factory, _api_key = _service(
        tmp_path,
        now=lambda: current[0],
    )
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    prepared = service._synthesis_adapter.prepare(
        system_prompt="system",
        user_prompt=service._synthesis_prompt(run["id"]),
        max_output_tokens=service._budget["limits"]["max_output_tokens_per_call"],
    )
    attempt_id = service._claim_synthesis(
        run["id"],
        budget=service._budget,
        prepared=prepared,
    )
    service._mark_dispatch_started(run["id"], attempt_id)

    current[0] = NOW + timedelta(minutes=6)
    recovered_service = MarketResearchService(
        repository_root=REPOSITORY_ROOT,
        session_factory=session_factory,
        credential_store=MemoryCredentialStore(),
        transport=transport,
        now=lambda: current[0],
    )
    recovered = recovered_service.get_run(run["id"])
    assert recovered["status"] == "recovery_required"
    assert recovered["accounted_cost_micros"] == 60_000
    assert transport.post_payloads == []

    with pytest.raises(MarketResearchError, match="明确确认"):
        recovered_service.reconcile_recovery(
            run["id"],
            confirm_end=False,
            note=None,
        )
    ended = recovered_service.reconcile_recovery(
        run["id"],
        confirm_end=True,
        note="本地确认结束，不重试。",
    )
    assert ended["status"] == "failed"
    assert ended["accounted_cost_micros"] == 60_000
    assert transport.post_payloads == []


def test_expired_claim_before_dispatch_is_recovered_as_not_charged(
    tmp_path: Path,
) -> None:
    current = [NOW]
    service, transport, profile_id, session_factory, _api_key = _service(
        tmp_path,
        now=lambda: current[0],
    )
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    prepared = service._synthesis_adapter.prepare(
        system_prompt="system",
        user_prompt=service._synthesis_prompt(run["id"]),
        max_output_tokens=service._budget["limits"]["max_output_tokens_per_call"],
    )
    service._claim_synthesis(
        run["id"],
        budget=service._budget,
        prepared=prepared,
    )

    current[0] = NOW + timedelta(minutes=6)
    recovered_service = MarketResearchService(
        repository_root=REPOSITORY_ROOT,
        session_factory=session_factory,
        credential_store=MemoryCredentialStore(),
        transport=transport,
        now=lambda: current[0],
    )
    recovered = recovered_service.get_run(run["id"])

    assert recovered["status"] == "recovery_required"
    assert recovered["accounted_cost_micros"] == 0
    assert transport.post_payloads == []


def test_unknown_dispatch_exception_is_conservatively_accounted_without_retry(
    tmp_path: Path,
) -> None:
    service, transport, profile_id, _session_factory, _api_key = _service(tmp_path)
    run = service.create_run(
        provider_profile_id=profile_id,
        confirm_external_sources=True,
    )
    transport.post_error = RuntimeError("unexpected TLS failure")

    with pytest.raises(MarketResearchError, match="未知异常"):
        service.synthesize(run["id"], confirm_external_ai=True)

    failed = service.get_run(run["id"])
    assert failed["status"] == "failed"
    assert failed["accounted_cost_micros"] == 60_000
    assert len(transport.post_payloads) == 1


def test_strict_transport_rejects_non_https_and_unapproved_hosts() -> None:
    transport = StrictHttpsTransport()
    with pytest.raises(MarketResearchError, match="白名单"):
        transport.get("http://www.stats.gov.cn/sj/", {"www.stats.gov.cn"})
    with pytest.raises(MarketResearchError, match="白名单"):
        transport.get("https://example.com/", {"www.stats.gov.cn"})


def test_strict_transport_rejects_cross_host_redirect_and_oversized_response(
    monkeypatch: MonkeyPatch,
) -> None:
    class FakeResponse:
        def __init__(
            self,
            status: int,
            headers: list[tuple[str, str]],
            body: bytes = b"",
        ) -> None:
            self.status = status
            self._headers = headers
            self._body = body

        def getheaders(self) -> list[tuple[str, str]]:
            return self._headers

        def read(self, amount: int) -> bytes:
            return self._body[:amount]

    class FakeConnection:
        responses: ClassVar[list[FakeResponse]] = []

        def __init__(self, host: str, timeout: int) -> None:
            del host, timeout

        def request(
            self,
            method: str,
            path: str,
            *,
            body: bytes | None,
            headers: dict[str, str],
        ) -> None:
            del method, path, body, headers

        def getresponse(self) -> FakeResponse:
            return self.responses.pop(0)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "cloud_study_api.market_research.http.client.HTTPSConnection",
        FakeConnection,
    )
    transport = StrictHttpsTransport()
    FakeConnection.responses = [FakeResponse(302, [("Location", "https://example.com/redirect")])]
    with pytest.raises(MarketResearchError, match="白名单"):
        transport.get("https://www.stats.gov.cn/sj/", {"www.stats.gov.cn"})

    FakeConnection.responses = [FakeResponse(200, [("Content-Length", str(MAX_SOURCE_BYTES + 1))])]
    with pytest.raises(MarketResearchError, match="超过允许大小"):
        transport.get("https://www.stats.gov.cn/sj/", {"www.stats.gov.cn"})


def test_market_research_api_overview_is_offline_and_confirmation_is_required(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = tmp_path / "market-research-api.db"
    monkeypatch.setenv("CLOUD_STUDY_DATABASE_PATH", str(database_path))

    with TestClient(app) as client:
        overview = client.get("/market-research/overview")
        history = client.get("/market-research/history")
        rejected = client.post(
            "/market-research/runs",
            json={
                "provider_profile_id": "not-used-without-confirmation",
                "goal_selection_id": "not-used-without-confirmation",
                "catalog_id": "official-cn-algorithm-market",
                "catalog_version": "1.2.0",
                "readiness_evaluation_id": None,
                "confirm_external_sources": False,
            },
        )

    assert overview.status_code == 200
    assert history.status_code == 200
    assert history.json() == {"runs": [], "events": []}
    assert overview.json()["catalog"]["scope"]["region"] == "CN-mainland"
    assert overview.json()["budget"]["monthly_limit_micros"] == 5_000_000
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "external_source_confirmation_required"
