import { useState } from "react";
import type { ResultContext } from "../types";
import GraphView from "./GraphView";
import QueryInspector from "./QueryInspector";

type Tab = "graph" | "queries" | "sources";

// Proof for the latest result: the subgraph it came from, the Cypher that ran, and every source it can cite.
export default function SidePanel({ context }: { context: ResultContext }) {
  const [tab, setTab] = useState<Tab>("graph");
  const tabs: [Tab, string, number][] = [
    ["graph", "Graph", context.graphKeys.length],
    ["queries", "Cypher", context.queries.length],
    ["sources", "Sources", context.evidence.length],
  ];
  return (
    <section className="panel insight" aria-label="Evidence">
      <div className="panel-head tabs" role="tablist">
        {tabs.map(([key, label, count]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "active" : ""} onClick={() => setTab(key)}>
            {label}
            <span className="count">{count}</span>
          </button>
        ))}
      </div>
      {context.title && <p className="muted small">For: {context.title}</p>}
      <div className="tab-body">
        {tab === "graph" && <GraphView keys={context.graphKeys} />}
        {tab === "queries" && <QueryInspector queries={context.queries} />}
        {tab === "sources" &&
          (context.evidence.length === 0 ? (
            <p className="muted">The links an answer is allowed to cite show up here.</p>
          ) : (
            <ul className="sources">
              {context.evidence.map((e) => (
                <li key={e.url}>
                  <a href={e.url} target="_blank" rel="noopener noreferrer">
                    {e.kind === "person" ? `@${e.id}` : e.id}
                  </a>{" "}
                  {e.title && e.title !== e.id && <span className="muted">{e.title}</span>}
                </li>
              ))}
            </ul>
          ))}
      </div>
    </section>
  );
}
