import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import AskPage from "./components/AskPage";
import OnboardingPage from "./components/OnboardingPage";
import ReviewersPage from "./components/ReviewersPage";
import SidePanel from "./components/SidePanel";
import SyncBadge from "./components/SyncBadge";
import type { ResultContext } from "./types";

type Page = "ask" | "reviewers" | "onboarding";

const PAGES: [Page, string][] = [
  ["ask", "Ask"],
  ["reviewers", "Reviewers"],
  ["onboarding", "Onboarding"],
];

const EMPTY: ResultContext = { queries: [], graphKeys: [], evidence: [], title: "" };

export default function App() {
  const [page, setPage] = useState<Page>("ask");
  const [context, setContext] = useState<ResultContext>(EMPTY);
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadCounts = useCallback(() => {
    api
      .health()
      .then((h) => {
        setCounts(h.counts ?? null);
        setNotice(h.falkordb === "ok" ? null : `FalkorDB: ${h.falkordb}`);
      })
      .catch((e: Error) => setNotice(`API unreachable: ${e.message}`));
  }, []);
  useEffect(loadCounts, [loadCounts]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>Moolai</h1>
          <span className="muted small" lang="ta">
            மூளை · company brain for Kubernetes
          </span>
        </div>
        <nav className="nav" aria-label="Pages">
          {PAGES.map(([key, label]) => (
            <button key={key} className={page === key ? "active" : ""} aria-current={page === key} onClick={() => setPage(key)}>
              {label}
            </button>
          ))}
        </nav>
        {counts && (
          <span className="muted small stat" title="Nodes in the FalkorDB graph">
            {counts.Decision ?? 0} KEPs · {counts.PR ?? 0} PRs · {counts.Person ?? 0} people
          </span>
        )}
        <SyncBadge onSynced={loadCounts} />
      </header>
      {notice && <p className="notice">{notice}</p>}
      <main className="columns">
        {/* Pages stay mounted so switching tabs keeps their state. */}
        <div hidden={page !== "ask"} style={{ display: page === "ask" ? "contents" : "none" }}>
          <AskPage onResult={setContext} />
        </div>
        <div hidden={page !== "reviewers"} style={{ display: page === "reviewers" ? "contents" : "none" }}>
          <ReviewersPage onResult={setContext} />
        </div>
        <div hidden={page !== "onboarding"} style={{ display: page === "onboarding" ? "contents" : "none" }}>
          <OnboardingPage onResult={setContext} />
        </div>
        <SidePanel context={context} />
      </main>
    </div>
  );
}
