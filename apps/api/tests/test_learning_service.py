from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from cloud_study_api.ai_configuration import AiConfigurationService
from cloud_study_api.credentials import MemoryCredentialStore
from cloud_study_api.database import create_session_factory, upgrade_database
from cloud_study_api.diagnostics import DiagnosticService
from cloud_study_api.governance import validate_repository
from cloud_study_api.learning import LearningError, LearningService, SourceObservation
from cloud_study_api.models import SourceCheckResult, SourceCheckRun
from cloud_study_api.notifications import NotificationError, NotificationService

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FAKE_SMTP_SECRET = "-".join(("smtp", "secret"))


class FakeSourceFetcher:
    def __init__(self) -> None:
        self.revision = "a"
        self.failed_source_id: str | None = None
        self.include_validators = True

    def fetch(self, source: dict[str, Any]) -> SourceObservation:
        if source["id"] == self.failed_source_id:
            raise RuntimeError("simulated remote failure")
        return SourceObservation(
            http_status=200,
            etag=(f"{source['id']}-{self.revision}" if self.include_validators else None),
            last_modified=("Mon, 27 Jul 2026 00:00:00 GMT" if self.include_validators else None),
            final_url=source["url"],
        )


class FakeMailSender:
    def __init__(self) -> None:
        self.subjects: list[str] = []

    def send(
        self,
        preference: Any,
        secret: str,
        subject: str,
        body: str,
    ) -> None:
        assert preference.credential_reference == "cloud-study/email/smtp"
        assert secret == FAKE_SMTP_SECRET
        assert "本地云奕学" in body
        self.subjects.append(subject)


def _services(
    tmp_path: Path,
) -> tuple[
    DiagnosticService,
    LearningService,
    NotificationService,
    FakeSourceFetcher,
]:
    database_path = tmp_path / "learning.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    packages = validate_repository(REPOSITORY_ROOT)
    credential_store = MemoryCredentialStore()
    notifications = NotificationService(
        session_factory=session_factory,
        credential_store=credential_store,
    )
    fetcher = FakeSourceFetcher()
    diagnostics = DiagnosticService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
    )
    learning = LearningService(
        repository_root=REPOSITORY_ROOT,
        packages=packages,
        session_factory=session_factory,
        notification_service=notifications,
        source_fetcher=fetcher,
        now=lambda: datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
    )
    return diagnostics, learning, notifications, fetcher


def test_planning_preview_is_source_backed_editable_and_read_only_after_save(
    tmp_path: Path,
) -> None:
    diagnostics, learning, _, _ = _services(tmp_path)
    package = validate_repository(REPOSITORY_ROOT)[0]
    diagnostic = diagnostics.create_session(
        skill_id=package.package_id,
        skill_version=package.version,
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )
    diagnostics.end_session(diagnostic["id"])

    proposal = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )
    repeated = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )

    assert proposal["is_preview"] is True
    assert proposal["status"] == "draft"
    assert len(proposal["units"]) == 4
    assert all(unit["sources"] for unit in proposal["units"])
    assert all(unit["completion_criteria"] for unit in proposal["units"])
    stable_fields = {
        "id",
        "diagnostic_session_id",
        "skill_id",
        "skill_version",
        "template_id",
        "provider_id",
        "model_id",
        "is_preview",
        "status",
        "title",
        "rationale",
        "limitations",
        "units",
    }
    assert {key: repeated[key] for key in stable_fields} == {
        key: proposal[key] for key in stable_fields
    }

    first_unit = proposal["units"][0]
    edited = learning.update_planning_unit(
        proposal["id"],
        first_unit["id"],
        title="按实际情况修正后的编程基础自检",
        objective=first_unit["objective"],
        reason=first_unit["reason"],
        estimated_minutes=90,
        completion_criteria=first_unit["completion_criteria"],
    )
    assert edited["units"][0]["estimated_minutes"] == 90

    saved = learning.set_proposal_status(proposal["id"], "saved_preview")
    assert saved["status"] == "saved_preview"
    with pytest.raises(LearningError) as error:
        learning.update_planning_unit(
            proposal["id"],
            first_unit["id"],
            title=first_unit["title"],
            objective=first_unit["objective"],
            reason=first_unit["reason"],
            estimated_minutes=60,
            completion_criteria=first_unit["completion_criteria"],
        )
    assert error.value.status_code == 409
    assert error.value.code == "planning_proposal_read_only"


