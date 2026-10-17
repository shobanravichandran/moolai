import { useState } from "react";
import { api } from "../api";
import type { ResultContext, ReviewersResponse } from "../types";

const EXAMPLES = [
  { label: "#143065 (open): drop pkg/util/iptables", pr: "https://github.com/kubernetes/kubernetes/pull/143065" },
  { label: "#129653: nftables kube-proxy to GA", pr: "kubernetes/kubernetes#129653" },
];

const prUrl = (id: string) => {
  const [repo, n] = id.split("#");
  return `https://github.com/${repo}/pull/${n}`;
};

export default function ReviewersPage({ onResult }: { onResult: (c: ResultContext) => void }) {
  const [pr, setPr] = useState("");
  const [result, setResult] = useState<ReviewersResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function suggest(ref: string) {
    if (!ref.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api.reviewers(ref.trim());
      setResult(r);
      const keys = [
        r.pr.pr.id,
        ...r.pr.author,
        ...r.pr.components,
        ...r.suggestions.map((s) => s.login),
        ...r.suggestions.flatMap((s) => (s.evidence ?? []).slice(0, 3)),
      ];
      const evidence = [
        { id: r.pr.pr.id, title: r.pr.pr.title, url: r.pr.pr.url },
        ...r.suggestions.map((s) => ({ id: s.login, title: s.reasons[0], url: `https://github.com/${s.login}`, kind: "person" as const })),
      ];
      onResult({ queries: r.queries, graphKeys: keys, evidence, title: `Reviewers for ${r.pr.pr.id}` });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const merged = result?.pr.pr.merged_at;
  return (
    <section className="panel" aria-label="Reviewer suggestions">
      <div className="panel-head">
        <h2>Who should review this PR?</h2>
        <span
          className="badge"
          title="Backtest (docs/backtest.md): for 700 merged PRs, a suggested person actually reviewed it in 79.1% of cases (top 3), using only history from before each PR was opened. SIG-only baseline: 63.7%."
        >
          79% hit@3 on 700 past PRs
        </span>
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          suggest(pr);
        }}
      >
        <input value={pr} onChange={(e) => setPr(e.target.value)} placeholder="PR URL or kubernetes/kubernetes#123" aria-label="Pull request" />
        <button type="submit" disabled={busy || !pr.trim()}>
          Suggest
        </button>
      </form>
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex.pr} onClick={() => (setPr(ex.pr), suggest(ex.pr))} disabled={busy}>
            {ex.label}
          </button>
        ))}
      </div>
      {busy && <p className="answer pending">Reading the files and their history…</p>}
      {error && <p className="error">{error}</p>}
      {result && !busy && (
        <>
          <div className="card">
            <h3>
              <a href={result.pr.pr.url} target="_blank" rel="noopener noreferrer">
                {result.pr.pr.id}
              </a>{" "}
              {result.pr.pr.title}
            </h3>
            <p className="muted small">
              by {result.pr.author.join(", ") || "?"} · {result.pr.pr.state}
              {merged && " · suggestions use only history from before it was opened"}
            </p>
            <div className="chips">
              {result.pr.components.map((c) => (
                <span key={c} className="badge">
                  {c.replace("dir:", "")}
                </span>
              ))}
              {result.pr.teams.map((t) => (
                <span key={t} className="badge">
                  {t}
                </span>
              ))}
            </div>
            {result.pr.reviewers.length > 0 && (
              <p className="small">
                Actually reviewed by: {result.pr.reviewers.map((r) => `${r.login} (${r.state.toLowerCase()})`).join(", ")}
              </p>
            )}
          </div>
          <ol className="cards">
            {result.suggestions.map((s, i) => {
              const hit = result.pr.reviewers.some((r) => r.login === s.login);
              return (
                <li key={s.login} className="card">
                  <h3>
                    {i + 1}.{" "}
                    <a href={`https://github.com/${s.login}`} target="_blank" rel="noopener noreferrer">
                      {s.login}
                    </a>{" "}
                    {s.basis === "team" && <span className="badge">from SIG history</span>}
                    {hit && <span className="badge">✓ actually reviewed</span>}
                  </h3>
                  <ul>
                    {s.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                  {s.evidence && s.evidence.length > 0 && (
                    <p className="small muted">
                      e.g.{" "}
                      {s.evidence.slice(0, 4).map((id, j) => (
                        <span key={id}>
                          {j > 0 && ", "}
                          <a href={prUrl(id)} target="_blank" rel="noopener noreferrer">
                            #{id.split("#")[1]}
                          </a>
                        </span>
                      ))}
                    </p>
                  )}
                </li>
              );
            })}
          </ol>
        </>
      )}
    </section>
  );
}
