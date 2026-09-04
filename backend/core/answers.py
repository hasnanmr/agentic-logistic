"""Composition of grounded answers, explainability, and previews.

Split out of the orchestrator so both the agent's tools and the orchestrator
can compose from the same code. Everything here is pure: it turns a validated
request plus a computed result into prose and an explainability payload, and it
is the *only* place answer text is written. The model never writes a figure, so
a hallucinated number has nowhere to enter (PRD 9).
"""

from __future__ import annotations

import re
from typing import Final

import pandas as pd

from backend.tools.forecast import MIN_HISTORY_WEEKS, THRESHOLD, build_forecast_details
from backend.core.metrics import METRICS, get_metric
from backend.core.schemas import (
    Explainability,
    ExplainedTimeRange,
    ForecastRecommendation,
    ForecastResult,
    ForecastStructuredRequest,
    MetricBasis,
    QueryResult,
    QueryStructuredRequest,
    ResolvedFilters,
    SmalltalkLanguage,
)


#: Reported back to the user whenever a question falls outside the grammar.
#: English only - this is what the model reads in its own system prompt, not
#: user-facing prose; :func:`supported_capabilities` is the localized version
#: attached to a user-facing unsupported response.
SUPPORTED_CAPABILITIES: Final = (
    "Supported metrics: "
    + ", ".join(sorted(METRICS))
    + ". Supported breakdowns: carrier, region, origin_city, destination_city, "
    "product_category, status, and time buckets (day, week, month). "
    "Demand can be forecast 1-8 weeks ahead."
)

_SUPPORTED_CAPABILITIES_ID: Final = (
    "Metrik yang didukung: "
    + ", ".join(sorted(METRICS))
    + ". Rincian yang didukung: carrier, region, origin_city, destination_city, "
    "product_category, status, dan satuan waktu (day, week, month). "
    "Permintaan dapat diperkirakan untuk 1-8 minggu ke depan."
)

_SUPPORTED_CAPABILITIES_ZH: Final = (
    "支持的指标："
    + "、".join(sorted(METRICS))
    + "。支持的细分：carrier、region、origin_city、destination_city、"
    "product_category、status，以及时间粒度（day、week、month）。"
    "可预测未来 1-8 周的需求。"
)

_SUPPORTED_CAPABILITIES_BY_LANGUAGE: Final[dict[SmalltalkLanguage, str]] = {
    "id": _SUPPORTED_CAPABILITIES_ID,
    "en": SUPPORTED_CAPABILITIES,
    "zh": _SUPPORTED_CAPABILITIES_ZH,
}


def supported_capabilities(language: SmalltalkLanguage = "en") -> str:
    """The user-facing capability summary, in the question's language."""

    return _SUPPORTED_CAPABILITIES_BY_LANGUAGE[language]


_PERCENT_METRICS: Final[frozenset[str]] = frozenset({"on_time_rate", "delay_rate"})

#: Metric labels are defined once, in English, in the frozen metric registry
#: (``backend/core/metrics.py``). This is a presentation-only translation of those
#: same labels for composed prose - the registry itself is untouched, so the
#: API's ``columns``/``metric`` identifiers stay English everywhere.
_METRIC_LABELS: Final[dict[str, dict[SmalltalkLanguage, str]]] = {
    "total_orders": {"id": "Total Pesanan", "zh": "订单总数"},
    "delivered_orders": {"id": "Pesanan Terkirim", "zh": "已送达订单数"},
    "delayed_orders": {"id": "Pesanan Terlambat", "zh": "延误订单数"},
    "on_time_rate": {"id": "Tingkat Tepat Waktu", "zh": "准时率"},
    "delay_rate": {"id": "Tingkat Keterlambatan", "zh": "延误率"},
    "avg_delivery_time": {"id": "Rata-rata Waktu Pengiriman", "zh": "平均配送时间"},
    "order_demand": {"id": "Permintaan Pesanan", "zh": "订单需求"},
}


def _metric_label(metric_name: str, language: SmalltalkLanguage) -> str:
    if language == "en":
        return get_metric(metric_name).label
    return _METRIC_LABELS.get(metric_name, {}).get(language) or get_metric(metric_name).label


_NOT_AVAILABLE: Final[dict[SmalltalkLanguage, str]] = {
    "id": "tidak tersedia",
    "en": "not available",
    "zh": "无数据",
}

_DAYS_UNIT: Final[dict[SmalltalkLanguage, str]] = {
    "id": "hari",
    "en": "days",
    "zh": "天",
}


