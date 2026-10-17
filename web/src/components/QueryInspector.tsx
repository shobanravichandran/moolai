import { useState } from "react";
import { api } from "../api";
import type { QueryRun } from "../types";

// Every named Cypher query the last request ran, with timings. Click one to read its source.
export default function QueryInspector({ queries }: { queries: QueryRun[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [source, setSource] = useState<Record<string, string>>({});

  async function toggle(name: string) {
    if (open === name) return setOpen(null);
    setOpen(name);
    if (!source[name]) {
      const res = await api.cypher(name).catch(() => ({ cypher: "// could not load" }));
      setSource((s) => ({ ...s, [name]: res.cypher }));
    }
  }

  if (queries.length === 0) {
    return <p className="muted">Every Cypher query behind an answer shows up here, with its source.</p>;
  }
  const total = queries.reduce((sum, q) => sum + q.ms, 0);
  return (
    <>
      <p className="muted">
        {queries.length} queries · {Math.round(total)} ms on FalkorDB
      </p>
      <ol className="queries">
        {queries.map((q, i) => (
          <li key={i}>
            <button className="link" onClick={() => toggle(q.name)} aria-expanded={open === q.name}>
              <code>{q.name}</code>
            </button>{" "}
            <span className="muted">{q.ms} ms</span>
            {open === q.name && <pre className="cypher">{source[q.name] ?? "loading…"}</pre>}
          </li>
        ))}
      </ol>
    </>
  );
}
