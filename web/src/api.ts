import type { AskResponse, Component, GraphData, OnboardingResponse, ReviewersResponse, SyncStatus } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

const q = (params: Record<string, string>) => new URLSearchParams(params).toString();
const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  health: () => request<{ ok: boolean; falkordb: string; counts: Record<string, number> }>("/health"),
  ask: (question: string, graph_only: boolean) => request<AskResponse>("/ask", post({ question, graph_only })),
  // PR references contain '#', so they must be URL-encoded (a bare '#' would start the URL fragment).
  reviewers: (pr: string) => request<ReviewersResponse>(`/reviewers?${q({ pr })}`),
  components: () => request<Component[]>("/components"),
  onboarding: (component: string) => request<OnboardingResponse>(`/onboarding?${q({ component })}`),
  graph: (keys: string[]) => request<GraphData>("/graph", post({ keys })),
  cypher: (name: string) => request<{ name: string; cypher: string }>(`/cypher?${q({ name })}`),
  syncStatus: () => request<SyncStatus>("/sync/status"),
  syncNow: () => request<SyncStatus & { started: boolean }>("/sync", { method: "POST" }),
};
