"""Pure functions: GitHub GraphQL nodes -> graph rows. No I/O, so they are unit-tested on fixtures."""

import re
from dataclasses import dataclass, field
from datetime import datetime

from ..components import Components

BODY_LIMIT = 2000
COMMENT_LIMIT = 600

# Strongest review signal wins when one person reviewed a PR several ways.
REVIEW_RANK = {"APPROVED": 4, "LGTM": 3, "CHANGES_REQUESTED": 2, "COMMENTED": 1, "DISMISSED": 1}

_PROW = {
    "LGTM": re.compile(r"^/lgtm\b(?!\s+cancel)", re.MULTILINE | re.IGNORECASE),
    "APPROVED": re.compile(r"^/approve\b(?!\s+cancel)", re.MULTILINE | re.IGNORECASE),
}
_KEP_IN_TEXT = re.compile(
    r"(?:\bKEP[- #]?(\d{2,5})\b|kubernetes/enhancements/issues/(\d+)|kubernetes/enhancements#(\d+)"
    r"|keps/sig-[\w-]+/(\d+)-)",
    re.IGNORECASE,
)
_KK_PR = re.compile(r"kubernetes/kubernetes(?:/pull/|#)(\d+)")


# ---------- small helpers ----------


def epoch(iso: str | None) -> int | None:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None


