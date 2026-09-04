"""Numeric grounding: which figures a narration is allowed to state.

The check is what makes an agent-written answer printable. It has to accept
prose that quotes computed figures, including sensibly rounded ones, and reject
prose that states a figure no tool produced.
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd
import pytest

from backend.core import grounding
from backend.core.answers import compose_query_answer, query_explainability
from backend.core.chart_rules import select_chart
from backend.core.ingestion import load_dataset
from backend.tools.query import prepare, run_query
from backend.core.schemas import AskResult, QueryStructuredRequest


@pytest.fixture(scope="module")
def dataset() -> pd.DataFrame:
    return load_dataset("mock_logistics_data.csv")


def result_for(dataset: pd.DataFrame, **payload: object) -> AskResult:
    """A real computed block, so the tests ground against genuine figures."""

    request = QueryStructuredRequest.model_validate(
        {"operation": "query", **payload}
    )
    computed = run_query(request, dataset)
    return AskResult(
        answer=compose_query_answer(request, computed),
        chart=select_chart(computed, request.dimensions),
        table=computed,
        explainability=query_explainability(
            "q", request, computed, prepare(request, dataset).frame
        ),
    )


def test_numbers_are_read_out_of_prose_with_separators() -> None:
    assert grounding.extract_numbers("FedEx 18.2% over 1,204 orders") == [
        Decimal("18.2"),
        Decimal("1204"),
    ]


def test_a_value_from_the_table_is_grounded(dataset: pd.DataFrame) -> None:
    result = result_for(dataset, metric="delay_rate", dimensions=["carrier"])
    leader = result.table.rows[0][-1]

    assert grounding.is_grounded(f"The worst carrier sits at {leader}%.", [result])


def test_an_invented_value_is_not_grounded(dataset: pd.DataFrame) -> None:
    result = result_for(dataset, metric="delay_rate", dimensions=["carrier"])

    assert not grounding.is_grounded("The worst carrier sits at 99.4%.", [result])
    assert grounding.ungrounded_numbers(
        "The worst carrier sits at 99.4%.", [result]
    ) == [Decimal("99.4")]


def test_a_sensibly_rounded_value_is_grounded(dataset: pd.DataFrame) -> None:
    """Prose that rounds a computed figure is still quoting that figure."""

    result = result_for(dataset, metric="delay_rate", dimensions=["carrier"])
    exact = Decimal(str(result.table.rows[0][-1]))
    rounded = exact.quantize(Decimal("0.1"))

    assert grounding.is_grounded(f"about {rounded}%", [result])


def test_small_counting_integers_need_no_grounding(dataset: pd.DataFrame) -> None:
    """"The top 3 carriers" is prose, not a claim about the data."""

    result = result_for(dataset, metric="delay_rate", dimensions=["carrier"])

    assert grounding.is_grounded("I ranked the top 3 carriers for you.", [result])


def test_with_nothing_computed_any_real_figure_is_ungrounded() -> None:
    """A conversational reply has no results, so it may state no figures."""

    assert grounding.is_grounded("I can look up delays and forecast demand.", [])
    assert not grounding.is_grounded("We shipped 4210 orders last year.", [])


def test_row_counts_and_metric_bases_are_grounded(dataset: pd.DataFrame) -> None:
    result = result_for(dataset, metric="delay_rate", dimensions=["carrier"])
    groups = result.table.total_groups
    basis = result.explainability.metric_basis.row_count

    assert grounding.is_grounded(f"{groups} groups over {basis} orders.", [result])


# --- explaining a metric, with nothing computed ----------------------------
#
# "How do you get the delay rate?" asks about the application's rules, not
# about the data, so no tool runs and there is no result to trace against. The
# x 100 in the registry's own formula used to be read as an invented figure,
# which threw the whole answer away and refused the question instead.


def test_a_registry_formula_may_be_stated_with_nothing_computed() -> None:
    assert grounding.is_grounded(
        "Delay rate is delayed orders / delivered orders x 100.", []
    )
    assert grounding.is_grounded(
        "On-time rate is on-time delivered orders / delivered orders x 100.", []
    )


def test_only_the_registry_constants_are_admitted() -> None:
    """The widening is exactly the numbers the registry writes, nothing more -
    a measurement stated with no tool call is still refused."""

    assert grounding._DEFINITION_NUMBERS == frozenset({Decimal("100")})
    assert not grounding.is_grounded("The delay rate is 28.57%.", [])
    assert not grounding.is_grounded("There were 4210 delayed orders.", [])


def test_the_agent_can_explain_a_metric_instead_of_refusing(
    dataset: pd.DataFrame,
) -> None:
    """End to end: the reply reaches the user rather than the canned refusal."""

    from backend.agents.agent import build_agent
    from backend.agents.orchestrator import answer_question
    from backend.tests.scripted_model import ScriptedChatModel, says

    definition = "Delay rate is delayed orders / delivered orders x 100."
    response = answer_question(
        "how do you got the delay rate?",
        build_agent(ScriptedChatModel(script=[says(definition)])),
        dataset,
    )

    assert response.unsupported is False
    assert response.answer == definition


def test_the_prompt_carries_the_registry_denominator() -> None:
    """The model was inventing the formula and getting it wrong - explaining
    delay_rate as a share of total orders. It answers from these words now."""

    from backend.core.answers import METRIC_DEFINITIONS

    assert "delay_rate = delayed orders / delivered orders x 100" in METRIC_DEFINITIONS


# --- a definition question that turns on a real count -----------------------
#
# "Kenapa bukan 400? semua data kan 400" asks why delay_rate's denominator is
# not the whole dataset. Answering it needs two counts, so prose alone cannot
# carry it: 400 stated with nothing computed is an unverified figure and the
# reply is discarded. The agent has to compute the counts it compares.


def _counts_then_explains() -> list:
    from backend.tests.scripted_model import ToolCall, asks_for, says
    from backend.tools.agent import QUERY_TOOL

    return [
        asks_for(
            ToolCall(QUERY_TOOL, {"metric": "total_orders", "language": "id"}),
            ToolCall(QUERY_TOOL, {"metric": "delivered_orders", "language": "id"}),
        ),
        says(
            "Penyebut delay rate adalah pesanan yang sudah terkirim, bukan seluruh "
            "pesanan, sehingga angkanya bukan 400 melainkan 359."
        ),
    ]


DENOMINATOR_QUESTION = "kenapa bukan 400? semua data kan 400"


def test_computing_the_counts_answers_the_denominator_question(
    dataset: pd.DataFrame,
) -> None:
    from backend.agents.agent import build_agent
    from backend.agents.orchestrator import answer_question
    from backend.tests.scripted_model import ScriptedChatModel

    response = answer_question(
        DENOMINATOR_QUESTION,
        build_agent(ScriptedChatModel(script=_counts_then_explains())),
        dataset,
    )

    assert response.unsupported is False
    assert len(response.results) == 2
    assert "400" in response.answer and "359" in response.answer
    # With both counts computed, the agent's own explanation is grounded too,
    # so `verified` narration mode may print it verbatim.
    assert grounding.is_grounded(
        "Penyebutnya pesanan terkirim, bukan seluruh pesanan: 359, bukan 400.",
        response.results,
    )


def test_asserting_the_count_without_computing_it_is_still_refused(
    dataset: pd.DataFrame,
) -> None:
    """The guard that makes the rule above necessary - and it stays in place."""

    from backend.agents.agent import build_agent
    from backend.agents.orchestrator import answer_question
    from backend.tests.scripted_model import ScriptedChatModel, says

    response = answer_question(
        DENOMINATOR_QUESTION,
        build_agent(
            ScriptedChatModel(
                script=[says("400 adalah total pesanan, tetapi penyebutnya yang terkirim.")]
            )
        ),
        dataset,
    )

    assert response.unsupported is True