def format_metric(
    metric_name: str, value: object, language: SmalltalkLanguage = "en"
) -> str:
    if value is None:
        return _NOT_AVAILABLE[language]
    if metric_name in _PERCENT_METRICS:
        return f"{value}%"
    if metric_name == "avg_delivery_time":
        return f"{value} {_DAYS_UNIT[language]}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def query_plan(request: QueryStructuredRequest) -> str:
    steps = ["filter orders"] if request.filters else []
    if request.time_range is not None:
        steps.append("restrict to the resolved time range")
    if request.dimensions:
        steps.append(f"group by {', '.join(request.dimensions)}")
    steps.append(f"compute {request.metric}")
    if request.sort is not None:
        steps.append(f"sort by {request.sort.by} {request.sort.direction}")
    if request.dimensions:
        steps.append(f"limit {request.limit}")
    return " -> ".join(steps)


_NO_ROWS_MATCH: Final[dict[SmalltalkLanguage, str]] = {
    "id": "Tidak ada pesanan yang cocok dengan filter tersebut, jadi tidak ada yang bisa dilaporkan.",
    "en": "No orders match those filters, so there is nothing to report.",
    "zh": "没有订单符合这些筛选条件，因此没有可报告的内容。",
}

_SUPERLATIVE_WORD: Final[dict[SmalltalkLanguage, dict[str, str]]] = {
    "id": {"desc": "tertinggi", "asc": "terendah"},
    "en": {"desc": "highest", "asc": "lowest"},
    "zh": {"desc": "最高", "asc": "最低"},
}


def compose_query_answer(
    request: QueryStructuredRequest,
    result: QueryResult,
    language: SmalltalkLanguage = "en",
) -> str:
    label = _metric_label(request.metric, language)

    if not request.dimensions:
        value = format_metric(request.metric, result.rows[0][0], language)
        if language == "id":
            return f"{label} adalah {value}."
        if language == "zh":
            return f"{label}为 {value}。"
        return f"{label} is {value}."

    if result.total_groups == 0:
        return _NO_ROWS_MATCH[language]

    dimension = request.dimensions[0]
    leader = result.rows[0]
    if request.sort is not None and request.limit == 1:
        superlative = _SUPERLATIVE_WORD[language][request.sort.direction]
        value = format_metric(request.metric, leader[-1], language)
        if language == "id":
            return f"{leader[0]} memiliki {label.lower()} {superlative} sebesar {value}."
        if language == "zh":
            return f"{leader[0]} 的{label}{superlative}，为 {value}。"
        return f"{leader[0]} has the {superlative} {label.lower()} at {value}."

    leader_value = format_metric(request.metric, leader[-1], language)
    if language == "id":
        noun = "kelompok"
        summary = f"{label} berdasarkan {dimension} pada {result.total_groups} {noun}."
        if request.sort is not None:
            summary += f" Teratas: {leader[0]} sebesar {leader_value}."
        if result.truncated:
            summary += f" Menampilkan {len(result.rows)} pertama."
        return summary
    if language == "zh":
        summary = f"按 {dimension} 分组的{label}，共 {result.total_groups} 组。"
        if request.sort is not None:
            summary += f" 领先：{leader[0]}，为 {leader_value}。"
        if result.truncated:
            summary += f" 仅显示前 {len(result.rows)} 项。"
        return summary

    summary = (
        f"{label} by {dimension} across {result.total_groups} "
        f"{'group' if result.total_groups == 1 else 'groups'}."
    )
    if request.sort is not None:
        summary += f" Leading: {leader[0]} at {leader_value}."
    if result.truncated:
        summary += f" Showing the first {len(result.rows)}."
    return summary


_INSUFFICIENT_HISTORY: Final[dict[SmalltalkLanguage, str]] = {
    "id": "Riwayat data tidak cukup untuk memperkirakan permintaan: {reason}.",
    "en": "There is not enough history to forecast demand: {reason}.",
    "zh": "历史数据不足，无法预测需求：{reason}。",
}


def _insufficient_history_reason(
    result: ForecastResult, language: SmalltalkLanguage
) -> str:
    """The ``{reason}`` clause above, in the question's language.

    English reuses ``result.insufficient_data_reason`` verbatim - written
    once in :mod:`backend.tools.forecast` from the same ``observations`` count used
    here - so English behavior is unchanged. Indonesian and Chinese are
    rebuilt from that count and ``MIN_HISTORY_WEEKS`` directly, the same
    pattern as ``_recommendation_sentence``, so :mod:`backend.tools.forecast`
    (owned by Stream D) needs no change.
    """

    if language == "en":
        return result.insufficient_data_reason or ""

    observations = result.history_window.observations
    if language == "id":
        return (
            f"hanya {observations} minggu lengkap riwayat yang tersedia; "
            f"dibutuhkan setidaknya {MIN_HISTORY_WEEKS} minggu untuk membuat "
            "perkiraan mingguan"
        )
    return (
        f"仅有 {observations} 个完整周的历史数据；每周预测至少需要 "
        f"{MIN_HISTORY_WEEKS} 个完整周的数据"
    )


