"use client";

import { useEffect, useRef, useState } from "react";

import AskChart from "../components/AskChart";
import DataTable from "../components/DataTable";
import EmptyState from "../components/EmptyState";
import { SendIcon, SparkleIcon } from "../components/icons";
import TraceSidebar from "../components/TraceSidebar";
import { askQuestion } from "@/lib/api";
import { plainText } from "@/lib/format";
import { ASK_RESPONSE_FIXTURE } from "@/lib/fixtures";
import { ApiError, type AskResponse, type AskResult, type HistoryTurn } from "@/lib/types";

const EXAMPLE_QUESTIONS = [
  "Which carrier has the highest delay rate?",
  "How many orders were delivered last month?",
  "Forecast demand for the next 4 weeks.",
];

const MAX_TURNS = 10;

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  response?: AskResponse;
  isError?: boolean;
}

/** Which result block's trace panel is open, if any. */
interface TraceTarget {
  message: number;
  result: number;
}

/**
 * A short label for one result block, used when an answer has several.
 * Taken from the request the agent actually made, so it names what was asked
 * of the data rather than guessing from the prose.
 */
function blockLabel(result: AskResult): string {
  const request = result.explainability.structured_request;
  if (request.operation === "forecast") {
    return `demand forecast, ${request.horizon_weeks} weeks`;
  }
  const dimensions = request.dimensions ?? [];
  return dimensions.length > 0
    ? `${request.metric} by ${dimensions.join(", ")}`
    : request.metric;
}

