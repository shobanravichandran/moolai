import { useEffect, useState } from "react";
import { api } from "../api";
import { renderMarkdown } from "../markdown";
import type { Component, OnboardingResponse, ResultContext } from "../types";

export default function OnboardingPage({ onResult }: { onResult: (c: ResultContext) => void }) {
  const [components, setComponents] = useState<Component[]>([]);
  const [selected, setSelected] = useState("kube-proxy");
  const [brief, setBrief] = useState<OnboardingResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .components()
      .then(setComponents)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function load(component: string) {
    setBusy(true);
    setError(null);
    try {
      const r = await api.onboarding(component);
      setBrief(r);
      // Experts' example PRs connect each person to the component (person -> PR -> component).
      const prs = r.experts.flatMap((e) => e.evidence ?? []);
      const keys = [component, ...r.team, ...r.experts.map((e) => e.login), ...prs.map((p) => p.id), ...r.decisions.map((d) => d.id)];
      const evidence = [
        ...r.experts.map((e) => ({ id: e.login, title: e.reasons[0], url: `https://github.com/${e.login}`, kind: "person" as const })),
        ...r.decisions.map((d) => ({ id: d.id, title: d.title, url: d.url })),
        ...prs.map((p) => ({ id: p.id, title: p.title, url: p.url })),
      ];
      onResult({ queries: r.queries, graphKeys: keys, evidence, title: `Onboarding: ${r.component.name}` });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function download() {
    if (!brief) return;
    const blob = new Blob([brief.brief_md + "\n"], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `onboarding-${brief.component.id}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <section className="panel" aria-label="Onboarding">
      <div className="panel-head">
        <h2>Onboarding brief</h2>
        {brief && <button onClick={download}>Download .md</button>}
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          load(selected);
        }}
      >
        <select value={selected} onChange={(e) => setSelected(e.target.value)} aria-label="Component">
          {components.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name} ({c.team ?? "no team"}, {c.files} files)
            </option>
          ))}
        </select>
        <button type="submit" disabled={busy}>
          Build brief
        </button>
      </form>
      {busy && <p className="answer pending">Collecting people, decisions and recent work…</p>}
      {error && <p className="error">{error}</p>}
      {brief && !busy && <div className="md answer" dangerouslySetInnerHTML={{ __html: renderMarkdown(brief.brief_md) }} />}
    </section>
  );
}