def _recommendation_sentence(
    recommendation: ForecastRecommendation, language: SmalltalkLanguage
) -> str:
    """The capacity-recommendation sentence, in the question's language.

    English reuses ``recommendation.text`` verbatim - written once in
    :mod:`backend.tools.forecast` from the same numeric fields used here - so
    English behavior is unchanged. Indonesian and Chinese are rebuilt from
    those numeric fields directly rather than translating that string, so
    :mod:`backend.tools.forecast` (owned by the tools package) needs no change.
    """

    if language == "en":
        return recommendation.text

    baseline = recommendation.baseline_weekly_orders
    level = recommendation.forecast_level
    delta = recommendation.delta_orders_per_week

    if baseline == 0:
        return {
            "id": (
                "Baseline 4 minggu terakhir adalah nol pesanan per minggu, "
                "sehingga tidak ada sinyal kapasitas yang berarti untuk "
                "ditindaklanjuti."
            ),
            "zh": "过去4周的基线为每周零单，因此没有值得据以采取行动的产能信号。",
        }[language]

    change = (level - baseline) / baseline
    if language == "id":
        lead = (
            f"Perkiraan rata-rata {level:.2f} pesanan/minggu dibanding baseline "
            f"4 minggu terakhir sebesar {baseline:.2f} ({change:+.1%})"
        )
        if recommendation.action == "increase_capacity":
            return (
                f"{lead}, di atas ambang batas {THRESHOLD:.0%} — pertimbangkan "
                f"menambah kapasitas sekitar {delta} pesanan/minggu lagi."
            )
        if recommendation.action == "no_increase":
            return (
                f"{lead}, di bawah ambang batas {THRESHOLD:.0%} — permintaan "
                "melunak, tidak perlu tambahan kapasitas."
            )
        return (
            f"{lead}, dalam ambang batas {THRESHOLD:.0%} — pertahankan kapasitas "
            "saat ini."
        )

    # zh
    lead = (
        f"预测均值为每周 {level:.2f} 单，相较过去4周基线 {baseline:.2f} 单"
        f"（{change:+.1%}）"
    )
    if recommendation.action == "increase_capacity":
        return f"{lead}，高于 {THRESHOLD:.0%} 的阈值——建议将每周产能再提高约 {delta} 单。"
    if recommendation.action == "no_increase":
        return f"{lead}，低于 {THRESHOLD:.0%} 的阈值——需求走弱，无需增加产能。"
    return f"{lead}，处于 {THRESHOLD:.0%} 阈值范围内——维持现有产能。"


def compose_forecast_answer(
    result: ForecastResult, language: SmalltalkLanguage = "en"
) -> str:
    if result.insufficient_data:
        return _INSUFFICIENT_HISTORY[language].format(
            reason=_insufficient_history_reason(result, language)
        )

    level = result.recommendation.forecast_level
    weeks = result.horizon_weeks
    recommendation_sentence = _recommendation_sentence(result.recommendation, language)

    if language == "id":
        return (
            f"Permintaan pesanan untuk {weeks} minggu ke depan diperkirakan "
            f"sekitar {level} pesanan per minggu. {recommendation_sentence}"
        )
    if language == "zh":
        return f"未来 {weeks} 周的订单需求预计约为每周 {level} 单。{recommendation_sentence}"

    return (
        f"Order demand for the next {weeks} week{'s' if weeks != 1 else ''} projects "
        f"to about {level} orders per week. {recommendation_sentence}"
    )


def forecast_preview(result: ForecastResult) -> QueryResult:
    """The forecast's underlying series, as an inspectable table (FR-10)."""

    rows: list[list[object]] = [
        [point.period, point.value, "actual"] for point in result.history
    ]
    rows += [[point.period, point.value, "forecast"] for point in result.forecast]
    return QueryResult(
        columns=["period", "order_demand", "series"],
        rows=rows,
        row_count=len(rows),
        total_groups=len(rows),
        metric="order_demand",
        resolved_time_range=None,
        truncated=False,
    )


def query_explainability(
    question: str,
    request: QueryStructuredRequest,
    result: QueryResult,
    frame: pd.DataFrame,
) -> Explainability:
    metric = get_metric(request.metric)
    window = result.resolved_time_range
    return Explainability(
        question=question,
        structured_request={"operation": "query", **request.model_dump(mode="json")},
        metric_definition=metric.describe(frame),
        metric_basis=MetricBasis(
            row_count=metric.basis_count(frame), inclusion_rule=metric.inclusion_rule
        ),
        resolved_filters=ResolvedFilters(
            time_range=(
                ExplainedTimeRange(
                    start=window.start, end=window.end, means="reported_period"
                )
                if window is not None
                else None
            ),
            filters=request.filters,
        ),
        query_plan=query_plan(request),
        result_preview=result,
        forecast_details=None,
    )


