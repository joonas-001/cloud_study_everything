from __future__ import annotations

from pathlib import Path
from typing import Any

from cloud_study_api.runner import RunnerProtocolError
from cloud_study_api.runner_broker import RunnerBroker


class _FakeBackend:
    def availability(self) -> dict[str, Any]:
        return {"available": True, "reason_code": None}

    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        return {"audit_id": invocation["audit_id"], "status": "passed"}

    def cleanup_stale(self) -> list[str]:
        return []


class _FailingBackend(_FakeBackend):
    def execute(self, invocation: dict[str, Any]) -> dict[str, Any]:
        raise RunnerProtocolError("untrusted details must not cross the broker")


def test_broker_allows_only_exact_governed_operations() -> None:
    broker = RunnerBroker(_FakeBackend())

    assert broker.handle({"operation": "availability"}) == {
        "ok": True,
        "result": {"available": True, "reason_code": None},
    }
    assert broker.handle({"operation": "cleanup_stale"}) == {"ok": True, "result": []}
    assert broker.handle({"operation": "execute", "invocation": {"audit_id": "audit-1"}}) == {
        "ok": True,
        "result": {"audit_id": "audit-1", "status": "passed"},
    }
    assert broker.handle({"operation": "availability", "extra": True}) == {
        "ok": False,
        "error_code": "operation_not_allowed",
    }
    assert broker.handle({"operation": "shell", "command": "id"}) == {
        "ok": False,
        "error_code": "operation_not_allowed",
    }


def test_broker_does_not_return_internal_protocol_details() -> None:
    broker = RunnerBroker(_FailingBackend())

    assert broker.handle({"operation": "execute", "invocation": {"audit_id": "audit-1"}}) == {
        "ok": False,
        "error_code": "protocol_invalid",
    }


def test_unix_backend_rejects_relative_socket_path() -> None:
    from cloud_study_api.runner import UnixSocketRunnerBackend

    try:
        UnixSocketRunnerBackend(Path("relative.sock"))
    except RunnerProtocolError as error:
        assert "absolute" in str(error)
    else:
        raise AssertionError("relative broker socket path was accepted")
