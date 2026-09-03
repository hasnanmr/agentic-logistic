"""Ask Operations router (Wave 1, Stream E)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.llm import LLMUnavailableError, get_client
from backend.orchestrator import MAX_HISTORY_TURNS, answer_question
from backend.schemas import AskResponse


router = APIRouter(prefix="/api", tags=["ask"])


class AskHistoryTurn(BaseModel):
    """One prior exchange, replayed to the model so follow-ups resolve.

    The conversation stays stateless: the client sends the turns it wants
    considered, bounded at MAX_HISTORY_TURNS, and the server stores nothing.
    """

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    """A natural-language question plus optional prior conversation turns."""

    question: str = Field(min_length=1, max_length=500)
    history: list[AskHistoryTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Answer a natural-language question from the governed dataset",
)
def post_ask(request: AskRequest) -> AskResponse:
    """Interpret the question, run the chosen tool, and return a grounded answer.

    Questions outside the approved grammar come back as a 200 with
    ``unsupported: true`` and an explanation - an unanswerable question is a
    normal outcome, not a transport error.
    """

    try:
        client = get_client()
    except LLMUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    return answer_question(
        request.question,
        client,
        history=[
            message
            for turn in request.history
            for message in (
                {"role": "user", "content": turn.question},
                {"role": "assistant", "content": turn.answer},
            )
        ],
    )