def test_source_failure_notifies_without_blocking_and_change_requires_review(
    tmp_path: Path,
) -> None:
    _, learning, notifications, fetcher = _services(tmp_path)
    fetcher.failed_source_id = "python-tutorial"

    failed_run = learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=False,
    )

    assert failed_run["status"] == "completed_with_failures"
    assert failed_run["failed_count"] == 1
    assert sum(result["status"] == "baseline_created" for result in failed_run["results"]) == 3
    assert sum(result["status"] == "failed" for result in failed_run["results"]) == 1
    assert any(
        item["severity"] == "warning" and "不会阻止学习" in item["message"]
        for item in notifications.list_notifications()
    )

    reused = learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=False,
    )
    assert reused["reused"] is True
    assert reused["id"] == failed_run["id"]

    fetcher.failed_source_id = None
    learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=True,
    )
    fetcher.revision = "b"
    changed_run = learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=True,
    )

    assert changed_run["changed_count"] == 4
    candidates = learning.list_change_candidates("algorithm", "0.1.0")
    assert candidates
    assert all(candidate["status"] == "pending" for candidate in candidates)
    accepted = learning.resolve_change_candidate(candidates[0]["id"], "accepted")
    assert accepted["status"] == "accepted"
    assert validate_repository(REPOSITORY_ROOT)[0].state == "draft"


def test_source_without_comparison_validators_requires_manual_review(
    tmp_path: Path,
) -> None:
    _, learning, notifications, fetcher = _services(tmp_path)
    fetcher.include_validators = False

    baseline = learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=True,
    )
    assert all(result["status"] == "baseline_created" for result in baseline["results"])

    indeterminate = learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=True,
    )
    assert all(result["status"] == "indeterminate" for result in indeterminate["results"])
    assert not any(result["status"] == "unchanged" for result in indeterminate["results"])
    assert any(
        item["severity"] == "warning" and "不会将其记录为“未变化”" in item["message"]
        for item in notifications.list_notifications()
    )


def test_source_history_is_isolated_by_skill_package_version(tmp_path: Path) -> None:
    _, learning, _, _ = _services(tmp_path)
    session_factory = create_session_factory(tmp_path / "learning.db")
    checked_at = datetime(2026, 7, 26, 8, 0, tzinfo=UTC)
    with session_factory() as database:
        database.add(
            SourceCheckRun(
                id="other-version-run",
                skill_id="algorithm",
                skill_version="9.9.9",
                local_date="2026-07-26",
                trigger="manual",
                status="completed",
                checked_count=1,
                changed_count=0,
                failed_count=0,
                started_at=checked_at,
                completed_at=checked_at,
            )
        )
        database.add(
            SourceCheckResult(
                id="other-version-result",
                run_id="other-version-run",
                source_id="python-tutorial",
                source_title="The Python Tutorial",
                status="baseline_created",
                http_status=200,
                etag="python-tutorial-a",
                last_modified="Mon, 27 Jul 2026 00:00:00 GMT",
                final_url="https://docs.python.org/3/tutorial/",
                checked_at=checked_at,
                last_success_at=checked_at,
            )
        )
        database.commit()

    current = learning.check_sources(
        skill_id="algorithm",
        skill_version="0.1.0",
        manual=True,
    )
    python_result = next(
        result for result in current["results"] if result["source_id"] == "python-tutorial"
    )
    assert python_result["status"] == "baseline_created"


def test_rejected_proposal_can_be_replaced(tmp_path: Path) -> None:
    diagnostics, learning, _, _ = _services(tmp_path)
    package = validate_repository(REPOSITORY_ROOT)[0]
    diagnostic = diagnostics.create_session(
        skill_id=package.package_id,
        skill_version=package.version,
        preview=True,
        provider_id="local-deterministic",
        model_id="diagnostic-v1",
        credential_reference=None,
        external_ai_consent=False,
    )
    diagnostics.end_session(diagnostic["id"])
    rejected = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )
    learning.set_proposal_status(rejected["id"], "rejected")

    with pytest.raises(LearningError) as error:
        learning.get_latest_proposal(package.package_id, package.version)
    assert error.value.code == "planning_proposal_not_found"

    replacement = learning.create_planning_proposal(
        diagnostic_session_id=diagnostic["id"],
        preview=True,
        provider_id="local-deterministic",
        model_id="planner-sim-v1",
    )
    assert replacement["id"] != rejected["id"]
    assert replacement["status"] == "draft"


