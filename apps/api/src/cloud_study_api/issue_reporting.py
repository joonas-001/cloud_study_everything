from __future__ import annotations

import os
import platform
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

ReportType = Literal["bug", "feature", "content"]
OptionalField = Literal[
    "page_route",
    "operation_type",
    "skill_version",
    "request_audit_id",
    "reason_code",
    "event_names",
    "runner_details",
]

OPTIONAL_FIELDS: tuple[OptionalField, ...] = (
    "page_route",
    "operation_type",
    "skill_version",
    "request_audit_id",
    "reason_code",
    "event_names",
    "runner_details",
)
FIELD_LABELS = {
    "report_type": "报告类型 / report type",
    "application_version": "应用版本 / application version",
    "release_commit": "发布提交 / release commit",
    "system_summary": "系统摘要 / system summary",
    "web_health": "Web 健康 / web health",
    "api_health": "API 健康 / API health",
    "schema_revision": "数据库修订 / database revision",
    "deployment_mode": "部署模式 / deployment mode",
    "runner_enabled": "Runner 启用 / Runner enabled",
    "external_calls_enabled": "外部调用启用 / external calls enabled",
    "generated_at": "生成时间 / generated at",
    "page_route": "页面路由 / page route",
    "operation_type": "操作类型 / operation type",
    "skill_version": "技能版本 / skill version",
    "request_audit_id": "请求审计 ID / request audit ID",
    "reason_code": "原因码 / reason code",
    "event_names": "受管事件 / managed events",
    "runner_details": "Runner 运行时 / Runner runtime",
}
REPORT_TEMPLATES: dict[ReportType, str] = {
    "bug": "bug.yml",
    "feature": "feature.yml",
    "content": "content.yml",
}
REPORT_TITLES: dict[ReportType, str] = {
    "bug": "[Bug] ",
    "feature": "[Feature] ",
    "content": "[Content] ",
}
SAFE_ROUTES = {
    "/",
    "/diagnostic",
    "/evidence",
    "/experiments",
    "/goals",
    "/inbox",
    "/learning",
    "/market-research",
    "/more",
    "/readiness",
    "/settings",
}
SAFE_OPERATIONS = {
    "page_load",
    "save_settings",
    "diagnostic",
    "planning",
    "learning",
    "evidence",
    "runner",
    "export",
    "notification",
    "managed_other",
}
SAFE_EVENTS = {
    "api_request_failed",
    "contract_validation_failed",
    "database_revision_mismatch",
    "learning_action_failed",
    "runner_protocol_invalid",
    "runner_unavailable",
    "source_review_pending",
}
SAFE_VERSION = re.compile(r"^[a-z][a-z0-9-]{0,49}@[0-9]+\.[0-9]+\.[0-9]+$")
SAFE_AUDIT_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
SAFE_REASON_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SAFE_COMMIT = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
PROHIBITED_DIAGNOSTIC_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),
    re.compile(r"\\\\[^\s]+"),
    re.compile(r"/(?:home|users|mnt|var/lib|run/secrets)/", re.IGNORECASE),
    re.compile(r"\b(?:10|127)\.(?:\d{1,3}\.){2}\d{1,3}\b"),
    re.compile(r"\b192\.168\.(?:\d{1,3}\.)\d{1,3}\b"),
    re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3}\b"),
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"(?:api[_-]?key|password|secret|token)\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"https?://(?!github\.com(?:/|$))", re.IGNORECASE),
)


class IssueReportError(ValueError):
    pass


class IssueReportField(TypedDict):
    key: str
    label: str
    value: str
    required: bool


def find_prohibited_diagnostic_content(value: str) -> list[str]:
    """Return stable reason codes without echoing sensitive matches."""

    return [
        f"prohibited_pattern_{index}"
        for index, pattern in enumerate(PROHIBITED_DIAGNOSTIC_PATTERNS, start=1)
        if pattern.search(value)
    ]


