"""Numeric grounding: proof that a figure came from a tool, not the model.

The safe default is that application code writes every word of an answer. But a
deep agent's value is synthesis across several tool calls, and that is only
usable if the prose can be *checked*. This module extracts every number a
narration states and confirms each one appears in the computed results, so an
agent-written answer can be accepted on evidence rather than on trust.

A number the tools never produced fails the check and the narration is dropped
in favour of composed prose - the invariant holds either way (PRD 9). The one
addition to "computed results" is the constants the metric registry writes its
own formulas with, so the agent can explain how a metric is defined without the
x 100 in the formula reading as an invented measurement.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Final, Iterable

from backend.core.metrics import METRICS
from backend.core.schemas import AskResult


#: Digit groups with optional thousands separators and decimals. Leading signs
#: are deliberately excluded: "-5" in prose is nearly always a range or a dash,
#: and the magnitude is what needs grounding.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: Small integers read as ordinary counting words rather than data ("the top 3
#: carriers", "in 2 groups"), and are also the horizon and limit values the
#: user themselves supplied. Grounding them adds noise without adding safety.
_COUNTING_CEILING: Final = 10


def extract_numbers(text: str) -> list[Decimal]:
    """Every number stated in ``text``, in order of appearance."""

    found: list[Decimal] = []
    for match in _NUMBER.finditer(text):
        try:
            found.append(Decimal(match.group().replace(",", "")))
        except InvalidOperation:  # pragma: no cover - regex admits nothing else
            continue
    return found


def _definition_numbers() -> frozenset[Decimal]:
    """Constants that belong to the metric registry's own formulas.

    ``grounded_numbers`` already admits the numbers in a result's
    ``metric_definition``, on the principle that a number written by the
    registry is the application's, not the model's. These are the same numbers,
    admitted with no result to hang them on - which is what an answer about how
    a metric is *defined* needs, since nothing was computed for it.

    In practice this is the single value 100, the multiplier that turns a ratio
    into a percentage. Without it "delay rate is delayed orders / delivered
    orders x 100" is thrown out as an ungrounded figure and the user gets a
    refusal instead of the definition. The cost is that a bare "the delay rate
    is 100%" would also pass this check on the tool-free path; that is a narrow
    and deliberate trade, and every other invented figure is still rejected.
    """

    return frozenset(
        number
        for definition in METRICS.values()
        for number in extract_numbers(definition.definition_text)
    )


#: Computed once: the registry is frozen at import.
_DEFINITION_NUMBERS: Final = _definition_numbers()


def grounded_numbers(results: Iterable[AskResult]) -> set[Decimal]:
    """Every number a narration for this run is allowed to state.

    Drawn from the payload the user can inspect - table cells, row counts,
    metric bases, forecast details and the composed prose - so anything a
    narration says can be traced to something on screen, plus the constants
    the metric registry's own formulas are written with.
    """

    allowed: set[Decimal] = set(_DEFINITION_NUMBERS)

    def admit(value: object) -> None:
        if isinstance(value, bool) or value is None:
            return
        if isinstance(value, (int, float, Decimal)):
            allowed.add(Decimal(str(value)))

    for result in results:
        allowed.update(extract_numbers(result.answer))

        table = result.table
        if table is not None:
            admit(table.row_count)
            admit(table.total_groups)
            admit(len(table.rows))
            for row in table.rows:
                for cell in row:
                    admit(cell)

        explain = result.explainability
        admit(explain.metric_basis.row_count)
        allowed.update(extract_numbers(explain.metric_definition))

        window = explain.resolved_filters.time_range
        if window is not None:
            for boundary in (window.start, window.end):
                admit(boundary.year)
                admit(boundary.month)
                admit(boundary.day)

        details = explain.forecast_details
        if details is not None:
            admit(details.horizon_weeks)
            admit(details.history_window.observations)
            admit(details.baseline_weekly_orders)
            admit(details.forecast_level)

    return allowed


def _is_grounded(candidate: Decimal, allowed: set[Decimal]) -> bool:
    if candidate in allowed:
        return True

    # A narration may round a computed figure ("18.23%" reported as "18.2%").
    # Accept it when some computed value rounds to exactly what was written, at
    # the precision it was written to.
    exponent = candidate.as_tuple().exponent
    if not isinstance(exponent, int) or exponent > 0:
        return False
    quantum = Decimal(1).scaleb(exponent)
    return any(
        value.quantize(quantum, rounding=ROUND_HALF_UP) == candidate
        for value in allowed
    )


def ungrounded_numbers(text: str, results: Iterable[AskResult]) -> list[Decimal]:
    """Numbers in ``text`` that no tool produced, in order of appearance."""

    allowed = grounded_numbers(results)
    return [
        candidate
        for candidate in extract_numbers(text)
        if not (
            candidate == candidate.to_integral_value()
            and abs(candidate) <= _COUNTING_CEILING
        )
        and not _is_grounded(candidate, allowed)
    ]


def is_grounded(text: str, results: Iterable[AskResult]) -> bool:
    """Whether every number in ``text`` traces to a computed result."""

    return not ungrounded_numbers(text, results)
