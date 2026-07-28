# ruff: noqa: RUF001

from __future__ import annotations

import smtplib
from collections.abc import Callable
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from cloud_study_api.credentials import CredentialStore, CredentialStoreError
from cloud_study_api.models import (
    EmailOutbox,
    Notification,
    NotificationPreference,
    utc_now,
)

SMTP_CREDENTIAL_REFERENCE = "cloud-study/email/smtp"


class NotificationError(RuntimeError):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class MailSender(Protocol):
    def send(
        self,
        preference: NotificationPreference,
        secret: str,
        subject: str,
        body: str,
    ) -> None: ...


class SmtpMailSender:
    def send(
        self,
        preference: NotificationPreference,
        secret: str,
        subject: str,
        body: str,
    ) -> None:
        if not all(
            [
                preference.smtp_host,
                preference.smtp_port,
                preference.smtp_username,
                preference.sender_email,
                preference.recipient_email,
            ]
        ):
            raise RuntimeError("SMTP configuration is incomplete")
        smtp_host = preference.smtp_host
        smtp_port = preference.smtp_port
        smtp_username = preference.smtp_username
        sender_email = preference.sender_email
        recipient_email = preference.recipient_email
        assert smtp_host is not None
        assert smtp_port is not None
        assert smtp_username is not None
        assert sender_email is not None
        assert recipient_email is not None
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender_email
        message["To"] = recipient_email
        message.set_content(body)
        if preference.smtp_security == "ssl":
            with smtplib.SMTP_SSL(
                smtp_host,
                smtp_port,
                timeout=10,
            ) as client:
                client.login(smtp_username, secret)
                client.send_message(message)
            return
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=10,
        ) as client:
            client.starttls()
            client.login(smtp_username, secret)
            client.send_message(message)


