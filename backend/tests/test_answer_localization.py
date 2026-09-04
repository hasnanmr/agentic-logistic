"""Composed answers must speak back in the question's own language.

``compose_query_answer``/``compose_forecast_answer`` default to English, so
every existing call site and golden value stays exactly as it was; the tests
below cover the id/zh branches added alongside that default, plus the
end-to-end path: the model declares the question's language as a ``language``
argument on every tool call (see ``backend/tools/agent.py``'s
``_language_field``) rather than the application guessing from the raw text,
and ``backend.agents.orchestrator`` uses that declared language to localize the
unsupported-reason text.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.core.answers import compose_forecast_answer, compose_query_answer
from backend.agents.agent import build_agent
from backend.tools.agent import DECLINE_TOOL, QUERY_TOOL
from backend.tools.forecast import run_forecast
from backend.core.ingestion import load_dataset
from backend.agents.orchestrator import answer_question
from backend.tools.query import run_query
from backend.core.schemas import ForecastStructuredRequest, QueryStructuredRequest
from backend.tests.scripted_model import ScriptedChatModel, ToolCall, asks_for, says, script_for


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


def _ranking(language: str) -> ToolCall:
    """The ranking call the model would make, declaring the question's
    language explicitly - the mechanism this whole module exercises."""

    return ToolCall(
        QUERY_TOOL,
        {
            "metric": "delay_rate",
            "dimensions": ["carrier"],
            "sort": {"by": "delay_rate", "direction": "desc"},
            "limit": 1,
            "language": language,
        },
    )


RANKING = _ranking("en")


# --- compose_query_answer, unit level ---------------------------------------


def test_scalar_answer_in_each_language(dataset: pd.DataFrame) -> None:
    request = QueryStructuredRequest(operation="query", metric="total_orders")
    result = run_query(request, dataset)

    assert compose_query_answer(request, result).endswith("is 400.")
    assert compose_query_answer(request, result, "id").endswith("adalah 400.")
    assert compose_query_answer(request, result, "zh") == "订单总数为 400。"


def test_ranking_answer_in_each_language(dataset: pd.DataFrame) -> None:
    request = QueryStructuredRequest(
        operation="query",
        metric="delay_rate",
        dimensions=["carrier"],
        sort={"by": "delay_rate", "direction": "desc"},
        limit=1,
    )
    result = run_query(request, dataset)
    leader = result.rows[0][0]

    en = compose_query_answer(request, result)
    idn = compose_query_answer(request, result, "id")
    zh = compose_query_answer(request, result, "zh")

    assert f"{leader} has the highest delay rate at" in en
    assert f"{leader} memiliki tingkat keterlambatan tertinggi sebesar" in idn
    assert f"{leader} 的延误率最高" in zh


def test_empty_result_in_each_language(dataset: pd.DataFrame) -> None:
    request = QueryStructuredRequest(
        operation="query",
        metric="delay_rate",
        dimensions=["carrier"],
        filters=[{"field": "region", "op": "eq", "value": "does-not-exist"}],
    )
    result = run_query(request, dataset)
    assert result.total_groups == 0

    assert "No orders match" in compose_query_answer(request, result)
    assert "Tidak ada pesanan" in compose_query_answer(request, result, "id")
    assert "没有订单符合" in compose_query_answer(request, result, "zh")


# --- compose_forecast_answer, unit level ------------------------------------


def test_forecast_answer_in_each_language(dataset: pd.DataFrame) -> None:
    request = ForecastStructuredRequest(
        operation="forecast", metric="order_demand", grain="week", horizon_weeks=4
    )
    result = run_forecast(request, dataset)

    en = compose_forecast_answer(result)
    idn = compose_forecast_answer(result, "id")
    zh = compose_forecast_answer(result, "zh")

    assert "Order demand for the next 4 weeks projects" in en
    assert result.recommendation.text in en  # unchanged English behavior
    assert "Permintaan pesanan untuk 4 minggu ke depan diperkirakan" in idn
    assert "未来 4 周的订单需求预计约为每周" in zh
    # The localized sentences carry the same numbers as the English original,
    # just not the same English words - the grounding invariant still holds.
    assert str(result.recommendation.forecast_level) in idn
    assert str(result.recommendation.forecast_level) in zh


# --- end to end: the model declares the language on its tool call ----------


def ask(question: str, script: list, frame: pd.DataFrame):
    return answer_question(question, build_agent(ScriptedChatModel(script=script)), frame)


def test_a_declared_indonesian_language_gets_an_indonesian_composed_answer(
    dataset: pd.DataFrame,
) -> None:
    response = ask(
        "Kurir mana yang paling sering telat?", script_for(_ranking("id")), dataset
    )

    assert response.unsupported is False
    assert "memiliki" in response.answer and "tertinggi" in response.answer
    assert "has the highest" not in response.answer


def test_a_declared_chinese_language_gets_a_chinese_composed_answer(
    dataset: pd.DataFrame,
) -> None:
    response = ask("哪家承运商延误率最高？", script_for(_ranking("zh")), dataset)

    assert response.unsupported is False
    assert "最高" in response.answer
    assert "has the highest" not in response.answer


def test_an_english_question_is_unaffected(dataset: pd.DataFrame) -> None:
    response = ask("Which carrier has the highest delay rate?", script_for(RANKING), dataset)

    assert response.unsupported is False
    assert "has the highest" in response.answer


def test_omitting_the_language_argument_defaults_to_english(
    dataset: pd.DataFrame,
) -> None:
    """A model that skips the hint field must still get a valid, computed
    answer - just in the safe default language, not a rejected call."""

    bare_ranking = ToolCall(
        QUERY_TOOL,
        {
            "metric": "delay_rate",
            "dimensions": ["carrier"],
            "sort": {"by": "delay_rate", "direction": "desc"},
            "limit": 1,
        },
    )

    response = ask("Kurir mana yang paling sering telat?", script_for(bare_ranking), dataset)

    assert response.unsupported is False
    assert "has the highest" in response.answer


def test_unsupported_reason_is_localized_for_an_indonesian_question(
    dataset: pd.DataFrame,
) -> None:
    """The decline reason is the model's own text (already in the question's
    language, per the system prompt instruction) and passes through verbatim;
    the appended capability summary is localized from the same ``language``
    argument decline_tool carries - covers ``orchestrator._unsupported``."""

    response = ask(
        "Berapa biaya pengiriman per paket?",
        [
            asks_for(
                ToolCall(
                    DECLINE_TOOL,
                    {
                        "reason": "biaya pengiriman tidak ada dalam dataset ini",
                        "language": "id",
                    },
                )
            ),
            says("Data tersebut tidak tersedia."),
        ],
        dataset,
    )

    assert response.unsupported is True
    assert "biaya pengiriman tidak ada dalam dataset ini" in response.unsupported_reason
    assert "Metrik yang didukung" in response.unsupported_reason
    assert "Supported metrics" not in response.unsupported_reason


def test_unsupported_reason_falls_back_to_the_static_english_message(
    dataset: pd.DataFrame,
) -> None:
    """No decline, no failure, no tool error, and ungrounded narration - the
    one path that reaches ``_refusal_reason``'s final static fallback."""

    response = ask(
        "Which carrier has the highest delay rate?",
        [says("It is around 4210 units, roughly.")],  # a stray number fails
        # the numeric-grounding check with no computed result to back it,
        # so the canned refusal is used instead of this invented prose.
        dataset,
    )

    assert response.unsupported is True
    assert "cannot be answered from this dataset" in response.unsupported_reason