def test_email_preferences_read_and_archive_cancel_optional_mail(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "notifications.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    credential_store = MemoryCredentialStore()
    sender = FakeMailSender()
    service = NotificationService(
        session_factory=session_factory,
        credential_store=credential_store,
        mail_sender=sender,
        now=lambda: datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
    )
    preferences = service.update_preferences(
        email_enabled=True,
        email_action_required=True,
        email_warning=True,
        email_delay_minutes=10,
        recipient_email="owner@example.com",
        sender_email="cloud-study@example.com",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_username="cloud-study@example.com",
        smtp_security="ssl",
        smtp_password=FAKE_SMTP_SECRET,
    )
    assert preferences["credential_reference"] == "cloud-study/email/smtp"
    assert FAKE_SMTP_SECRET not in str(preferences)

    replacement_secret = "-".join(("replacement", "smtp", "secret"))
    with pytest.raises(NotificationError) as error:
        service.update_preferences(
            email_enabled=True,
            email_action_required=True,
            email_warning=True,
            email_delay_minutes=10,
            recipient_email=None,
            sender_email="cloud-study@example.com",
            smtp_host="smtp.example.com",
            smtp_port=465,
            smtp_username="cloud-study@example.com",
            smtp_security="ssl",
            smtp_password=replacement_secret,
        )
    assert error.value.code == "email_configuration_incomplete"
    assert credential_store.get("cloud-study/email/smtp") == FAKE_SMTP_SECRET

    warning_id = service.create(
        category="source_check",
        severity="warning",
        title="来源失败",
        message="远程来源暂时不可用。",
    )
    assert service.process_outbox() == {"sent": 0, "cancelled": 0, "failed": 0}
    handled = service.mark_read(warning_id)
    assert handled["email_status"] == "cancelled"

    archived_id = service.create(
        category="source_update",
        severity="warning",
        title="来源变化",
        message="远程来源元数据发生变化。",
    )
    archived = service.archive(archived_id)
    assert archived["read_at"] is not None
    assert archived["archived_at"] is not None
    assert archived["email_status"] == "cancelled"
    assert archived_id not in {item["id"] for item in service.list_notifications()}
    assert archived_id in {item["id"] for item in service.list_notifications(include_archived=True)}

    service.create(
        category="security",
        severity="required",
        title="必要通知",
        message="用于验证必要邮件立即发送。",
    )
    assert service.process_outbox()["sent"] == 1
    assert sender.subjects == ["必要通知"]


def test_ai_provider_capabilities_and_credentials_stay_out_of_sqlite_and_logs(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_path = tmp_path / "ai-configuration.db"
    upgrade_database(database_path, REPOSITORY_ROOT)
    session_factory = create_session_factory(database_path)
    credential_store = MemoryCredentialStore()
    service = AiConfigurationService(
        session_factory=session_factory,
        credential_store=credential_store,
        now=lambda: datetime(2026, 7, 27, 8, 0, tzinfo=UTC),
    )

    providers = service.list_providers()
    assert [provider["id"] for provider in providers] == [
        "local-deterministic",
        "openai",
        "deepseek",
        "moonshot",
    ]
    assert all(provider["capabilities"] for provider in providers)
    assert providers[0]["executable"] is True
    assert all(provider["executable"] is False for provider in providers[1:])

    api_key = "-".join(("third", "milestone", "credential"))
    profile = service.create_profile(
        provider_id="openai",
        display_name="本地 OpenAI 配置",
        base_url=None,
        api_key=api_key,
        enabled=True,
    )

    assert profile["credential_reference"].startswith("cloud-study/ai/")
    assert credential_store.get(profile["credential_reference"]) == api_key
    assert api_key not in str(profile)
    persisted = service.list_profiles()
    assert len(persisted) == 1
    assert persisted[0]["id"] == profile["id"]
    assert persisted[0]["credential_reference"] == profile["credential_reference"]
    assert persisted[0]["provider_id"] == "openai"
    assert persisted[0]["executable"] is False
    assert api_key.encode() not in database_path.read_bytes()
    assert api_key not in caplog.text
