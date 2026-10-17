"""The company brain's answers, each built from named queries: who knows X, who should review this PR,
onboarding facts for a component, and a decision's trace. No LLM here: these are the graph-only answers.
"""

import re
import time

from .components import load_components
from .db import run

WINDOW_DAYS = 365
_PR_REF = re.compile(r"(?:github\.com/([\w.-]+/[\w.-]+)/pull/|([\w.-]+/[\w.-]+)#|#|^)(\d+)\s*$")
_WORD = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")


class NotFound(LookupError):
    pass


def now() -> int:
    return int(time.time())


# ---------- topics ----------


def resolve_topic(text: str) -> list[dict]:
    """'auth module', 'kube-proxy', 'SIG Network' -> components / teams, best match first.

    Aliases match whole words or phrases only, so 'dra' doesn't match 'drain'.
    """
    norm = " " + " ".join(_WORD.findall(text.lower())) + " "
    comps = load_components()
    out: list[dict] = []
    for c in comps.named:
        terms = [c.id, c.name.lower(), *comps.aliases[c.id]]
        hits = [t for t in terms if f" {t.lower()} " in norm]
        if hits:
            out.append(
                {
                    "kind": "component",
                    "id": c.id,
                    "name": c.name,
                    "team": c.team,
                    "matched": max(hits, key=len),
                }
            )
    m = re.search(r"\b(sig|wg)[\s/-]+([a-z0-9-]+)", text.lower())
    if m:
        out.append(
            {"kind": "team", "id": f"{m.group(1)}-{m.group(2)}", "name": m.group(0), "matched": m.group(0)}
        )
    out.sort(key=lambda r: -len(r["matched"]))  # longest (most specific) match first
    return out


# ---------- who knows ----------


def experts(*, component: str | None = None, team: str | None = None, topic: str | None = None, k: int = 8,
            as_of: int | None = None, window_days: int = WINDOW_DAYS, evidence: int = 3) -> dict:  # fmt: skip
    if topic and not (component or team):
        matches = resolve_topic(topic)
        if not matches:
            raise NotFound(f"no component or team matches {topic!r}")
        component = matches[0]["id"] if matches[0]["kind"] == "component" else None
        team = matches[0]["id"] if matches[0]["kind"] == "team" else None
    as_of = as_of or now()
    params = {"as_of": as_of, "window_s": window_days * 86400, "k": k}
    if component:
        rows = run("who_knows", {**params, "component": component}, read_only=True)
        for r in rows[:5]:
            r["evidence"] = run(
                "expert_evidence",
                {"login": r["login"], "component": component, "as_of": as_of, "window_s": params["window_s"],
                 "limit": evidence},
                read_only=True,
            )  # fmt: skip
    elif team:
        rows = run("who_knows_team", {**params, "team": team}, read_only=True)
    else:
        raise NotFound("give a component, a team or a topic")
    for r in rows:
        r["reasons"] = _expert_reasons(r)
    return {"component": component, "team": team, "window_days": window_days, "experts": rows}


def _expert_reasons(r: dict) -> list[str]:
    out = []
    if r["reviewed"]:
        out.append(f"reviewed {int(r['reviewed'])} merged PR(s)")
    if r["authored"]:
        out.append(f"authored {int(r['authored'])} merged PR(s)")
    if r["keps"]:
        shown = ", ".join(r["keps"][:3]) + (" …" if len(r["keps"]) > 3 else "")
        out.append(f"author/approver of {len(r['keps'])} related KEP(s): {shown}")
    return out


# ---------- reviewers ----------


def parse_pr_ref(ref: str, default_repo: str = "kubernetes/kubernetes") -> tuple[str, int]:
    m = _PR_REF.search(ref.strip())
    if not m:
        raise NotFound(f"not a PR reference: {ref!r}")
    return (m.group(1) or m.group(2) or default_repo), int(m.group(3))


