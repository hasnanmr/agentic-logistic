import type { RequestFilter, Scalar } from "./types";

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

export function formatCount(value: Scalar): string {
  return value === null ? "N/A" : new Intl.NumberFormat("en-US").format(Number(value));
}

export function formatPercent(value: Scalar): string {
  return value === null ? "N/A" : `${Number(value).toFixed(2)}%`;
}

export function formatDays(value: Scalar): string {
  return value === null ? "N/A" : `${Number(value).toFixed(2)} days`;
}
