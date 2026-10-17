# Moolai

**Point Moolai at a public GitHub org, and it becomes that org's company brain in FalkorDB: who knows what, why
each decision was made, and who should review a change. Every answer comes with a graph path and a link.**

*Moolai* (மூளை) means "brain" in Tamil.

**Live demo: https://moolai-tau.vercel.app** (API: https://moolai-api.vercel.app/api/health). Read-only, with a
shared $3/day cap on Claude answers; past the cap it answers in graph-only mode.

Built for [Graph Hacks: Context for AI Agents](https://www.wemakedevs.org/hackathons/falkordb) (WeMakeDevs ×
FalkorDB, Oct 15–18 2026). **Track: 03, Company Brain.**

> Status: in progress. Ingestion, KEP extraction, the Claude agent (live), graph-only mode and the UI work. The
> build plan is in [PLAN.md](PLAN.md).

## What it answers

| Question | How |
|---|---|
| "Why did kube-proxy switch from iptables to nftables?" | decision trace: KEP → tracking issue → implementing PRs → people, with links |
| "Who knows the auth module?" | experts ranked by recency-weighted authorship and reviews, shown next to the formal OWNERS |
| "Who should review this PR?" | files → components → recent authors and reviewers, with a measured hit rate (backtest) |
| "Onboard me to kube-proxy" | people, hot files, decisions in flight, recent PRs, good first issues |

The demo company is the Kubernetes project: KEPs, `kubernetes/kubernetes` PRs for three SIGs, reviews, OWNERS files.
It is defined in [config/sources.yaml](config/sources.yaml).

## Quick start (local)

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/) (or `python -m uv`), Python 3.12.

```bash
cp .env.example .env                 # add GITHUB_TOKEN and ANTHROPIC_API_KEY
docker compose up -d falkordb        # FalkorDB on :6380, Browser on http://localhost:3001
uv sync
uv run python -m moolai.schema       # create indexes (safe to re-run)
uv run python -m moolai.ingest.keps  # clone kubernetes/enhancements, load every KEP (~6 s; re-runs load only changes)
uv run python -m moolai.ingest.pulls # tracking issues + k/k PRs + implementation PRs (needs GITHUB_TOKEN)
uv run uvicorn moolai.api:app --reload --port 8020
```

Then the UI (Node 20+), on http://localhost:5180:

```bash
cd web && npm install && npm run dev   # proxies /api to the API on :8020
```

- **Ask:** questions in English or Tanglish, with a Graph-only toggle (no LLM, same facts).
- **Reviewers:** paste a PR to get the top 3 with reasons and example PRs.
- **Onboarding:** a brief per component, downloadable as Markdown.
- **Side panel:** the subgraph behind each answer (click a node to open it on GitHub), every Cypher query that
  ran (click to read it), and the sources the answer may cite.
- **Sync now:** an incremental sync from GitHub and the KEP repo.

Or the API directly (each response lists the named Cypher queries it ran, with timings):

```bash
curl "localhost:8020/api/experts?topic=auth%20module"
curl "localhost:8020/api/reviewers?pr=https://github.com/kubernetes/kubernetes/pull/143065"
curl "localhost:8020/api/onboarding?component=kube-proxy"
curl "localhost:8020/api/decisions/KEP-3866/trace"
curl -X POST localhost:8020/api/ask -H "content-type: application/json"   -d '{"question": "Ean iptables-la irundhu nftables-ku switch pannanga?"}'
```

`/api/ask` uses Claude (`claude-opus-5-5`) with tools over the same queries when `ANTHROPIC_API_KEY` is set, and a
graph-only keyword router otherwise (or with `"graph_only": true`). Every link in an answer must come from a tool
result; anything else is stripped and reported in `ungrounded`. To add the "what did this KEP move from / to"
edges, run `uv run python -m moolai.extract` (Batches API, ~237 KEPs, cached in `data/extract/`).

Reviewer suggestions are backtested on 700 real merged PRs: [docs/backtest.md](docs/backtest.md).

Or run the whole stack in Docker: `docker compose --profile app up -d --build`, which serves the API on
http://localhost:8020/api/health.

Host ports are 6380, 3001 and 8020, so this runs next to other FalkorDB projects that use 6379 and 3000.

## Repo layout

```
moolai/          Python package: config, FalkorDB access, schema, API
queries/         named Cypher queries; the code runs them by name (00_schema.cypher = indexes)
config/          sources.yaml (which GitHub data), components.yaml (path → component → team)
tests/           pytest; DB tests skip if FalkorDB is down
web/             React + Vite + TypeScript UI
PLAN.md          build plan, data model, timeline
```

## Data model

See [PLAN.md §4](PLAN.md#4-graph-data-model-graph-brain_kubernetes-one-graph-per-company).

## Data and licensing

Moolai reads public GitHub data from the Kubernetes project and never writes to upstream repositories. It stores
public GitHub logins and display names only, never emails. KEPs and Kubernetes source are Apache-2.0.

## AI usage disclosure

We use AI coding assistants (Claude Code) while building, and we review and understand everything that is merged.
The runtime agent uses Claude (`claude-opus-5-5`) to write answers from graph query results. Graph-only mode turns it
off.

*This section is completed before submission.*
