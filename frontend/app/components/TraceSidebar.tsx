"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import DataTable from "./DataTable";
import type { Explainability, QueryStructuredRequest, RequestFilter } from "@/lib/types";

interface TraceSidebarProps {
  explainability: Explainability | null;
  open: boolean;
  onClose: () => void;
}

const OPERATOR_LABELS: Record<RequestFilter["op"], string> = {
  eq: "is",
  neq: "is not",
  in: "in",
  not_in: "not in",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
};

const ALL_SECTIONS = ["pipeline", "metric", "time", "filters", "forecast", "preview", "request"] as const;
type SectionId = (typeof ALL_SECTIONS)[number];

const DEFAULT_OPEN: SectionId[] = ["pipeline", "metric", "time", "filters", "forecast"];

function isQueryRequest(
  request: Explainability["structured_request"],
): request is QueryStructuredRequest {
  return request.operation === "query";
}

function formatFilterValue(value: RequestFilter["value"]): string {
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join(", ");
  return String(value);
}

function splitPlan(plan: string): string[] {
  return plan
    .split(/->|→/)
    .map((step) => step.trim())
    .filter(Boolean);
}

interface SectionProps {
  id: SectionId;
  title: string;
  badge?: string;
  isOpen: boolean;
  onToggle: (id: SectionId) => void;
  children: React.ReactNode;
}

function Section({ id, title, badge, isOpen, onToggle, children }: SectionProps) {
  return (
    <section className={`trace-section${isOpen ? " is-open" : ""}`}>
      <h3 className="trace-section-heading">
        <button
          type="button"
          className="trace-section-toggle"
          aria-expanded={isOpen}
          aria-controls={`trace-section-${id}`}
          onClick={() => onToggle(id)}
        >
          <span className="trace-caret" aria-hidden="true" />
          <span className="trace-section-title">{title}</span>
          {badge ? <span className="trace-badge">{badge}</span> : null}
        </button>
      </h3>
      <div id={`trace-section-${id}`} className="trace-section-body" hidden={!isOpen}>
        {children}
      </div>
    </section>
  );
}