def reviewers(pr: str, *, k: int = 3, as_of: int | None = None, window_days: int = WINDOW_DAYS,
              fetch_missing: bool = True) -> dict:  # fmt: skip
    """Suggest reviewers for a PR. A PR not in the graph yet (e.g. opened today) is fetched from GitHub.

    as_of defaults to the PR's creation time, so the answer for a merged PR is what we'd have said when it was
    opened (no peeking at its reviewers or anything after). When file history gives fewer than k people,
    the list is topped up with the busiest reviewers of the PR's SIGs (docs/backtest.md measures both).
    """
    repo, number = parse_pr_ref(pr)
    pr_id = f"{repo}#{number}"
    ctx = run("pr_context", {"pr_id": pr_id}, read_only=True)
    if (not ctx or not ctx[0]["pr"].get("created_at")) and fetch_missing:
        _fetch_pr(repo, number)
        ctx = run("pr_context", {"pr_id": pr_id}, read_only=True)
    if not ctx or not ctx[0]["pr"].get("created_at"):
        raise NotFound(f"PR {pr_id} is not in the graph")
    c = ctx[0]
    as_of = as_of or c["pr"]["created_at"] or now()
    window_s = window_days * 86400
    rows = run(
        "suggest_reviewers", {"pr_id": pr_id, "as_of": as_of, "window_s": window_s, "k": k}, read_only=True
    )
    suggestions = []
    for r in rows:
        prs = {p for group in r["prs"] for p in group}
        same = {p for group in r["same_file_prs"] for p in group}
        suggestions.append(
            {
                "login": r["login"],
                "score": r["score"],
                "basis": "files",
                "components": r["components"],
                "last_active": r["last_active"],
                "evidence": sorted(same or prs, reverse=True)[:5],
                "reasons": [
                    f"worked on {len(prs)} earlier PR(s) in {', '.join(r['components'])}",
                    *([f"{len(same)} of them touched the same files"] if same else []),
                ],
            }
        )
    if len(suggestions) < k and c["teams"]:
        taken = {s["login"] for s in suggestions} | set(c["author"])
        team = run(
            "baseline_team_reviewers",
            {"teams": c["teams"], "as_of": as_of, "window_s": window_s, "exclude": sorted(taken), "k": k},
            read_only=True,
        )
        for r in team[: k - len(suggestions)]:
            suggestions.append(
                {
                    "login": r["login"],
                    "score": 0.0,
                    "basis": "team",
                    "reasons": [
                        f"no file history; reviewed {r['reviews']} PR(s) for {', '.join(c['teams'])}"
                    ],
                }
            )
    context = {**c, "components": sorted(set(c["components"]))}
    return {"pr": context, "as_of": as_of, "suggestions": suggestions}


def _fetch_pr(repo: str, number: int) -> None:
    from .ingest import mapping, pulls
    from .ingest.github import GitHub

    cfg = pulls.sources()
    keps = {r["number"] for r in run("decision_numbers", read_only=True)}
    rows = mapping.Rows()
    for _, node in pulls.fetch_by_number(GitHub(), repo, "pullRequest", [number], batch=1):
        mapping.add_pr(rows, node, repo, components=load_components(), bots=cfg["bots"], keps=keps)
    if rows.prs:
        pulls.load_rows(rows)


# ---------- onboarding ----------


def onboarding(component: str, *, as_of: int | None = None, window_days: int = WINDOW_DAYS) -> dict:
    as_of = as_of or now()
    overview = run("component_overview", {"component": component}, read_only=True)
    if not overview:
        raise NotFound(f"unknown component {component!r}")
    w = {"as_of": as_of, "window_s": window_days * 86400}
    return {
        **overview[0],
        "experts": experts(component=component, k=5, as_of=as_of, window_days=window_days, evidence=2)[
            "experts"
        ],
        "hot_files": run("onboarding_hot_files", {**w, "component": component, "limit": 10}, read_only=True),
        "decisions": run("onboarding_decisions", {"component": component, "limit": 8}, read_only=True),
        "recent_prs": run(
            "onboarding_recent_prs", {"component": component, "as_of": as_of, "limit": 8}, read_only=True
        ),
        "open_prs": run("onboarding_open_prs", {"component": component, "limit": 8}, read_only=True),
    }


# ---------- decisions ----------


def decision(decision_id: str) -> dict:
    did = decision_id.strip()
    did = "KEP-" + did[4:] if did.lower().startswith("kep-") else f"KEP-{did}" if did.isdigit() else did
    rows = run("decision_trace", {"id": did}, read_only=True)
    if not rows:
        raise NotFound(f"unknown decision {decision_id!r}")
    return rows[0]
