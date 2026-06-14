"use client";

import { useState } from "react";
import { askStream, type AgentAnswer } from "../lib/api";

export function AskBox({ repo, team, asOf }: { repo: string; team: string; asOf: string }) {
  const [question, setQuestion] = useState("who owns the auth tokens module and what is at risk");
  const [stages, setStages] = useState<string[]>([]);
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onAsk() {
    setBusy(true);
    setError(null);
    setStages([]);
    setAnswer(null);
    try {
      await askStream({ question, repo, team, as_of: asOf }, (event) => {
        const stage = event.stage as string;
        if (stage === "plan") {
          setStages((s) => [...s, `plan: ${(event.tools as string[]).join(", ")}`]);
        } else if (stage === "tool") {
          setStages((s) => [...s, `${event.tool} (+${event.evidence})`]);
        } else if (stage === "final") {
          setAnswer(event.answer as AgentAnswer);
        }
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="panel askbox">
      <h2>Ask EngPulse</h2>
      <textarea value={question} onChange={(e) => setQuestion(e.target.value)} />
      <button className="btn" onClick={onAsk} disabled={busy || !question.trim()}>
        {busy ? "Thinking…" : "Ask"}
      </button>

      {stages.length > 0 && (
        <div className="stages">
          {stages.map((s, i) => (
            <span className="chip" key={i}>{s}</span>
          ))}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {answer && (
        <div className="answer">
          {answer.clarifying_question ? (
            <p>🤔 {answer.clarifying_question}</p>
          ) : answer.abstained ? (
            <p className="muted">Abstained — no grounded evidence for this question.</p>
          ) : (
            <>
              <p>{answer.answer}</p>
              <p className="muted">
                confidence {answer.confidence.toFixed(2)} · citations:{" "}
                {answer.citations.map((c) => (
                  <span className="citation" key={c}>{c} </span>
                ))}
              </p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