def forecast_explainability(
    question: str, request: ForecastStructuredRequest, result: ForecastResult
) -> Explainability:
    return Explainability(
        question=question,
        structured_request={
            "operation": "forecast",
            **request.model_dump(mode="json"),
        },
        metric_definition=(
            "orders per complete ISO week "
            f"(n={result.history_window.observations} weeks)"
        ),
        metric_basis=MetricBasis(
            row_count=result.history_window.observations,
            inclusion_rule=(
                "complete ISO weeks only; part-weeks at either end of the data "
                "are excluded because they measure a shorter period"
            ),
        ),
        resolved_filters=ResolvedFilters(
            time_range=ExplainedTimeRange(
                start=result.history_window.start,
                end=result.history_window.end,
                means="history_window",
            ),
            filters=request.filters,
        ),
        query_plan=(
            "aggregate orders per complete ISO week -> fit a 12-week trend -> "
            f"project {result.horizon_weeks} week(s) -> compare with the trailing "
            "baseline"
        ),
        result_preview=forecast_preview(result),
        forecast_details=build_forecast_details(result),
    )


# --- localizing the Query Tool's own validation errors ----------------------
#
# These messages are raised inside backend/tools/query.py (the query tool,
# left untouched) and are read twice: by the model, to self-correct a
# rejected call, and - only when every attempt still failed - by the end
# user, appended after the (already localized) capability summary in an
# unsupported response. Translating by pattern here, rather than editing
# tools/query.py, keeps its precise English wording as the thing the model
# corrects against while still giving the user one message in one language
# instead of an English clause glued to a translated suffix.

_DIMENSION_NOT_APPROVED: Final = re.compile(
    r"^dimension\(s\) (?P<dims>.+?) are not approved for metric '(?P<metric>[^']+)'; "
    r"approved: (?P<approved>.+)$"
)
_OPERATOR_DATE_FIELDS_ONLY: Final = re.compile(
    r"^operator '(?P<op>[^']+)' is only supported on date fields "
    r"\((?P<fields>.+?)\), not on '(?P<field>[^']+)'$"
)
_SORT_KEY_NOT_ALLOWED: Final = re.compile(
    r"^cannot sort by '(?P<sort_key>[^']+)': sort by the requested metric "
    r"\('(?P<metric>[^']+)'\) or one of its dimensions$"
)
_DUPLICATE_DIMENSIONS: Final = "dimensions must not repeat"


def localize_validation_message(message: str, language: SmalltalkLanguage) -> str:
    """Best-effort translation of a known Query Tool validation message.

    Only the handful of messages ``backend/tools/query.py`` can actually raise
    for a well-formed contract are recognised (the rest are pydantic-level
    rejections that never reach this text). A message that does not match any
    known shape - a validation rule this function was never told about - is
    returned unchanged rather than mistranslated by guesswork.
    """

    if language == "en":
        return message

    stripped = message.rstrip(".")

    match = _DIMENSION_NOT_APPROVED.match(stripped)
    if match:
        if language == "id":
            return (
                f"dimensi {match['dims']} tidak didukung untuk metrik "
                f"'{match['metric']}'; yang didukung: {match['approved']}"
            )
        return (
            f"指标 '{match['metric']}' 不支持维度 {match['dims']}；"
            f"支持的维度：{match['approved']}"
        )

    match = _OPERATOR_DATE_FIELDS_ONLY.match(stripped)
    if match:
        if language == "id":
            return (
                f"operator '{match['op']}' hanya didukung pada kolom tanggal "
                f"({match['fields']}), bukan pada '{match['field']}'"
            )
        return (
            f"运算符 '{match['op']}' 仅支持日期字段（{match['fields']}），"
            f"不支持 '{match['field']}'"
        )

    match = _SORT_KEY_NOT_ALLOWED.match(stripped)
    if match:
        if language == "id":
            return (
                f"tidak dapat mengurutkan berdasarkan '{match['sort_key']}': "
                f"urutkan berdasarkan metrik yang diminta ('{match['metric']}') "
                "atau salah satu dimensinya"
            )
        return (
            f"无法按 '{match['sort_key']}' 排序：请按所请求的指标"
            f"（'{match['metric']}'）或其维度之一排序"
        )

    if stripped == _DUPLICATE_DIMENSIONS:
        return "dimensi tidak boleh berulang" if language == "id" else "维度不能重复"

    return message
