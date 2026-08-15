from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
from pathlib import Path
from typing import Any, cast

from cloud_study_api.runner import (
    DockerRunnerBackend,
    RunnerBackend,
    RunnerCleanupError,
    RunnerProtocolError,
    _read_socket_frame,
    _write_socket_frame,
)

_UnixStreamServerBase: Any = getattr(
    socketserver,
    "UnixStreamServer",
    socketserver.TCPServer,
)


class RunnerBroker:
    """Narrow Docker authority to the three operations required by the API."""

    def __init__(self, backend: RunnerBackend) -> None:
        self._backend = backend

    def handle(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict) or not isinstance(request.get("operation"), str):
            return {"ok": False, "error_code": "invalid_request"}
        operation = request["operation"]
        try:
            if operation == "availability" and set(request) == {"operation"}:
                result: object = self._backend.availability()
            elif operation == "cleanup_stale" and set(request) == {"operation"}:
                result = self._backend.cleanup_stale()
            elif operation == "execute" and set(request) == {"operation", "invocation"}:
                invocation = request.get("invocation")
                if not isinstance(invocation, dict):
                    return {"ok": False, "error_code": "invalid_invocation"}
                result = self._backend.execute(cast(dict[str, Any], invocation))
            else:
                return {"ok": False, "error_code": "operation_not_allowed"}
        except RunnerCleanupError:
            return {"ok": False, "error_code": "cleanup_failed"}
        except RunnerProtocolError:
            return {"ok": False, "error_code": "protocol_invalid"}
        except Exception:
            return {"ok": False, "error_code": "broker_internal_error"}
        return {"ok": True, "result": result}


class _BrokerRequestHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        connection = cast(socket.socket, self.request)
        try:
            payload = _read_socket_frame(connection)
            request = json.loads(payload)
            response = cast(_RunnerBrokerServer, self.server).broker.handle(request)
        except RunnerProtocolError, UnicodeDecodeError, json.JSONDecodeError:
            response = {"ok": False, "error_code": "invalid_request"}
        encoded = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        _write_socket_frame(connection, encoded)


class _RunnerBrokerServer(_UnixStreamServerBase):
    allow_reuse_address = False

    def __init__(self, socket_path: str, broker: RunnerBroker) -> None:
        self.broker = broker
        super().__init__(socket_path, _BrokerRequestHandler)


def serve_runner_broker(
    repository_root: Path,
    socket_path: Path,
    *,
    data_root: Path,
    disk_root: Path,
) -> None:
    if os.name == "nt":
        raise RunnerProtocolError("remote Runner broker requires a POSIX host")
    if not socket_path.is_absolute() or not data_root.is_absolute() or not disk_root.is_absolute():
        raise RunnerProtocolError("remote Runner paths must be absolute")
    parent = socket_path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise RunnerProtocolError("Runner broker socket directory is unavailable")
    if socket_path.exists() or socket_path.is_symlink():
        mode = socket_path.lstat().st_mode
        if not stat.S_ISSOCK(mode):
            raise RunnerProtocolError("Runner broker refuses to replace a non-socket path")
        socket_path.unlink()
    backend = DockerRunnerBackend(
        repository_root,
        data_root=data_root,
        disk_root=disk_root,
    )
    backend.cleanup_stale()
    with _RunnerBrokerServer(str(socket_path), RunnerBroker(backend)) as server:
        socket_path.chmod(0o660)
        server.serve_forever(poll_interval=0.25)
