import { describe, expect, it } from "vitest";

import {
  ASK_RESPONSE_FIXTURE,
  CARRIER_RESULT_FIXTURE,
  GROUND_TRUTH,
  WEEKLY_RESULT_FIXTURE,
  fixtureQueryResult,
} from "./fixtures";

describe("fixtureQueryResult", () => {
  it("returns a scalar result for a metric without dimensions", () => {
    const result = fixtureQueryResult("delay_rate", []);

    expect(result).toMatchObject({
      columns: ["delay_rate"],
      rows: [[GROUND_TRUTH.delay_rate]],
      row_count: 1,
      metric: "delay_rate",
      resolved_time_range: null,
      truncated: false,
    });
  });

  it("returns carrier data when carrier is requested", () => {
    expect(fixtureQueryResult("delay_rate", ["carrier"])).toBe(CARRIER_RESULT_FIXTURE);
  });

  it("returns weekly data when week is requested", () => {
    expect(fixtureQueryResult("order_demand", ["week"])).toBe(WEEKLY_RESULT_FIXTURE);
  });
});

describe("ASK_RESPONSE_FIXTURE", () => {
  it("contains a complete answer compatible with the response contract", () => {
    expect(ASK_RESPONSE_FIXTURE.unsupported).toBe(false);
    expect(ASK_RESPONSE_FIXTURE.results).toHaveLength(1);
    // The headline row, and it has to be the one the table puts first: the
    // fixtures mode and the live API must not disagree about who is worst.
    expect(ASK_RESPONSE_FIXTURE.chart?.data[0]).toEqual({ carrier: "UPS", delay_rate: 50.0 });
    expect(ASK_RESPONSE_FIXTURE.answer).toContain("UPS");
    expect(ASK_RESPONSE_FIXTURE.table).toBe(CARRIER_RESULT_FIXTURE);
    expect(ASK_RESPONSE_FIXTURE.explainability?.result_preview).toBe(CARRIER_RESULT_FIXTURE);
  });
});
