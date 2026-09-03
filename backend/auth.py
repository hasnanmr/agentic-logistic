"""HTTP Basic authentication for the protected API surface.

Deliberately minimal (PRD 5.0): one credential pair held in environment
variables, verified per request. No login page, no cookie, no session store,
no user table. Basic Auth transmits credentials on every request, so any
non-local deployment must terminate TLS.

The guard is attached once in ``backend.main`` at router-registration time so
that routers owned by other work streams stay untouched.
"""

from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials


router = APIRouter(prefix="/api", tags=["auth"])

_basic_scheme = HTTPBasic(description="Reviewer credentials from APP_USERNAME/APP_PASSWORD.")

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Basic"}


def _configured_credentials() -> tuple[str, str]:
    """Return the expected credential pair from the environment.

    Missing configuration fails closed: an unset password must never be
    interpreted as "this deployment has no authentication".
    """

    username = os.environ.get("APP_USERNAME", "")
    password = os.environ.get("APP_PASSWORD", "")
    if not username or not password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured; set APP_USERNAME and APP_PASSWORD.",
        )
    return username, password


def require_auth(
    credentials: HTTPBasicCredentials = Depends(_basic_scheme),
) -> str:
    """Validate Basic credentials and return the authenticated username."""

    expected_username, expected_password = _configured_credentials()

    # Compare both fields unconditionally so the response time does not reveal
    # which half of the credential pair was wrong.
    username_ok = secrets.compare_digest(credentials.username, expected_username)
    password_ok = secrets.compare_digest(credentials.password, expected_password)
    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers=_UNAUTHORIZED_HEADERS,
        )
    return credentials.username


@router.get("/session", summary="Confirm the current credentials are accepted")
def read_session(username: str = Depends(require_auth)) -> dict[str, str]:
    """Report the authenticated user so the frontend can verify access."""

    return {"username": username}
