import type { RequestFilter } from "./types";

export interface DashboardFilters {
  start: string;
  end: string;
  carrier: string;
  region: string;
}

export const EMPTY_FILTERS: DashboardFilters = { start: "", end: "", carrier: "", region: "" };

export function buildRequestFilters(filters: DashboardFilters): RequestFilter[] {
  const requestFilters: RequestFilter[] = [];
  if (filters.start) requestFilters.push({ field: "order_date", op: "gte", value: filters.start });
  if (filters.end) requestFilters.push({ field: "order_date", op: "lte", value: filters.end });
  if (filters.carrier) requestFilters.push({ field: "carrier", op: "eq", value: filters.carrier });
  if (filters.region) requestFilters.push({ field: "region", op: "eq", value: filters.region });
  return requestFilters;
}

export function describeFilters(filters: DashboardFilters): string[] {
  const parts: string[] = [];
  if (filters.start && filters.end) parts.push(`dates ${filters.start} to ${filters.end}`);
  else if (filters.start) parts.push(`from ${filters.start}`);
  else if (filters.end) parts.push(`through ${filters.end}`);
  if (filters.carrier) parts.push(`carrier ${filters.carrier}`);
  if (filters.region) parts.push(`region ${filters.region}`);
  return parts;
}

/**
 * Markdown emphasis the model sometimes writes, as plain text.
 *
 * Answers render inside a plain `<p>`, so a stray `**terlambat**` reaches the
 * reader as four literal asterisks. The agent is told not to write markdown
 * (see `backend/agents/agent.py`'s system prompt), but a prompt is guidance and
 * this is the render, so the markers are stripped here as well: emphasis,
 * inline code, list bullets and heading hashes come off, and the words they
 * wrapped stay exactly where they were.
 *
 * What comes off: `*one*`, `**two**` and `***three***` asterisks, `__strong__`
 * and `___strong___`, backticked spans, and - only at the start of a line -
 * `-`/`*`/`+` bullets and `#` headings.
 *
 * What is deliberately left: a single `_`, because this product's prose is full
 * of identifiers that pair them up ("the snake_case column is order_date" would
 * italicise to "the snakecase column is orderdate"); an asterisk or hash mid-
 * sentence ("multiply 3 * 4", "batch #3"), since the line-start anchors and the
 * no-space-after-the-marker rule skip it; and an unmatched marker, which is
 * printed as written rather than guessed at.
 *
 * The narrowness is the point, so extend it only against a real example: a
 * marker this misses reaches the user as a couple of stray characters, while
 * one it strips too eagerly silently rewrites a word.
 */
export function plainText(text: string): string {
  return text
    .split("\n")
    .map((line) =>
      line
        .replace(/^\s{0,3}#{1,6}\s+/, "")
        .replace(/^\s{0,3}[-*+]\s+/, "")
        .replace(/(\*{1,3}|_{2,3})(\S(?:.*?\S)?)\1/g, "$2")
        .replace(/`([^`]+)`/g, "$1"),
    )
    .join("\n")
    .trim();
}
