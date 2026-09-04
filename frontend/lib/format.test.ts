import { describe, expect, it } from "vitest";

import { buildRequestFilters, describeFilters, EMPTY_FILTERS, plainText, type DashboardFilters } from "./format";

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

describe("plainText", () => {
  it.each([
    ["Delay rate is **terlambat** over **total pesanan**.", "Delay rate is terlambat over total pesanan."],
    ["*emphasis* and __strong__ and ***both***", "emphasis and strong and both"],
    ["Use the `delay_rate` metric.", "Use the delay_rate metric."],
    ["## Heading\n- first\n* second\n+ third", "Heading\nfirst\nsecond\nthird"],
  ])("strips markdown from %j", (raw, expected) => {
    expect(plainText(raw)).toBe(expected);
  });

  it.each([
    "DHL is from Germany.",
    "Delay rate rose 5% in batch #3.",
    "Multiply 3 * 4 to get the total.",
    "The snake_case column is order_date.",
  ])("leaves plain prose untouched: %j", (text) => {
    expect(plainText(text)).toBe(text);
  });

  it("leaves single underscores alone, since identifiers pair them up", () => {
    // "the snake_case column is order_date" reads as italics to a greedy rule.
    expect(plainText("_italic_ text")).toBe("_italic_ text");
  });

  it("keeps unmatched markers rather than guessing", () => {
    expect(plainText("An unclosed **marker stays")).toBe("An unclosed **marker stays");
  });
});