export default function TraceSidebar({ explainability, open, onClose }: TraceSidebarProps) {
  const [openSections, setOpenSections] = useState<SectionId[]>(DEFAULT_OPEN);
  const [activeStep, setActiveStep] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const lastFocusedRef = useRef<HTMLElement | null>(null);

  const steps = useMemo(
    () => (explainability ? splitPlan(explainability.query_plan) : []),
    [explainability],
  );

  useEffect(() => {
    if (!open) return;
    lastFocusedRef.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      lastFocusedRef.current?.focus();
    };
  }, [open, onClose]);

  useEffect(() => {
    setActiveStep(null);
    setCopied(false);
    setOpenSections(DEFAULT_OPEN);
  }, [explainability]);

  if (!open || !explainability) return null;

  const { structured_request, resolved_filters, forecast_details, metric_basis } = explainability;
  const timeRange = resolved_filters.time_range;
  const filters = resolved_filters.filters;
  const requestJson = JSON.stringify(structured_request, null, 2);

  function toggleSection(id: SectionId) {
    setOpenSections((current) =>
      current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id],
    );
  }

  const availableSections = ALL_SECTIONS.filter(
    (id) => id !== "forecast" || forecast_details !== null,
  );
  const allOpen = availableSections.every((id) => openSections.includes(id));

  async function copyRequest() {
    try {
      await navigator.clipboard.writeText(requestJson);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }

  const baseline = forecast_details?.baseline_weekly_orders ?? null;
  const level = forecast_details?.forecast_level ?? null;
  const deltaPercent =
    baseline !== null && level !== null && baseline !== 0
      ? ((level - baseline) / baseline) * 100
      : null;
  const scale = baseline !== null && level !== null ? Math.max(baseline, level, 1) : 1;

  return (
    <>
      <div className="trace-backdrop" onClick={onClose} aria-hidden="true" />
      <aside
        className="trace-sidebar"
        role="dialog"
        aria-modal="true"
        aria-label="How this answer was produced"
      >
        <header className="trace-header">
          <div>
            <p className="trace-eyebrow">How this answer was produced</p>
            <p className="trace-question">{explainability.question}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="trace-close"
            onClick={onClose}
            aria-label="Close trace panel"
          >
            ×
          </button>
        </header>

        <div className="trace-toolbar">
          <span className="trace-op-chip">{structured_request.operation}</span>
          <button
            type="button"
            className="trace-link-button"
            onClick={() => setOpenSections(allOpen ? [] : [...availableSections])}
          >
            {allOpen ? "Collapse all" : "Expand all"}
          </button>
        </div>

        <div className="trace-scroll">
          <Section
            id="pipeline"
            title="Query plan"
            badge={`${steps.length} steps`}
            isOpen={openSections.includes("pipeline")}
            onToggle={toggleSection}
          >
            <ol className="trace-steps">
              {steps.map((step, index) => (
                <li key={`${step}-${index}`}>
                  <button
                    type="button"
                    className={`trace-step${activeStep === index ? " is-active" : ""}`}
                    onClick={() => setActiveStep((current) => (current === index ? null : index))}
                    aria-pressed={activeStep === index}
                  >
                    <span className="trace-step-index">{index + 1}</span>
                    <span className="trace-step-text">{step}</span>
                  </button>
                </li>
              ))}
            </ol>
          </Section>

          <Section
            id="metric"
            title="Metric"
            isOpen={openSections.includes("metric")}
            onToggle={toggleSection}
          >
            <p className="trace-value">{explainability.metric_definition}</p>
            <div className="trace-stat-row">
              <span className="trace-stat">
                <span className="trace-stat-label">Rows counted</span>
                <span className="trace-stat-value">{metric_basis.row_count}</span>
              </span>
            </div>
            <p className="trace-note">{metric_basis.inclusion_rule}</p>
          </Section>

          <Section
            id="time"
            title="Time range"
            badge={timeRange === null ? "all history" : undefined}
            isOpen={openSections.includes("time")}
            onToggle={toggleSection}
          >
            {timeRange === null ? (
              <p className="trace-value">All available history</p>
            ) : (
              <>
                <p className="trace-value trace-range">
                  <span>{timeRange.start}</span>
                  <span className="trace-range-arrow" aria-hidden="true">
                    →
                  </span>
                  <span>{timeRange.end}</span>
                </p>
                <p
                  className={`trace-tag${timeRange.means === "history_window" ? " trace-tag-warn" : ""}`}
                >
                  {timeRange.means === "history_window"
                    ? "History window — learning data, not a reported period"
                    : "Reported period"}
                </p>
              </>
            )}
          </Section>

          <Section
            id="filters"
            title="Filters"
            badge={filters.length === 0 ? "none" : String(filters.length)}
            isOpen={openSections.includes("filters")}
            onToggle={toggleSection}
          >
            {filters.length === 0 ? (
              <p className="trace-note">No filters were applied.</p>
            ) : (
              <ul className="trace-filters">
                {filters.map((filter, index) => (
                  <li key={`${filter.field}-${index}`} className="trace-filter">
                    <span className="trace-filter-field">{filter.field.replaceAll("_", " ")}</span>
                    <span className="trace-filter-op">{OPERATOR_LABELS[filter.op] ?? filter.op}</span>
                    <span className="trace-filter-value">{formatFilterValue(filter.value)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {forecast_details ? (
            <Section
              id="forecast"
              title="Forecast"
              badge={`${forecast_details.horizon_weeks}w`}
              isOpen={openSections.includes("forecast")}
              onToggle={toggleSection}
            >
              {forecast_details.insufficient_data ? (
                <p className="trace-tag trace-tag-warn">
                  Insufficient history — treat this forecast with caution.
                </p>
              ) : null}
              <div className="trace-stat-row">
                <span className="trace-stat">
                  <span className="trace-stat-label">Method</span>
                  <span className="trace-stat-value">{forecast_details.method}</span>
                </span>
                <span className="trace-stat">
                  <span className="trace-stat-label">Observations</span>
                  <span className="trace-stat-value">
                    {forecast_details.history_window.observations}
                  </span>
                </span>
              </div>
              <p className="trace-note">
                Learned from {forecast_details.history_window.start} to{" "}
                {forecast_details.history_window.end}
              </p>

              {baseline === null || level === null ? (
                <p className="trace-note">Baseline vs forecast unavailable (insufficient history).</p>
              ) : (
                <div className="trace-compare">
                  <div className="trace-compare-row">
                    <span className="trace-compare-label">Baseline</span>
                    <span className="trace-compare-bar">
                      <span
                        className="trace-compare-fill trace-compare-fill-baseline"
                        style={{ width: `${(baseline / scale) * 100}%` }}
                      />
                    </span>
                    <span className="trace-compare-value">{baseline}</span>
                  </div>
                  <div className="trace-compare-row">
                    <span className="trace-compare-label">Forecast</span>
                    <span className="trace-compare-bar">
                      <span
                        className="trace-compare-fill trace-compare-fill-forecast"
                        style={{ width: `${(level / scale) * 100}%` }}
                      />
                    </span>
                    <span className="trace-compare-value">{level}</span>
                  </div>
                  {deltaPercent === null ? null : (
                    <p className="trace-note">
                      Forecast is {deltaPercent >= 0 ? "+" : ""}
                      {deltaPercent.toFixed(1)}% vs the trailing baseline (orders/week).
                    </p>
                  )}
                </div>
              )}

              <p className="trace-subheading">Recommendation rule</p>
              <p className="trace-value">{forecast_details.recommendation_rule}</p>
            </Section>
          ) : null}

          <Section
            id="preview"
            title="Result preview"
            badge={`${explainability.result_preview.row_count} rows`}
            isOpen={openSections.includes("preview")}
            onToggle={toggleSection}
          >
            {explainability.result_preview.row_count === 0 ? (
              <p className="trace-note">No rows returned.</p>
            ) : (
              <>
                <DataTable result={explainability.result_preview} />
                {explainability.result_preview.truncated ? (
                  <p className="trace-note">Preview truncated.</p>
                ) : null}
              </>
            )}
          </Section>

          <Section
            id="request"
            title="Structured request"
            isOpen={openSections.includes("request")}
            onToggle={toggleSection}
          >
            <div className="trace-code-actions">
              <button type="button" className="trace-link-button" onClick={() => void copyRequest()}>
                {copied ? "Copied" : "Copy JSON"}
              </button>
            </div>
            <pre className="trace-code">{requestJson}</pre>
            {isQueryRequest(structured_request) && structured_request.sort ? (
              <p className="trace-note">
                Sorted by {structured_request.sort.by} ({structured_request.sort.direction})
                {structured_request.limit ? `, limit ${structured_request.limit}` : ""}.
              </p>
            ) : null}
          </Section>
        </div>
      </aside>
    </>
  );
}
