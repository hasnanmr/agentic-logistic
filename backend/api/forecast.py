"""Demand forecasting router (Wave 1, Stream D)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from backend.tools.forecast import run_forecast
from backend.tools.query import QueryToolError
from backend.core.schemas import ForecastResult, ForecastStructuredRequest


router = APIRouter(prefix="/api", tags=["forecast"])


@router.post(
    "/forecast",
    response_model=ForecastResult,
    summary="Forecast weekly order demand over a bounded horizon",
)
def post_forecast(request: ForecastStructuredRequest) -> ForecastResult:
    """Project weekly demand and attach a rule-based capacity recommendation.

    ``horizon_weeks`` is bounded 1-8 by the request contract. Too little history
    returns a successful response carrying ``insufficient_data`` rather than a
    fabricated number.
    """

    try:
        return run_forecast(request)
    except (QueryToolError, KeyError) as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error).strip("'")
        ) from error
