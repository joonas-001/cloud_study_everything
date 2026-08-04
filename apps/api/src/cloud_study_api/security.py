from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from cloud_study_api.config import Settings

RequestHandler = Callable[[Request], Awaitable[Response]]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/health"}
TAILSCALE_LOGIN_HEADER = "Tailscale-User-Login"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code, "message": message, "context": {}}},
    )


def _is_loopback(request: Request) -> bool:
    if request.client is None:
        return False
    try:
        return ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        return False


def _apply_security_headers(response: Response, private_preview: bool) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if private_preview:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"


async def enforce_deployment_security(request: Request, call_next: RequestHandler) -> Response:
    settings: Settings = request.app.state.settings
    deployment = settings.deployment
    private_preview = deployment.mode == "private_preview"

    if private_preview:
        if not _is_loopback(request):
            response = _error(
                403,
                "trusted_proxy_required",
                "Private preview API traffic must arrive from the local trusted proxy.",
            )
            _apply_security_headers(response, private_preview=True)
            return response

        if request.url.path not in PUBLIC_PATHS:
            login = request.headers.get(TAILSCALE_LOGIN_HEADER)
            if login is None:
                response = _error(
                    401,
                    "authentication_required",
                    "A Tailscale-authenticated owner identity is required.",
                )
                _apply_security_headers(response, private_preview=True)
                return response
            if login.strip().casefold() != deployment.owner_login:
                response = _error(
                    403,
                    "owner_identity_required",
                    "The authenticated identity is not the configured owner.",
                )
                _apply_security_headers(response, private_preview=True)
                return response
            request.state.authenticated_owner = True

            if request.method not in SAFE_METHODS:
                origin = request.headers.get("Origin")
                if origin != deployment.allowed_origin:
                    response = _error(
                        403,
                        "csrf_origin_rejected",
                        "State-changing requests require the exact private preview origin.",
                    )
                    _apply_security_headers(response, private_preview=True)
                    return response

    final_response = await call_next(request)
    _apply_security_headers(final_response, private_preview=private_preview)
    return final_response
