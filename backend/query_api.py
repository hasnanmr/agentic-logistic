"""Structured query router (Wave 1, Stream B2)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.query_tool import QueryToolError, run_query
from backend.schemas import QueryResult, QueryStructuredRequest


router = APIRouter(prefix="/api", tags=["query"])


@router.post(
    "/query",
    response_model=QueryResult,
    summary="Run a validated structured analytical request",
)
def post_query(request: QueryStructuredRequest) -> QueryResult:
    """Execute a structured request against the governed dataset.

    Contract violations are rejected by the request model itself; requests that
    parse but are not semantically allowed (an unapproved dimension for the
    chosen metric, an unsortable key) return 400 with the reason.
    """

    try:
        return run_query(request)
    except (QueryToolError, KeyError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error).strip("'")
        ) from error