class NotificationService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        credential_store: CredentialStore,
        mail_sender: MailSender | None = None,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session_factory = session_factory
        self._credential_store = credential_store
        self._mail_sender = mail_sender or SmtpMailSender()
        self._now = now

    def get_preferences(self) -> dict[str, Any]:
        with self._session_factory() as database:
            return self._preference_payload(self._preference(database))

    def update_preferences(
        self,
        *,
        email_enabled: bool,
        email_action_required: bool,
        email_warning: bool,
        email_delay_minutes: int,
        recipient_email: str | None,
        sender_email: str | None,
        smtp_host: str | None,
        smtp_port: int | None,
        smtp_username: str | None,
        smtp_security: str,
        smtp_password: str | None,
    ) -> dict[str, Any]:
        if not 0 <= email_delay_minutes <= 1440:
            raise NotificationError(
                422,
                "invalid_email_delay",
                "Email delay must be between 0 and 1440 minutes.",
            )
        if smtp_security not in {"starttls", "ssl"}:
            raise NotificationError(
                422,
                "invalid_smtp_security",
                "SMTP security must be starttls or ssl.",
            )
        configured = all(
            [
                self._valid_email(recipient_email),
                self._valid_email(sender_email),
                smtp_host,
                smtp_port is not None and 1 <= smtp_port <= 65535,
                smtp_username,
            ]
        )
        with self._session_factory() as database:
            preference = self._preference(database)
            credential_reference = preference.credential_reference
            if smtp_password:
                try:
                    self._credential_store.put(
                        SMTP_CREDENTIAL_REFERENCE,
                        smtp_password,
                        smtp_username,
                    )
                except CredentialStoreError as error:
                    raise NotificationError(
                        409,
                        "credential_store_unavailable",
                        str(error),
                    ) from error
                credential_reference = SMTP_CREDENTIAL_REFERENCE
            if email_enabled and (not configured or not credential_reference):
                raise NotificationError(
                    422,
                    "email_configuration_incomplete",
                    "A complete SMTP configuration and saved credential are required.",
                )
            preference.email_enabled = email_enabled
            preference.email_action_required = email_action_required
            preference.email_warning = email_warning
            preference.email_delay_minutes = email_delay_minutes
            preference.recipient_email = recipient_email or None
            preference.sender_email = sender_email or None
            preference.smtp_host = smtp_host or None
            preference.smtp_port = smtp_port
            preference.smtp_username = smtp_username or None
            preference.smtp_security = smtp_security
            preference.credential_reference = credential_reference
            preference.updated_at = self._now()
            database.commit()
            return self._preference_payload(preference)

    def create(
        self,
        *,
        category: str,
        severity: str,
        title: str,
        message: str,
        related_type: str | None = None,
        related_id: str | None = None,
        deduplication_key: str | None = None,
    ) -> str:
        if severity not in {"required", "action_required", "warning", "info"}:
            raise ValueError(f"unsupported notification severity: {severity}")
        with self._session_factory() as database:
            if deduplication_key:
                existing = database.scalar(
                    select(Notification).where(
                        Notification.deduplication_key == deduplication_key,
                        Notification.read_at.is_(None),
                        Notification.archived_at.is_(None),
                    )
                )
                if existing is not None:
                    return existing.id
            now = self._now()
            notification = Notification(
                id=str(uuid4()),
                category=category,
                severity=severity,
                title=title,
                message=message,
                related_type=related_type,
                related_id=related_id,
                deduplication_key=deduplication_key,
                created_at=now,
            )
            database.add(notification)
            preference = self._preference(database)
            if self._should_email(preference, severity):
                delay = 0 if severity == "required" else preference.email_delay_minutes
                database.add(
                    EmailOutbox(
                        id=str(uuid4()),
                        notification_id=notification.id,
                        status="queued",
                        not_before=now + timedelta(minutes=delay),
                        attempt_count=0,
                        created_at=now,
                    )
                )
            database.commit()
            return notification.id

    def list_notifications(self, include_archived: bool = False) -> list[dict[str, Any]]:
        with self._session_factory() as database:
            statement = select(Notification).order_by(Notification.created_at.desc())
            if not include_archived:
                statement = statement.where(Notification.archived_at.is_(None))
            return [
                self._notification_payload(database, item)
                for item in database.scalars(statement).all()
            ]

    def mark_read(self, notification_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            notification = self._notification(database, notification_id)
            if notification.read_at is None:
                notification.read_at = self._now()
            outbox = database.scalar(
                select(EmailOutbox).where(EmailOutbox.notification_id == notification.id)
            )
            if outbox is not None and outbox.status == "queued":
                outbox.status = "cancelled"
                outbox.last_error = "cancelled because the station notification was read"
            database.commit()
            return self._notification_payload(database, notification)

    def archive(self, notification_id: str) -> dict[str, Any]:
        with self._session_factory() as database:
            notification = self._notification(database, notification_id)
            notification.archived_at = self._now()
            if notification.read_at is None:
                notification.read_at = notification.archived_at
            outbox = database.scalar(
                select(EmailOutbox).where(EmailOutbox.notification_id == notification.id)
            )
            if outbox is not None and outbox.status == "queued":
                outbox.status = "cancelled"
                outbox.last_error = "cancelled because the station notification was archived"
            database.commit()
            return self._notification_payload(database, notification)

    def send_test_email(self) -> dict[str, Any]:
        notification_id = self.create(
            category="email_test",
            severity="required",
            title="云奕学邮件通道测试",
            message="这是一封最小化测试邮件，用于确认本地邮件配置可以正常投递。",
        )
        self.process_outbox()
        notifications = self.list_notifications(include_archived=True)
        return next(item for item in notifications if item["id"] == notification_id)

    def process_outbox(self) -> dict[str, int]:
        sent = 0
        cancelled = 0
        failed = 0
        with self._session_factory() as database:
            preference = self._preference(database)
            due = database.scalars(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status == "queued",
                    EmailOutbox.not_before <= self._now(),
                )
                .order_by(EmailOutbox.created_at)
            ).all()
            for outbox in due:
                notification = self._notification(database, outbox.notification_id)
                if notification.read_at is not None or notification.archived_at is not None:
                    outbox.status = "cancelled"
                    outbox.last_error = "cancelled because the station notification was handled"
                    cancelled += 1
                    continue
                if not preference.email_enabled or not preference.credential_reference:
                    outbox.status = "cancelled"
                    outbox.last_error = "cancelled because email delivery is disabled"
                    cancelled += 1
                    continue
                outbox.attempt_count += 1
                try:
                    secret = self._credential_store.get(preference.credential_reference)
                    self._mail_sender.send(
                        preference,
                        secret,
                        notification.title,
                        self._email_body(notification),
                    )
                except (
                    CredentialStoreError,
                    OSError,
                    RuntimeError,
                    smtplib.SMTPException,
                ) as error:
                    outbox.status = "failed"
                    outbox.last_error = f"{type(error).__name__}: email delivery failed"
                    failed += 1
                else:
                    outbox.status = "sent"
                    outbox.sent_at = self._now()
                    outbox.last_error = None
                    sent += 1
            database.commit()
        return {"sent": sent, "cancelled": cancelled, "failed": failed}

    def _preference(self, database: Session) -> NotificationPreference:
        preference = database.get(NotificationPreference, 1)
        if preference is None:
            raise RuntimeError("notification preference row is missing")
        return preference

    def _notification(self, database: Session, notification_id: str) -> Notification:
        notification = database.get(Notification, notification_id)
        if notification is None:
            raise NotificationError(404, "notification_not_found", "Notification not found.")
        return notification

    def _preference_payload(self, preference: NotificationPreference) -> dict[str, Any]:
        return {
            "email_enabled": preference.email_enabled,
            "email_action_required": preference.email_action_required,
            "email_warning": preference.email_warning,
            "email_delay_minutes": preference.email_delay_minutes,
            "recipient_email": preference.recipient_email,
            "sender_email": preference.sender_email,
            "smtp_host": preference.smtp_host,
            "smtp_port": preference.smtp_port,
            "smtp_username": preference.smtp_username,
            "smtp_security": preference.smtp_security,
            "credential_reference": preference.credential_reference,
            "updated_at": preference.updated_at,
        }

    def _notification_payload(
        self,
        database: Session,
        notification: Notification,
    ) -> dict[str, Any]:
        outbox = database.scalar(
            select(EmailOutbox).where(EmailOutbox.notification_id == notification.id)
        )
        return {
            "id": notification.id,
            "category": notification.category,
            "severity": notification.severity,
            "title": notification.title,
            "message": notification.message,
            "related_type": notification.related_type,
            "related_id": notification.related_id,
            "created_at": notification.created_at,
            "read_at": notification.read_at,
            "archived_at": notification.archived_at,
            "email_status": outbox.status if outbox is not None else None,
        }

    def _should_email(
        self,
        preference: NotificationPreference,
        severity: str,
    ) -> bool:
        if not preference.email_enabled:
            return False
        if severity == "required":
            return True
        if severity == "action_required":
            return preference.email_action_required
        if severity == "warning":
            return preference.email_warning
        return False

    def _email_body(self, notification: Notification) -> str:
        return f"{notification.message}\n\n详细信息和处理操作请在本地云奕学站内通知中心查看。"

    def _valid_email(self, value: str | None) -> bool:
        if value is None or len(value) > 320 or value.count("@") != 1:
            return False
        local, domain = value.rsplit("@", 1)
        return bool(local and "." in domain and not domain.startswith("."))