export default function AskPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<TraceTarget | null>(null);
  // The server holds the conversation once it hands back a thread; history is
  // still sent so the first turn and a forgotten thread both work.
  const [threadId, setThreadId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const turns: HistoryTurn[] = messages
    .filter((message) => !message.isError && message.text)
    .reduce<HistoryTurn[]>((accumulated, message, index, all) => {
      if (message.role !== "user") return accumulated;
      const reply = all[index + 1];
      if (reply && reply.role === "assistant" && !reply.isError) {
        accumulated.push({ question: message.text, answer: reply.text });
      }
      return accumulated;
    }, []);
  const turnCount = turns.length;
  const limitReached = turnCount >= MAX_TURNS;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  async function submit(rawQuestion: string) {
    const trimmed = rawQuestion.trim();
    if (!trimmed || loading || limitReached) return;
    setError(null);
    setInput("");
    setMessages((current) => [...current, { role: "user", text: trimmed }]);
    setLoading(true);
    try {
      const response = await askQuestion(trimmed, turns.slice(-MAX_TURNS), threadId);
      setThreadId(response.thread_id ?? threadId);
      setMessages((current) => [
        ...current,
        { role: "assistant", text: response.unsupported ? response.unsupported_reason ?? "" : response.answer, response },
      ]);
    } catch (caught) {
      if (caught instanceof ApiError && (caught.status === 503 || caught.status === 0)) {
        const sample = JSON.parse(JSON.stringify(ASK_RESPONSE_FIXTURE)) as AskResponse;
        setMessages((current) => [
          ...current,
          { role: "assistant", text: sample.answer, response: sample },
        ]);
        setError("The AI service is not available right now, so a sample answer was shown.");
      } else {
        const message = caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.";
        setMessages((current) => [...current, { role: "assistant", text: message, isError: true }]);
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page ask-page">
      <div className="page-header">
        <h1>Ask Operations</h1>
        <p className="page-subtitle">
          Chat about deliveries, delays, or demand. Follow-up questions use the
          conversation so far ({turnCount}/{MAX_TURNS} turns).
        </p>
      </div>

      <section className="panel chat-panel" aria-label="Conversation">
        <div className="chat-scroll">
          {messages.length === 0 ? (
            <div className="chat-empty">
              <span className="chat-empty-icon" aria-hidden="true">
                <SparkleIcon />
              </span>
              <p>Ask a question to start the conversation.</p>
              <div className="ask-examples">
                {EXAMPLE_QUESTIONS.map((example) => (
                  <button
                    key={example}
                    type="button"
                    className="chip"
                    onClick={() => void submit(example)}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((message, index) => (
              <div key={index} className={`chat-row chat-row-${message.role}`}>
                {message.role === "assistant" ? (
                  <span className="chat-avatar chat-avatar-assistant" aria-hidden="true">
                    <SparkleIcon className="chat-avatar-icon" />
                  </span>
                ) : null}
                <div className={`chat-bubble chat-bubble-${message.role}${message.isError ? " chat-bubble-error" : ""}`}>
                  {message.role === "user" ? (
                    <p className="chat-text">{message.text}</p>
                  ) : message.isError ? (
                    <p className="chat-text">{message.text}</p>
                  ) : message.response && message.response.unsupported ? (
                    <>
                      <p className="chat-text">That question is outside what the data can answer.</p>
                      {/* The refusal quotes the agent's own decline reason, so
                          it goes through the same markdown cleanup as an answer. */}
                      <p className="chat-text muted">{plainText(message.response.unsupported_reason ?? "")}</p>
                    </>
                  ) : (
                    <>
                      {/* Model-written prose, rendered as plain text: strip any
                          markdown it wrote so `**bold**` is not read literally. */}
                      <p className="chat-text">{plainText(message.text)}</p>
                      {/* One block per tool call the agent made. A single
                          figure renders exactly as it always did; a compound
                          question adds a labelled block for each part. */}
                      {(message.response?.results ?? []).map((result, resultIndex) => {
                        const isOpen =
                          trace?.message === index && trace?.result === resultIndex;
                        const several = (message.response?.results.length ?? 0) > 1;
                        return (
                          <div className="ask-result-block" key={resultIndex}>
                            {several ? (
                              <p className="ask-result-label">{blockLabel(result)}</p>
                            ) : null}
                            {result.chart && result.chart.data.length > 0 ? (
                              <AskChart chart={result.chart} />
                            ) : null}
                            {result.table && result.table.row_count > 0 ? (
                              <DataTable result={result.table} />
                            ) : null}
                            <button
                              type="button"
                              className={`trace-open-button${isOpen ? " is-active" : ""}`}
                              onClick={() =>
                                setTrace(
                                  isOpen ? null : { message: index, result: resultIndex },
                                )
                              }
                              aria-expanded={isOpen}
                            >
                              <span className="trace-open-icon" aria-hidden="true" />
                              {isOpen
                                ? "Hide how this was produced"
                                : several
                                  ? `How “${blockLabel(result)}” was produced`
                                  : "How this answer was produced"}
                            </button>
                          </div>
                        );
                      })}
                    </>
                  )}
                </div>
              </div>
            ))
          )}
          {loading ? (
            <div className="chat-row chat-row-assistant">
              <span className="chat-avatar chat-avatar-assistant" aria-hidden="true">
                <SparkleIcon className="chat-avatar-icon" />
              </span>
              <div className="chat-bubble chat-bubble-assistant" aria-live="polite" aria-label="Thinking">
                <span className="typing-dots">
                  <span />
                  <span />
                  <span />
                </span>
              </div>
            </div>
          ) : null}
          <div ref={bottomRef} />
        </div>

        {limitReached ? (
          <div className="notice-banner chat-limit">
            Conversation limit of {MAX_TURNS} turns reached. Start a new conversation to continue.
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                setMessages([]);
                setThreadId(null);
                setTrace(null);
              }}
            >
              New conversation
            </button>
          </div>
        ) : null}

        {error ? <div className="notice-banner">{error}</div> : null}

        <form
          className="ask-form"
          onSubmit={(event) => {
            event.preventDefault();
            void submit(input);
          }}
        >
          <input
            type="text"
            value={input}
            maxLength={500}
            placeholder={
              limitReached ? "Conversation limit reached" : "Ask a follow-up or a new question…"
            }
            disabled={limitReached || loading}
            onChange={(event) => setInput(event.target.value)}
            aria-label="Your question"
          />
          <button
            type="submit"
            className="button-primary ask-send"
            disabled={limitReached || loading || !input.trim()}
            aria-label={loading ? "Asking…" : "Ask"}
          >
            <SendIcon />
          </button>
        </form>
      </section>

      <TraceSidebar
        open={trace !== null}
        explainability={
          trace === null
            ? null
            : messages[trace.message]?.response?.results[trace.result]?.explainability ?? null
        }
        plan={trace === null ? [] : messages[trace.message]?.response?.plan ?? []}
        onClose={() => setTrace(null)}
      />
    </main>
  );
}
