"use client";

import { useEffect, useRef, useState } from "react";

import AskChart from "../components/AskChart";
import DataTable from "../components/DataTable";
import EmptyState from "../components/EmptyState";
import ExplainabilityPanel from "../components/ExplainabilityPanel";
import { askQuestion } from "@/lib/api";
import { ASK_RESPONSE_FIXTURE } from "@/lib/fixtures";
import { ApiError, type AskResponse, type HistoryTurn } from "@/lib/types";

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

export default function AskPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      const response = await askQuestion(trimmed, turns.slice(-MAX_TURNS));
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
                <div className={`chat-bubble chat-bubble-${message.role}${message.isError ? " chat-bubble-error" : ""}`}>
                  {message.role === "user" ? (
                    <p className="chat-text">{message.text}</p>
                  ) : message.isError ? (
                    <p className="chat-text">{message.text}</p>
                  ) : message.response && message.response.unsupported ? (
                    <>
                      <p className="chat-text">That question is outside what the data can answer.</p>
                      <p className="chat-text muted">{message.response.unsupported_reason}</p>
                    </>
                  ) : (
                    <>
                      <p className="chat-text">{message.text}</p>
                      {message.response?.chart && message.response.chart.data.length > 0 ? (
                        <AskChart chart={message.response.chart} />
                      ) : null}
                      {message.response?.table && message.response.table.row_count > 0 ? (
                        <DataTable result={message.response.table} />
                      ) : null}
                      {message.response?.explainability ? (
                        <ExplainabilityPanel explainability={message.response.explainability} />
                      ) : null}
                    </>
                  )}
                </div>
              </div>
            ))
          )}
          {loading ? <p className="loading chat-loading">Thinking…</p> : null}
          <div ref={bottomRef} />
        </div>

        {limitReached ? (
          <div className="notice-banner chat-limit">
            Conversation limit of {MAX_TURNS} turns reached. Start a new conversation to continue.
            <button type="button" className="button-secondary" onClick={() => setMessages([])}>
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
          <button type="submit" className="button-primary" disabled={limitReached || loading || !input.trim()}>
            {loading ? "Asking…" : "Ask"}
          </button>
        </form>
      </section>
    </main>
  );
}
