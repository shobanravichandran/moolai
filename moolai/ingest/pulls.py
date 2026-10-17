"""GitHub -> graph: KEP tracking issues, kubernetes/kubernetes PRs, and KEP-linked implementation PRs.

Usage: python -m moolai.ingest.pulls [--only tracking|prs|backfill] [--full] [--offline] [--max-backfill N]

1. tracking: every KEP's tracking issue in kubernetes/enhancements (issue number == KEP number), with
   comments. k/k PR links in those threads become (PR)-[:IMPLEMENTS {via:'tracking_issue'}]->(Decision).
2. prs: k/k PRs labelled with the configured SIGs, merged or open since `since` (config/sources.yaml), with
   files, reviews, Prow /lgtm + /approve, closing issues, labels and KEP references in the body.
3. backfill: implementation PRs linked from tracking issues of KEPs owned by `extract_teams`, any age.

Watermarks (max updatedAt seen) live in (:SyncState); later runs only fetch what changed since then.
"""

import argparse
import gzip
import json
import logging
from datetime import UTC, date, datetime, timedelta

import yaml

from ..components import load_components
from ..config import CONFIG_DIR
from ..db import run
from ..schema import ensure_schema
from . import mapping
from .github import CACHE_DIR, GitHub

log = logging.getLogger("moolai.pulls")

KK = "kubernetes/kubernetes"
ENH = "kubernetes/enhancements"
SEARCH_CAP = 1000  # GitHub search returns at most 1,000 results per query
PAGE = 20

PR_FIELDS = """
fragment PR on PullRequest {
  number title body url state isDraft createdAt updatedAt mergedAt closedAt additions deletions
  author { login __typename }
  labels(first: 30) { nodes { name } }
  files(first: 100) { totalCount nodes { path additions deletions } }
  reviews(first: 50) { nodes { author { login __typename } state submittedAt } }
  comments(first: 60) { nodes { id author { login __typename } body createdAt url } }
  closingIssuesReferences(first: 10) { nodes { number title url state repository { nameWithOwner } } }
}
"""

SEARCH = (
    PR_FIELDS
    + """
query($q: String!, $first: Int!, $after: String) {
  rateLimit { cost remaining resetAt }
  search(query: $q, type: ISSUE, first: $first, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ...PR }
  }
}
"""
)

COUNT = """
query($q: String!) {
  rateLimit { cost remaining resetAt }
  search(query: $q, type: ISSUE, first: 0) { issueCount }
}
"""

ISSUE_FIELDS = """
  number title body url state createdAt updatedAt closedAt
  author { login __typename }
  labels(first: 20) { nodes { name } }
  first: comments(first: 100) { nodes { id author { login __typename } body createdAt url } }
  last: comments(last: 100) { nodes { id author { login __typename } body createdAt url } }
"""

ISSUES_UPDATED = """
query($after: String, $since: DateTime!) {
  rateLimit { cost remaining resetAt }
  repository(owner: "kubernetes", name: "enhancements") {
    issues(first: 100, after: $after, filterBy: {since: $since},
           orderBy: {field: UPDATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number updatedAt }
    }
  }
}
"""


# ---------- config ----------


