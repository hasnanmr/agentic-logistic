"""FastAPI application composition root.

Wave 1 streams own the router implementations. Keep this module limited to
application-wide configuration and router registration.
"""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Loads .env into the process environment before anything reads os.environ.
import backend.config  # noqa: F401

from backend import ask_api, auth, forecast_api, query_api
from backend.auth import require_auth


app = FastAPI(
    title="AI Logistics Analytics API",
    version="0.1.0",
    description="Read-only logistics analytics, forecasting, and AI Q&A API.",
)

# Wave 2: the frontend runs on a different origin in development, so browser
# requests need CORS. The origin is configurable so a deployed frontend can be
# allow-listed without a code change. Credentials are not cookie-based; the
# frontend sends its Basic header explicitly, hence allow_headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3001")],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# The Basic Auth guard is applied here rather than inside each router module so
# that routers owned by other work streams need no auth-specific edits. Only
# /health stays public, so deployment health checks keep working.
_protected = [Depends(require_auth)]

app.include_router(auth.router)
app.include_router(query_api.router, dependencies=_protected)
app.include_router(ask_api.router, dependencies=_protected)
app.include_router(forecast_api.router, dependencies=_protected)


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Lightweight health endpoint for local and deployment checks."""

    return {"status": "ok"}
