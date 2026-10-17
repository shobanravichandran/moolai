import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { SyncStatus } from "../types";

function ago(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 2 * 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} days ago`;
}

function summary(result: Record<string, unknown> | null): string {
  if (!result) return "";
  const n = (path: [string, string]) => Number((result[path[0]] as Record<string, number> | undefined)?.[path[1]] ?? 0);
  const prs = n(["prs", "prs"]) + n(["backfill", "prs"]);
  const reviews = n(["prs", "reviews"]) + n(["backfill", "reviews"]);
  return `${prs} PR(s), ${reviews} review(s) refreshed`;
}

// "Knowledge stays current": when each source last synced, and a button that runs an incremental sync.
export default function SyncBadge({ onSynced }: { onSynced: () => void }) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api
      .syncStatus()
      .then((s) => {
        setStatus((prev) => {
          if (prev?.running && !s.running && !s.error) onSynced();
          return s;
        });
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, [onSynced]);

  useEffect(refresh, [refresh]);
  useEffect(() => {
    if (!status?.running) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [status?.running, refresh]);

  async function syncNow() {
    try {
      setStatus(await api.syncNow());
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const last = Math.max(0, ...(status?.sources ?? []).map((s) => s.last_run_at ?? 0));
  return (
    <div className="sync" aria-live="polite">
      {error && <span className="error">{error}</span>}
      {status?.running ? (
        <span className="cost">Syncing from GitHub…</span>
      ) : (
        <span className="cost" title={(status?.sources ?? []).map((s) => `${s.source}: ${s.cursor}`).join("\n")}>
          {last ? `Synced ${ago(last)}` : "Never synced"}
          {status?.result && <span className="muted"> · {summary(status.result)}</span>}
          {status?.error && <span className="error"> · last sync failed</span>}
        </span>
      )}
      <button onClick={syncNow} disabled={status?.running}>
        Sync now
      </button>
    </div>
  );
}
