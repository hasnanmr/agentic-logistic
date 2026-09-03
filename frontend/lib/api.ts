import { ApiError, type AskResponse, type HistoryTurn, type MetricName, type QueryResult, type QueryStructuredRequest } from "./types";
import { ASK_RESPONSE_FIXTURE, fixtureQueryResult } from "./fixtures";

const DATA_MODE = (process.env.NEXT_PUBLIC_DATA_MODE ?? "api") as "api" | "fixtures";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

const API_USERNAME = process.env.NEXT_PUBLIC_API_USERNAME ?? "";
const API_PASSWORD = process.env.NEXT_PUBLIC_API_PASSWORD ?? "";

function authHeaders(): HeadersInit {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (API_USERNAME || API_PASSWORD) {
    headers.Authorization = `Basic ${btoa(`${API_USERNAME}:${API_PASSWORD}`)}`;
  }
  return headers;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_BASE_URL}. Is the backend running?`, 0);
  }

  if (!response.ok) {
    if (response.status === 401) {
      throw new ApiError("Authentication failed. Check the API credentials in the environment settings.", 401);
    }
    const detail = await response.json().catch(() => null);
    const message =
      detail && typeof detail === "object" && "detail" in detail && typeof detail.detail === "string"
        ? detail.detail
        : `Request failed with status ${response.status}.`;
    throw new ApiError(message, response.status);
  }

  return (await response.json()) as T;
}

export function runQuery(request: QueryStructuredRequest): Promise<QueryResult> {
  if (DATA_MODE === "fixtures") {
    return Promise.resolve(fixtureQueryResult(request.metric, request.dimensions ?? []));
  }
  return post<QueryResult>("/api/query", request);
}

export function askQuestion(question: string, history: HistoryTurn[] = []): Promise<AskResponse> {
  if (DATA_MODE === "fixtures") {
    return Promise.resolve(ASK_RESPONSE_FIXTURE);
  }
  return post<AskResponse>("/api/ask", { question, history });
}

export type { MetricName, QueryResult, QueryStructuredRequest };