def sources() -> dict:
    return yaml.safe_load((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"))


def pr_labels(cfg: dict) -> list[str]:
    return next(s["labels"] for s in cfg["sources"] if s["kind"] == "pull_requests")


# ---------- GitHub reads ----------


def search_prs(gh: GitHub, base: str, field: str, start: date, end: date):
    """Yield PR nodes for `base field:start..end`, halving the date window while it exceeds the search cap."""
    q = f"{base} {field}:{start.isoformat()}..{end.isoformat()}"
    count = gh.query(COUNT, {"q": q})["search"]["issueCount"]
    if count > SEARCH_CAP and end > start:
        mid = start + (end - start) // 2
        yield from search_prs(gh, base, field, start, mid)
        yield from search_prs(gh, base, field, mid + timedelta(days=1), end)
        return
    if count > SEARCH_CAP:
        log.warning("%s has %d results on a single day; only the first %d are fetched", q, count, SEARCH_CAP)
    log.info("search %s: %d PRs", q, count)
    after = None
    while True:
        page = gh.query(SEARCH, {"q": q, "first": PAGE, "after": after})["search"]
        yield from (n for n in page["nodes"] if n)  # empty nodes are non-PR hits / deleted items
        if not page["pageInfo"]["hasNextPage"]:
            return
        after = page["pageInfo"]["endCursor"]


def fetch_by_number(gh: GitHub, repo: str, kind: str, numbers: list[int], batch: int):
    """Yield (number, node) for issues or PRs fetched by number, `batch` per query using aliases."""
    owner, name = repo.split("/")
    body = ISSUE_FIELDS if kind == "issue" else "...PR"
    head = PR_FIELDS if kind == "pullRequest" else ""
    for i in range(0, len(numbers), batch):
        chunk = numbers[i : i + batch]
        fields = "\n".join(f"n{n}: {kind}(number: {n}) {{ {body} }}" for n in chunk)
        q = f'{head}query {{ rateLimit {{ cost remaining resetAt }} repository(owner: "{owner}", name: "{name}") {{ {fields} }} }}'  # noqa: E501
        repo_data = gh.query(q)["repository"] or {}
        for n in chunk:
            node = repo_data.get(f"n{n}")
            if node:
                yield n, node


def issues_updated_since(gh: GitHub, since: str) -> list[int]:
    numbers, after = [], None
    while True:
        page = gh.query(ISSUES_UPDATED, {"after": after, "since": since})["repository"]["issues"]
        numbers += [n["number"] for n in page["nodes"]]
        if not page["pageInfo"]["hasNextPage"]:
            return numbers
        after = page["pageInfo"]["endCursor"]


# ---------- graph writes ----------


def load_rows(rows: mapping.Rows) -> dict:
    """Write one batch. PR edges (files, reviews, fixes, team tags) are replaced, so re-syncs show edits."""
    ensure_schema()
    run("upsert_people", {"rows": rows.people_rows()})
    pr_ids = list(dict.fromkeys(r["id"] for r in rows.prs))
    for chunk in _chunks(pr_ids, 100):
        run("unlink_prs", {"ids": chunk})
    steps = [
        ("upsert_prs", rows.prs, 100),
        ("upsert_issues", rows.issues, 100),
        ("link_pr_files", _dedupe(rows.files, "pr", "file"), 500),
        ("link_pr_reviews", rows.reviews, 500),
        ("link_pr_fixes", rows.fixes, 500),
        ("link_pr_teams", _team_rows(rows.teams), 500),
        ("link_implements", _dedupe(rows.implements, "pr", "decision"), 500),
        ("upsert_comments", rows.comments, 500),
    ]
    for name, data, size in steps:
        for chunk in _chunks(data, size):
            run(name, {"rows": chunk})
    return {
        "prs": len(pr_ids),
        "issues": len(rows.issues),
        "files": len(rows.files),
        "skipped_files": rows.skipped_files,
        "reviews": len(rows.reviews),
        "fixes": len(rows.fixes),
        "implements": len(rows.implements),
        "comments": len(rows.comments),
        "people": len(rows.people),
    }


def ensure_components() -> None:
    comps = load_components()
    run(
        "upsert_components",
        {
            "rows": [
                {"id": c.id, "name": c.name, "team": c.team, "aliases": comps.aliases[c.id]}
                for c in comps.named
            ]
        },
    )


# ---------- steps ----------


def sync_tracking(gh: GitHub, cfg: dict, full: bool) -> tuple[dict, dict[int, list[int]]]:
    """Tracking issues for every KEP. Returns stats and {kep number: linked k/k PR numbers}."""
    source = f"github:{ENH}:tracking"
    keps = {r["number"] for r in run("decision_numbers", read_only=True)}
    cursor = _cursor(source)
    started = _now_iso()
    if cursor and not full:
        numbers = sorted(n for n in issues_updated_since(gh, cursor) if n in keps)
    else:
        numbers = sorted(keps)
    rows, links = mapping.Rows(), {}
    for n, node in fetch_by_number(gh, ENH, "issue", numbers, batch=10):
        links[n] = mapping.add_tracking_issue(rows, node, ENH, n, bots=cfg["bots"])
    stats = load_rows(rows)
    _set_cursor(source, started, stats)
    return stats, links


def sync_prs(gh: GitHub, cfg: dict, full: bool) -> dict:
    source = f"github:{KK}:prs"
    keps = {r["number"] for r in run("decision_numbers", read_only=True)}
    base = f"repo:{KK} is:pr label:{','.join(pr_labels(cfg))}"  # comma = OR in GitHub search
    cursor = _cursor(source)
    started = _now_iso()
    today = datetime.now(UTC).date()
    if cursor and not full:
        windows = [(f"{base}", "updated", date.fromisoformat(cursor[:10]), today)]
    else:
        since = date.fromisoformat(str(cfg["since"]))
        windows = [
            (f"{base} is:merged", "merged", since, today),
            (f"{base} is:open", "created", since, today),
        ]
        # Open PRs created before `since` but still active are picked up by later incremental runs.
    totals: dict = {}
    for q, field, start, end in windows:
        batch = mapping.Rows()
        for node in search_prs(gh, q, field, start, end):
            mapping.add_pr(batch, node, KK, components=load_components(), bots=cfg["bots"], keps=keps)
            if len(batch.prs) >= 200:
                _add(totals, load_rows(batch))
                batch = mapping.Rows()
        _add(totals, load_rows(batch))
    _set_cursor(source, started, totals)
    return totals


def backfill(gh: GitHub, cfg: dict, links: dict[int, list[int]] | None, limit: int) -> dict:
    """Fetch implementation PRs that KEP tracking issues link to, for KEPs owned by `extract_teams`."""
    keps = {r["number"] for r in run("decision_numbers", read_only=True)}
    wanted = {
        r["number"]
        for r in run("decision_numbers_for_teams", {"teams": cfg["extract_teams"]}, read_only=True)
    }
    if links is None:  # --only backfill: use the IMPLEMENTS stubs already in the graph
        stubs = run("implementation_stubs", {"teams": cfg["extract_teams"]}, read_only=True)
        numbers = sorted({r["number"] for r in stubs})
    else:
        numbers = sorted({n for kep, prs in links.items() if kep in wanted for n in prs})
    have = {r["number"] for r in run("fetched_pr_numbers", {"repo": KK}, read_only=True)}
    todo = [n for n in numbers if n not in have][:limit]
    log.info(
        "backfill: %d linked PRs, %d already fetched, fetching %d",
        len(numbers),
        len(have & set(numbers)),
        len(todo),
    )
    totals: dict = {}
    batch = mapping.Rows()
    found = set()
    for n, node in fetch_by_number(gh, KK, "pullRequest", todo, batch=10):
        found.add(n)
        mapping.add_pr(batch, node, KK, components=load_components(), bots=cfg["bots"], keps=keps)
        if len(batch.prs) >= 200:
            _add(totals, load_rows(batch))
            batch = mapping.Rows()
    _add(totals, load_rows(batch))
    # Links like kubernetes/kubernetes#N can point at issues; GitHub then returns no PR. Drop those stubs.
    missing = [f"{KK}#{n}" for n in todo if n not in found]
    run("delete_pr_stubs", {"ids": missing})
    totals["not_prs_removed"] = len(missing)
    return totals


def replay_cache(cfg: dict) -> dict:
    """Rebuild from data/raw/github without a token: every cached response, newest version of each item wins.

    Queries differ between runs (watermarks, today's date), so offline mode replays the whole cache rather
    than looking up exact queries.
    """
    prs: dict[int, dict] = {}
    issues: dict[int, dict] = {}
    for path in sorted(CACHE_DIR.glob("*.json.gz")):
        data = json.loads(gzip.decompress(path.read_bytes())).get("data") or {}
        nodes = (data.get("search") or {}).get("nodes") or []
        repo_data = data.get("repository") or {}
        nodes += [v for k, v in repo_data.items() if k.startswith("n") and k[1:].isdigit() and v]
        for node in nodes:
            if not node or "number" not in node or "labels" not in node:
                continue
            bucket = prs if "mergedAt" in node else issues
            old = bucket.get(node["number"])
            if old is None or node["updatedAt"] >= old["updatedAt"]:
                bucket[node["number"]] = node
    keps = {r["number"] for r in run("decision_numbers", read_only=True)}
    rows = mapping.Rows()
    for n, node in sorted(issues.items()):
        if n in keps:
            mapping.add_tracking_issue(rows, node, ENH, n, bots=cfg["bots"])
    for node in prs.values():
        mapping.add_pr(rows, node, KK, components=load_components(), bots=cfg["bots"], keps=keps)
    return load_rows(rows)


def sync(
    only: str | None = None, full: bool = False, offline: bool = False, max_backfill: int = 2000
) -> dict:
    cfg = sources()
    ensure_schema()
    ensure_components()
    if offline:
        return {"offline_replay": replay_cache(cfg)}
    gh = GitHub()
    out: dict = {}
    links = None
    if only in (None, "tracking"):
        out["tracking"], links = sync_tracking(gh, cfg, full)
    if only in (None, "prs"):
        out["prs"] = sync_prs(gh, cfg, full)
    if only in (None, "backfill"):
        out["backfill"] = backfill(gh, cfg, links, max_backfill)
    out["github"] = {"calls": gh.calls, "cost": gh.cost}
    return out


# ---------- helpers ----------


def _cursor(source: str) -> str | None:
    state = run("sync_state_get", {"source": source}, read_only=True)
    return state[0]["cursor"] if state else None


def _set_cursor(source: str, cursor: str, stats: dict) -> None:
    run("sync_state_set", {"source": source, "cursor": cursor, "stats": json.dumps(stats, sort_keys=True)})


def _now_iso() -> str:
    # Taken before fetching, so anything updated during the run is picked up again next time.
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _team_rows(rows: list[dict]) -> list[dict]:
    out = _dedupe(rows, "pr", "team")
    for r in out:
        kind, _, name = r["team"].partition("-")
        r["kind"], r["name"] = kind, f"{kind.upper()} {name.replace('-', ' ').title()}"
    return out


def _dedupe(rows: list[dict], *keys: str) -> list[dict]:
    seen, out = set(), []
    for r in rows:
        k = tuple(r[key] for key in keys)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def _add(totals: dict, stats: dict) -> None:
    for k, v in stats.items():
        totals[k] = totals.get(k, 0) + v


def _chunks(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--only", choices=["tracking", "prs", "backfill"])
    p.add_argument("--full", action="store_true", help="ignore watermarks and re-fetch everything in scope")
    p.add_argument(
        "--offline", action="store_true", help="rebuild from data/raw/github only (no token needed)"
    )
    p.add_argument("--max-backfill", type=int, default=2000)
    a = p.parse_args()
    print(json.dumps(sync(a.only, a.full, a.offline, a.max_backfill), indent=2))