class IssueReportService:
    """Build an allowlist-only preview without persisting or sending it."""

    def __init__(
        self,
        *,
        repository_root: Path,
        session_factory: sessionmaker[Session],
        deployment_status: dict[str, object],
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository_root = repository_root
        self._session_factory = session_factory
        self._deployment_status = deployment_status
        self._now = now or (lambda: datetime.now(UTC))

    def preview(
        self,
        *,
        report_type: ReportType,
        included_optional_fields: list[OptionalField],
        page_route: str | None,
        operation_type: str | None,
        skill_version: str | None,
        request_audit_id: str | None,
        reason_code: str | None,
        event_names: list[str],
    ) -> dict[str, object]:
        included = set(included_optional_fields)
        if len(included) != len(included_optional_fields):
            raise IssueReportError("optional fields must not contain duplicates")
        self._validate_optional_values(
            included=included,
            page_route=page_route,
            operation_type=operation_type,
            skill_version=skill_version,
            request_audit_id=request_audit_id,
            reason_code=reason_code,
            event_names=event_names,
        )

        release_commit = os.getenv("CLOUD_STUDY_RELEASE_COMMIT", "").strip().lower()
        if not SAFE_COMMIT.fullmatch(release_commit):
            release_commit = "unavailable"
        system = platform.system().casefold()
        architecture = platform.machine().casefold()
        if system not in {"windows", "linux", "darwin"}:
            system = "other"
        if architecture not in {"amd64", "x86_64", "arm64", "aarch64"}:
            architecture = "other"
        with self._session_factory() as database:
            schema_revision = str(
                database.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )

        required_values = {
            "report_type": report_type,
            "application_version": "0.1.0",
            "release_commit": release_commit,
            "system_summary": f"{system}/{architecture}",
            "web_health": "ok",
            "api_health": "ok",
            "schema_revision": schema_revision,
            "deployment_mode": str(self._deployment_status["mode"]),
            "runner_enabled": self._bool_text(
                bool(self._deployment_status["remote_runner_enabled"])
                or self._deployment_status["mode"] == "local"
            ),
            "external_calls_enabled": self._bool_text(
                bool(self._deployment_status["external_calls_enabled"])
            ),
            "generated_at": self._now().astimezone(UTC).isoformat(timespec="seconds"),
        }
        optional_values = {
            "page_route": page_route,
            "operation_type": operation_type,
            "skill_version": skill_version,
            "request_audit_id": request_audit_id,
            "reason_code": reason_code,
            "event_names": ", ".join(event_names) if event_names else None,
            "runner_details": "protocol=1.1.0; gcc=15.2.0; python=3.14.3",
        }
        fields: list[IssueReportField] = [
            {
                "key": key,
                "label": FIELD_LABELS[key],
                "value": str(value),
                "required": True,
            }
            for key, value in required_values.items()
        ]
        fields.extend(
            {
                "key": key,
                "label": FIELD_LABELS[key],
                "value": str(optional_values[key]),
                "required": False,
            }
            for key in OPTIONAL_FIELDS
            if key in included and optional_values[key] is not None
        )
        rendered_text = self._render(fields)
        violations = find_prohibited_diagnostic_content(rendered_text)
        if violations:
            raise IssueReportError(
                "the generated diagnostic failed the prohibited-content boundary"
            )
        query = urlencode(
            {
                "template": REPORT_TEMPLATES[report_type],
                "title": REPORT_TITLES[report_type],
            }
        )
        return {
            "report_type": report_type,
            "fields": fields,
            "rendered_text": rendered_text,
            "submission_url": (
                "https://github.com/joonas-001/cloud_study_everything/issues/new?" + query
            ),
            "automatic_submission_enabled": False,
            "attachments_enabled": False,
            "copy_required_before_open": True,
            "privacy_notice": (
                "诊断仅由允许列表字段组成。请完整预览后复制。系统不会自动提交或上传。"
            ),
        }

    def _validate_optional_values(
        self,
        *,
        included: set[OptionalField],
        page_route: str | None,
        operation_type: str | None,
        skill_version: str | None,
        request_audit_id: str | None,
        reason_code: str | None,
        event_names: list[str],
    ) -> None:
        supplied = {
            "page_route": page_route,
            "operation_type": operation_type,
            "skill_version": skill_version,
            "request_audit_id": request_audit_id,
            "reason_code": reason_code,
            "event_names": event_names or None,
        }
        for key, value in supplied.items():
            if value is not None and key not in included:
                raise IssueReportError(f"{key} was supplied but not selected for the preview")
        if page_route is not None and page_route not in SAFE_ROUTES:
            raise IssueReportError("page_route is not a managed route")
        if operation_type is not None and operation_type not in SAFE_OPERATIONS:
            raise IssueReportError("operation_type is not managed")
        if skill_version is not None:
            if not SAFE_VERSION.fullmatch(skill_version):
                raise IssueReportError("skill_version has an invalid format")
            skill_id, version = skill_version.split("@", maxsplit=1)
            manifest = (
                self._repository_root
                / "skill-packs"
                / skill_id
                / "versions"
                / version
                / "manifest.yaml"
            )
            if not manifest.is_file():
                raise IssueReportError("skill_version is not a managed package")
        if request_audit_id is not None and not SAFE_AUDIT_ID.fullmatch(request_audit_id):
            raise IssueReportError("request_audit_id must be a UUID")
        if reason_code is not None and not SAFE_REASON_CODE.fullmatch(reason_code):
            raise IssueReportError("reason_code is not a managed identifier")
        if len(event_names) > 5 or any(name not in SAFE_EVENTS for name in event_names):
            raise IssueReportError("event_names contains an unmanaged event")
        if len(set(event_names)) != len(event_names):
            raise IssueReportError("event_names must not contain duplicates")

    @staticmethod
    def _bool_text(value: bool) -> str:
        return "true" if value else "false"

    @staticmethod
    def _render(fields: list[IssueReportField]) -> str:
        lines = ["Cloud Study sanitized diagnostic v1", ""]
        lines.extend(f"- {field['key']}: {field['value']}" for field in fields)
        lines.extend(
            [
                "",
                "Previewed locally; no automatic submission or attachment.",
            ]
        )
        return "\n".join(lines)
