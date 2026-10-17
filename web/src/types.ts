export interface QueryRun {
  name: string;
  ms: number;
}

export interface Usage {
  calls: number;
  cost_usd: number;
}

export interface Evidence {
  id: string;
  title: string | null;
  url: string;
  kind?: "person" | "mentioned";
}

export interface ToolCall {
  tool: string;
  input: Record<string, string>;
  ms: number;
  ok: boolean;
}

export interface AskResponse {
  mode: "agent" | "graph-only";
  intent: { kind: string; [arg: string]: string };
  answer_md: string;
  evidence: Evidence[];
  ungrounded: string[];
  unknown_keps?: string[];
  tool_calls?: ToolCall[];
  note?: string;
  queries: QueryRun[];
  usage: Usage;
}

export interface Suggestion {
  login: string;
  score: number;
  basis: "files" | "team";
  reasons: string[];
  evidence?: string[];
  components?: string[];
}

export interface ReviewersResponse {
  pr: {
    pr: { id: string; title: string; url: string; state: string; created_at: number; merged_at: number | null };
    author: string[];
    components: string[];
    teams: string[];
    reviewers: { login: string; state: string }[];
    decisions: string[];
  };
  as_of: number;
  suggestions: Suggestion[];
  queries: QueryRun[];
}

export interface Component {
  id: string;
  name: string;
  team: string | null;
  files: number;
}

export interface OnboardingResponse {
  component: { id: string; name: string };
  team: string[];
  experts: { login: string; reasons: string[]; evidence?: { id: string; title: string; url: string }[] }[];
  decisions: { id: string; title: string; url: string }[];
  brief_md: string;
  queries: QueryRun[];
}

export interface GraphNode {
  id: number;
  label: string;
  key: string;
  name: string;
  url: string | null;
}

export interface GraphData {
  nodes: GraphNode[];
  links: { source: number; target: number; type: string }[];
}

export interface SyncSource {
  source: string;
  cursor: string;
  last_run_at: number;
  stats: string;
}

export interface SyncStatus {
  running: boolean;
  started_at: number | null;
  finished_at: number | null;
  result: Record<string, unknown> | null;
  error: string | null;
  sources: SyncSource[];
}

/** What the side panel shows for the latest result on any tab. */
export interface ResultContext {
  queries: QueryRun[];
  graphKeys: string[];
  evidence: Evidence[];
  title: string;
}
