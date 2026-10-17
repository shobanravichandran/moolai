# Moolai

**Point Moolai at a public GitHub org, and it becomes that org's company brain in FalkorDB: who knows what, why
each decision was made, and who should review a change. Every answer comes with a graph path and a link.**

*Moolai* (மூளை) means "brain" in Tamil.

Built for [Graph Hacks: Context for AI Agents](https://www.wemakedevs.org/hackathons/falkordb) (WeMakeDevs ×
FalkorDB, Oct 15–18 2026). **Track: 03, Company Brain.**

> Status: in progress. KEP ingestion works (645 decisions, their SIGs and people). The build plan is in
> [PLAN.md](PLAN.md).

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

Or run the whole stack in Docker: `docker compose --profile app up -d --build`, which serves the API on
http://localhost:8020/api/health.

Host ports are 6380, 3001 and 8020, so this runs next to other FalkorDB projects that use 6379 and 3000.

## Repo layout

```
moolai/          Python package: config, FalkorDB access, schema, API
queries/         named Cypher queries; the code runs them by name (00_schema.cypher = indexes)
config/          sources.yaml (which GitHub data), components.yaml (path → component → team)
tests/           pytest; DB tests skip if FalkorDB is down
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
