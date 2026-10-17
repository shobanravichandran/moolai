import { useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import type { AskResponse, ResultContext } from "../types";

const EXAMPLES = [
  "Ean iptables-la irundhu nftables-ku switch pannanga?",
  "Why did Kubernetes replace PodSecurityPolicy with Pod Security Admission?",
  "Why did kubelet move from dockershim to containerd?",
  "Auth module pathi yaarukku theriyum?",
  "Indha PR-ku yaar review pannanum? kubernetes/kubernetes#143065",
  "Onboard me to kube-proxy",
];

interface Turn {
  question: string;
  response?: AskResponse;
  error?: string;
}

/** Keys of the graph nodes behind an answer: what it actually links to, plus the component it was about. */
export function graphKeysFor(r: AskResponse): string[] {
  const cited = (url: string) => r.answer_md.includes(url) || r.answer_md.includes(url.replace("/pull/", "/issues/"));
  const keys = r.evidence.filter((e) => e.kind !== "mentioned" && cited(e.url)).map((e) => e.id);
  for (const arg of ["component", "topic"]) if (r.intent[arg]) keys.push(r.intent[arg]);
  return keys;
}

export default function AskPage({ onResult }: { onResult: (c: ResultContext) => void }) {
  const [question, setQuestion] = useState("");
  const [graphOnly, setGraphOnly] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setBusy(true);
    setQuestion("");
    setTurns((t) => [...t, { question: q }]);
    try {
      const response = await api.ask(q, graphOnly);
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, response } : turn)));
      onResult({ queries: response.queries, graphKeys: graphKeysFor(response), evidence: response.evidence, title: q });
    } catch (e) {
      setTurns((t) => t.map((turn, i) => (i === t.length - 1 ? { ...turn, error: (e as Error).message } : turn)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel" aria-label="Ask">
      <div className="panel-head">
        <h2>Ask the company brain</h2>
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Why did X switch to Y? Who knows Z? Who should review this PR?"
          aria-label="Question"
        />
        <label title="Answer from Cypher queries and templates only, without Claude">
          <input type="checkbox" checked={graphOnly} onChange={(e) => setGraphOnly(e.target.checked)} />
          Graph-only
        </label>
        <button type="submit" disabled={busy || !question.trim()}>
          Ask
        </button>
      </form>
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} onClick={() => ask(ex)} disabled={busy}>
            {ex}
          </button>
        ))}
      </div>
      <ul className="thread">
        {turns.map((turn, i) => (
          <li key={i} style={{ display: "contents" }}>
            <div className="question">{turn.question}</div>
            {turn.error ? (
              <div className="answer error">{turn.error}</div>
            ) : !turn.response ? (
              <div className="answer pending">Walking the graph…</div>
            ) : (
              <Answer r={turn.response} />
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Answer({ r }: { r: AskResponse }) {
  const ms = Math.round(r.queries.reduce((s, q) => s + q.ms, 0));
  return (
    <div className="answer">
      <div className="answer-meta">
        <span className="badge">{r.mode === "agent" ? "Claude + graph" : "Graph-only"}</span>
        <span className="muted">
          {r.intent.kind.replace("_", " ")} · {r.queries.length} Cypher queries · {ms} ms
          {r.usage.calls > 0 && ` · ${r.usage.calls} model call(s), $${r.usage.cost_usd.toFixed(3)}`}
        </span>
      </div>
      <div className="md" dangerouslySetInnerHTML={{ __html: renderMarkdown(r.answer_md) }} />
      {r.tool_calls && r.tool_calls.length > 0 && (
        <p className="toolcalls muted">
          Tools: {r.tool_calls.map((c) => `${c.tool}(${Object.values(c.input).join(", ")})${c.ok ? "" : " ✗"}`).join(" → ")}
        </p>
      )}
      {r.note && <p className="warn">{r.note}</p>}
      {r.ungrounded.length > 0 && (
        <p className="warn">
          Removed {r.ungrounded.length} link(s) that no graph query returned: {r.ungrounded.join(", ")}
        </p>
      )}
      {r.unknown_keps && r.unknown_keps.length > 0 && (
        <p className="warn">Mentions KEPs the graph didn't return: {r.unknown_keps.join(", ")}</p>
      )}
    </div>
  );
}
