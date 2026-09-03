import { describe, expect, it } from "vitest";

import { buildRequestFilters, describeFilters, EMPTY_FILTERS, type DashboardFilters } from "./format";

describe("buildRequestFilters", () => {
  it("builds filters in the API's expected order", () => {
    const filters: DashboardFilters = {
      start: "2025-01-01",
      end: "2025-03-31",
      carrier: "DHL",
      region: "US-W",
    };

    expect(buildRequestFilters(filters)).toEqual([
      { field: "order_date", op: "gte", value: "2025-01-01" },
      { field: "order_date", op: "lte", value: "2025-03-31" },
      { field: "carrier", op: "eq", value: "DHL" },
      { field: "region", op: "eq", value: "US-W" },
    ]);
  });

  it("omits empty filters", () => {
    expect(buildRequestFilters(EMPTY_FILTERS)).toEqual([]);
    expect(
      buildRequestFilters({ ...EMPTY_FILTERS, carrier: "UPS", end: "2025-12-30" }),
    ).toEqual([
      { field: "order_date", op: "lte", value: "2025-12-30" },
      { field: "carrier", op: "eq", value: "UPS" },
    ]);
  });
});

describe("describeFilters", () => {
  it.each([
    [EMPTY_FILTERS, []],
    [{ ...EMPTY_FILTERS, start: "2025-01-01", end: "2025-03-31" }, ["dates 2025-01-01 to 2025-03-31"]],
    [{ ...EMPTY_FILTERS, start: "2025-01-01" }, ["from 2025-01-01"]],
    [{ ...EMPTY_FILTERS, end: "2025-03-31" }, ["through 2025-03-31"]],
    [{ ...EMPTY_FILTERS, carrier: "FedEx", region: "US-E" }, ["carrier FedEx", "region US-E"]],
  ])("describes %o", (filters, expected) => {
    expect(describeFilters(filters as DashboardFilters)).toEqual(expected);
  });
});
