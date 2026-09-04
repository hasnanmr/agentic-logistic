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