def trim(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def actor(node: dict | None, bots: list[str]) -> tuple[str, bool] | None:
    """(lower-cased login, is_bot) for an author/actor field; None for deleted users ('ghost')."""
    if not node or not node.get("login"):
        return None
    login = node["login"].lower()
    return login, node.get("__typename") == "Bot" or is_bot_login(login, bots)


def is_bot_login(login: str, bots: list[str]) -> bool:
    """Exact names, or '*suffix' patterns matched literally.

    Not fnmatch: there '*[bot]' is a character class and would flag every login ending in b, o or t.
    """
    login = login.lower()
    return any(login.endswith(b[1:].lower()) if b.startswith("*") else login == b.lower() for b in bots)


def team_from_label(label: str) -> str | None:
    """'sig/network' -> 'sig-network', 'wg/device-management' -> 'wg-device-management'."""
    kind, _, name = label.partition("/")
    return f"{kind}-{name}" if kind in {"sig", "wg", "committee"} and name else None


def kep_numbers_in(text: str | None, known: set[int]) -> list[int]:
    """KEP numbers referenced in free text, kept only if they are real KEPs (known)."""
    out: list[int] = []
    for m in _KEP_IN_TEXT.finditer(text or ""):
        n = int(next(g for g in m.groups() if g))
        if n in known and n not in out:
            out.append(n)
    return out


def kk_pr_numbers_in(text: str | None) -> list[int]:
    out: list[int] = []
    for m in _KK_PR.finditer(text or ""):
        n = int(m.group(1))
        if n not in out:
            out.append(n)
    return out


def prow_commands(body: str | None) -> list[str]:
    """Review states expressed as Prow commands in a comment: ['LGTM'], ['APPROVED'], both, or []."""
    return [state for state, rx in _PROW.items() if rx.search(body or "")]


# ---------- PR -> rows ----------


@dataclass
class Rows:
    people: dict[str, bool] = field(default_factory=dict)  # login -> is_bot
    prs: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    files: list[dict] = field(default_factory=list)
    reviews: list[dict] = field(default_factory=list)
    fixes: list[dict] = field(default_factory=list)
    teams: list[dict] = field(default_factory=list)
    implements: list[dict] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    skipped_files: int = 0

    def person(self, who: tuple[str, bool] | None) -> str | None:
        if who:
            self.people[who[0]] = self.people.get(who[0], False) or who[1]
        return who[0] if who else None

    def people_rows(self) -> list[dict]:
        return [{"login": login, "is_bot": is_bot} for login, is_bot in sorted(self.people.items())]


def add_pr(
    rows: Rows, node: dict, repo: str, *, components: Components, bots: list[str], keps: set[int]
) -> None:
    pr_id = f"{repo}#{node['number']}"
    author = rows.person(actor(node.get("author"), bots))
    labels = [lab["name"] for lab in node["labels"]["nodes"]]
    rows.prs.append(
        {
            "id": pr_id,
            "author": author,
            "props": {
                "repo": repo,
                "number": node["number"],
                "title": node["title"],
                "body": trim(node.get("body"), BODY_LIMIT),
                "state": node["state"].lower(),
                "draft": node.get("isDraft", False),
                "created_at": epoch(node["createdAt"]),
                "updated_at": epoch(node["updatedAt"]),
                "merged_at": epoch(node.get("mergedAt")),
                "closed_at": epoch(node.get("closedAt")),
                "additions": node.get("additions"),
                "deletions": node.get("deletions"),
                "files_total": node["files"]["totalCount"],
                "labels": labels,
                "url": node["url"],
                "fetched": True,
            },
        }
    )
    for label in labels:
        team = team_from_label(label)
        if team:
            rows.teams.append({"pr": pr_id, "team": team})

    seen_files, touched = set(), set()
    for f in node["files"]["nodes"]:
        path = f["path"]
        if components.skipped(path) or path in seen_files:
            rows.skipped_files += path not in seen_files
            seen_files.add(path)
            continue
        seen_files.add(path)
        c = components.resolve(path)
        touched.add(c.id)
        rows.files.append(
            {
                "pr": pr_id,
                "file": f"{repo}:{path}",
                "repo": repo,
                "path": path,
                "dir": path.rsplit("/", 1)[0] if "/" in path else "",
                "component": c.id,
                "component_name": c.name,
                "team": c.team,
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
            }
        )
    # How many components a PR spans: dependency bumps and lint sweeps touch dozens and say little about
    # expertise in any one of them, so scoring divides by sqrt(n_components).
    rows.prs[-1]["props"]["n_components"] = max(1, len(touched))

    # Reviews: GitHub review objects plus Prow /lgtm and /approve comments; one edge per person.
    best: dict[str, dict] = {}

    def review(login: str | None, state: str, at: int | None, via: str) -> None:
        if not login or login == author or rows.people.get(login) or state not in REVIEW_RANK:
            return
        cur = best.get(login)
        if cur is None:
            best[login] = {"state": state, "at": at, "via": via}
            return
        if REVIEW_RANK[state] > REVIEW_RANK[cur["state"]]:
            cur["state"] = state
        cur["at"] = max((x for x in (cur["at"], at) if x is not None), default=None)
        if via != cur["via"]:
            cur["via"] = "both"

    for r in node["reviews"]["nodes"]:
        review(rows.person(actor(r.get("author"), bots)), r["state"], epoch(r.get("submittedAt")), "github")
    for c in node["comments"]["nodes"]:
        who = rows.person(actor(c.get("author"), bots))
        if not who or rows.people.get(who):
            continue  # bots: Prow's own messages, triage robot
        for state in prow_commands(c.get("body")):
            review(who, state, epoch(c["createdAt"]), "prow")
        rows.comments.append(_comment(c, who, pr_id))
    rows.reviews += [{"pr": pr_id, "login": login, **r} for login, r in best.items()]

    for issue in node["closingIssuesReferences"]["nodes"]:
        issue_repo = issue["repository"]["nameWithOwner"]
        rows.fixes.append(
            {
                "pr": pr_id,
                "issue": f"{issue_repo}#{issue['number']}",
                "repo": issue_repo,
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"].lower(),
                "url": issue["url"],
            }
        )

    for n in kep_numbers_in(f"{node['title']}\n{node.get('body') or ''}", keps):
        rows.implements.append(_implements(pr_id, repo, node["number"], n, "pr_body"))


# ---------- tracking issue -> rows ----------


def add_tracking_issue(rows: Rows, node: dict, repo: str, kep_number: int, *, bots: list[str]) -> list[int]:
    """Fill a KEP tracking issue; returns the k/k PR numbers it links to (implementation PRs)."""
    issue_id = f"{repo}#{node['number']}"
    author = rows.person(actor(node.get("author"), bots))
    rows.issues.append(
        {
            "id": issue_id,
            "author": author,
            "props": {
                "repo": repo,
                "number": node["number"],
                "title": node["title"],
                "body": trim(node.get("body"), BODY_LIMIT),
                "state": node["state"].lower(),
                "kind": "kep-tracking",
                "created_at": epoch(node["createdAt"]),
                "updated_at": epoch(node["updatedAt"]),
                "closed_at": epoch(node.get("closedAt")),
                "labels": [lab["name"] for lab in node["labels"]["nodes"]],
                "url": node["url"],
            },
        }
    )
    texts = [node.get("body") or ""]
    seen = set()
    for c in node["first"]["nodes"] + node["last"]["nodes"]:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        who = rows.person(actor(c.get("author"), bots))
        if who and not rows.people.get(who):  # bots (triage robot, Prow) add noise, not implementation links
            texts.append(c.get("body") or "")
            rows.comments.append(_comment(c, who, issue_id))
    linked = kk_pr_numbers_in("\n".join(texts))
    for n in linked:
        pr_id = f"kubernetes/kubernetes#{n}"
        rows.implements.append(_implements(pr_id, "kubernetes/kubernetes", n, kep_number, "tracking_issue"))
    return linked


def _comment(c: dict, author: str, on: str) -> dict:
    return {
        "id": c["id"],
        "author": author,
        "on": on,
        "body": trim(c.get("body"), COMMENT_LIMIT),
        "created_at": epoch(c["createdAt"]),
        "url": c["url"],
    }


def _implements(pr_id: str, repo: str, number: int, kep: int, via: str) -> dict:
    return {
        "pr": pr_id,
        "repo": repo,
        "number": number,
        "url": f"https://github.com/{repo}/pull/{number}",
        "decision": f"KEP-{kep}",
        "via": via,
    }
