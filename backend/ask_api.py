"""Ask Operations router (Wave 1, Stream E)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend.agent import get_agent
from backend.carrier_knowledge import is_carrier_knowledge_question
from backend.llm import LLMUnavailableError
from backend.orchestrator import MAX_HISTORY_TURNS, answer_question
from backend.schemas import AskResponse
from backend.smalltalk import is_smalltalk


router = APIRouter(prefix="/api", tags=["ask"])


class AskHistoryTurn(BaseModel):
    """One prior exchange, replayed to the agent so follow-ups resolve.

    Only needed by a stateless client. A client that sends ``thread_id``
    instead lets the server hold the conversation and can omit history.
    """

    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    """A natural-language question plus how the conversation is continued."""

    question: str = Field(min_length=1, max_length=500)
    history: list[AskHistoryTurn] = Field(
        default_factory=list, max_length=MAX_HISTORY_TURNS
    )
    #: A thread the server already holds, echoed back from a prior response.
    #: When present, the agent resumes it and ``history`` is ignored.
    thread_id: str | None = Field(default=None, max_length=100)


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Answer a natural-language question from the governed dataset",
)
def post_ask(request: AskRequest) -> AskResponse:
    """Run the question through the agent and return a grounded answer.

    Questions outside the approved grammar come back as a 200 with
    ``unsupported: true`` and an explanation - an unanswerable question is a
    normal outcome, not a transport error.
    """

    # Greetings are answered from templates, so they cost no model call and
    # still work when the analytics provider is unavailable. The thread is
    # echoed back so a greeting mid-conversation does not drop its context.
    if is_smalltalk(request.question):
        return answer_question(request.question, thread_id=request.thread_id)

    # Informational carrier questions use the local source-backed glossary and
    # do not need the LLM. This also keeps the glossary available when only the
    # analytics provider is unavailable. History is not replayed - the glossary
    # answer does not depend on it - but the thread is echoed back so asking
    # "what is JNE?" mid-conversation does not strand the follow-ups after it.
    if is_carrier_knowledge_question(request.question):
        return answer_question(request.question, thread_id=request.thread_id)

    try:
        agent = get_agent()
    except LLMUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error

    return answer_question(
        request.question,
        agent,
        history=[
            message
            for turn in request.history
            for message in (
                {"role": "user", "content": turn.question},
                {"role": "assistant", "content": turn.answer},
            )
        ],
        thread_id=request.thread_id,
    )
