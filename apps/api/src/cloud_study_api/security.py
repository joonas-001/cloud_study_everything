from __future__ import annotations

import ipaddress
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from cloud_study_api.authentication import AuthenticationError
from cloud_study_api.config import Settings
from cloud_study_api.identity import IdentityError
from cloud_study_api.principals import LEGACY_OWNER_PRINCIPAL, Principal, principal_scope

RequestHandler = Callable[[Request], Awaitable[Response]]
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PUBLIC_PATHS = {"/health"}
PUBLIC_AUTH_PATHS = {
    "/auth/session",
    "/auth/login/start",
    "/auth/callback",
    "/auth/account/deletion-cancel",
    "/privacy/deletion-jobs/current/cancel",
}
TAILSCALE_LOGIN_HEADER = "Tailscale-User-Login"
SYNTHETIC_ISSUER_HEADER = "X-Cloud-Study-Synthetic-Issuer"
SYNTHETIC_SUBJECT_HEADER = "X-Cloud-Study-Synthetic-Subject"


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

    if private_preview and not _is_loopback(request):
        response = _error(
            403,
            "trusted_proxy_required",
            "Private preview API traffic must arrive from the local trusted proxy.",
        )
        _apply_security_headers(response, private_preview=True)
        return response

    principal: Principal = LEGACY_OWNER_PRINCIPAL
    auth_mode = settings.authentication.mode
    if auth_mode != "legacy_owner":
        if request.method not in SAFE_METHODS:
            origin = request.headers.get("Origin")
            if origin != settings.authentication.allowed_origin:
                response = _error(
                    403,
                    "csrf_origin_rejected",
                    "State-changing requests require the exact application origin.",
                )
                _apply_security_headers(response, private_preview=private_preview)
                return response
        if request.url.path not in PUBLIC_PATHS | PUBLIC_AUTH_PATHS:
            raw_token = request.cookies.get(settings.authentication.session_cookie_name, "")
            try:
                auth_session = request.app.state.authentication_service.authenticate_session(
                    raw_token
                )
            except AuthenticationError as error:
                response = _error(error.status_code, error.code, str(error))
                _apply_security_headers(response, private_preview=private_preview)
                return response
            principal = auth_session.principal
            request.state.auth_session = auth_session
            if principal.role == "support_restricted":
                response = _error(
                    403,
                    "role_access_denied",
                    "Support accounts have no default access to user data.",
                )
                _apply_security_headers(response, private_preview=private_preview)
                return response
    elif private_preview:
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

    elif settings.synthetic_identity_enabled and request.url.path not in PUBLIC_PATHS:
        issuer = request.headers.get(SYNTHETIC_ISSUER_HEADER, "")
        subject = request.headers.get(SYNTHETIC_SUBJECT_HEADER, "")
        try:
            principal = request.app.state.identity_service.authenticate_synthetic(issuer, subject)
        except IdentityError as error:
            response = _error(error.status_code, error.code, str(error))
            _apply_security_headers(response, private_preview=False)
            return response
        if principal.role == "support_restricted":
            response = _error(
                403,
                "role_access_denied",
                "Support accounts have no default access to user data.",
            )
            _apply_security_headers(response, private_preview=False)
            return response
        request.state.synthetic_identity = True

    request.state.principal = principal
    with principal_scope(principal):
        final_response = await call_next(request)
    _apply_security_headers(final_response, private_preview=private_preview)
    return final_response
