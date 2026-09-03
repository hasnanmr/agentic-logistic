import { beforeEach, describe, expect, it, vi } from "vitest";

import { type QueryStructuredRequest } from "./types";

const request: QueryStructuredRequest = {
  operation: "query",
  metric: "delay_rate",
  dimensions: ["carrier"],
  limit: 10,
};

const result = {
  columns: ["carrier", "delay_rate"],
  rows: [["DHL", 11.1]],
  row_count: 1,
  total_groups: 1,
  metric: "delay_rate" as const,
  resolved_time_range: null,
  truncated: false,
};

async function loadApi() {
  vi.resetModules();
  return import("./api");
}

beforeEach(() => {
  delete process.env.NEXT_PUBLIC_DATA_MODE;
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
  delete process.env.NEXT_PUBLIC_API_USERNAME;
  delete process.env.NEXT_PUBLIC_API_PASSWORD;
  vi.unstubAllGlobals();
});

describe("runQuery", () => {
  it("posts a structured query to the configured API", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(result), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.test";
    process.env.NEXT_PUBLIC_API_USERNAME = "reviewer";
    process.env.NEXT_PUBLIC_API_PASSWORD = "secret";

    const { runQuery } = await loadApi();
    await expect(runQuery(request)).resolves.toEqual(result);

    expect(fetchMock).toHaveBeenCalledWith("https://api.example.test/api/query", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Basic ${btoa("reviewer:secret")}`,
      },
      body: JSON.stringify(request),
      cache: "no-store",
    });
  });

  it("uses fixture data when fixture mode is enabled", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    process.env.NEXT_PUBLIC_DATA_MODE = "fixtures";

    const { runQuery } = await loadApi();
    const fixtureResult = await runQuery({ operation: "query", metric: "total_orders" });

    expect(fixtureResult.rows).toEqual([[400]]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns the sample answer from askQuestion in fixture mode", async () => {
    vi.stubGlobal("fetch", vi.fn());
    process.env.NEXT_PUBLIC_DATA_MODE = "fixtures";

    const { askQuestion } = await loadApi();
    const { ASK_RESPONSE_FIXTURE } = await import("./fixtures");
    const response = await askQuestion("Which carrier is most delayed?", [], null);

    // Compared with the fixture rather than a carrier name: this test is about
    // fixture mode answering without a request, and pinning the name here is
    // what made the demo data drift away from what the backend computes.
    expect(response.answer).toBe(ASK_RESPONSE_FIXTURE.answer);
    expect(response.thread_id).toBe("ask-fixture");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("normalizes connection failures into an ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const { runQuery } = await loadApi();

    await expect(runQuery(request)).rejects.toMatchObject({
      name: "Error",
      message: "Cannot reach the API at http://localhost:8080. Is the backend running?",
      status: 0,
    });
  });

  it("surfaces API error details, including authentication failures", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Bad credentials" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Invalid metric" }), { status: 422 }));
    vi.stubGlobal("fetch", fetchMock);
    const { runQuery } = await loadApi();

    await expect(runQuery(request)).rejects.toMatchObject({
      message: "Authentication failed. Check the API credentials in the environment settings.",
      status: 401,
    });
    await expect(runQuery(request)).rejects.toMatchObject({ message: "Invalid metric", status: 422 });
  });
});
