"""Graph-only answers: a keyword router picks an intent, named queries answer it, a template writes it up.

This is what /api/ask returns with graph_only=true (or when no Claude key is configured). The agent (agent.py)
uses the same brain functions as tools, so turning the LLM off changes the wording, not the facts.
Also home to the evidence collector and the grounding check that both modes share.
"""

import json
import re
import time
from dataclasses import dataclass, field

from . import brain
from .db import run

# ---------- intent detection ----------

_PR_URL = re.compile(r"github\.com/[\w.-]+/[\w.-]+/pull/\d+")
_PR_SHORT = re.compile(r"(?:[\w.-]+/[\w.-]+#\d+|\bPR\s*#?\d{3,}\b|#\d{4,}\b)", re.IGNORECASE)
_KEP = re.compile(r"\bKEP[- ]?(\d{1,5})\b", re.IGNORECASE)
_WHY = re.compile(r"\b(why|ean|yen|yean|en|reason|enna\s+karanam)\b|ஏன்", re.IGNORECASE)
_SWITCH_PATTERNS = [
    # English: "from X to Y", "replace X with Y", "X -> Y"
    re.compile(r"\bfrom\s+(?P<x>.+?)\s+(?:to|towards|in favou?r of)\s+(?P<y>.+?)(?:[?.!]|$)", re.IGNORECASE),
    re.compile(r"\breplace[ds]?\s+(?P<x>.+?)\s+with\s+(?P<y>.+?)(?:[?.!]|$)", re.IGNORECASE),
    re.compile(r"(?P<x>[\w./ -]+?)\s*(?:->|→|=>)\s*(?P<y>[\w./ -]+)", re.IGNORECASE),
    # Tanglish: "X-la irundhu Y-ku", "X le irundhu Y kku"
    re.compile(
        r"(?P<x>[\w./ ]+?)[- ]?(?:la|le|il|lla)\s+irun?dh?u\s+(?P<y>[\w./ ]+?)[- ]?(?:ku|kku|kke|kki)\b",
        re.IGNORECASE,
    ),
]
_EXPERTS = re.compile(
    r"\b(who\s+(?:knows|owns|maintains|works on|to ask)|experts?|maintainers?|owners?|yaarukku|yaaru|yaar)\b",
    re.IGNORECASE,
)
_REVIEW = re.compile(r"\breview", re.IGNORECASE)
_ONBOARD = re.compile(r"\b(onboard\w*|new to|getting started|get started|intro\w*|brief)\b", re.IGNORECASE)
_STOP = {
    "the",
    "a",
    "an",
    "kube",
    "k8s",
    "kubernetes",
    "mode",
    "backend",
    "module",
    "kube-proxy's",
    "to",
    "use",
    # question words the switch patterns can sweep into X (English and Tanglish)
    "why",
    "ean",
    "yen",
    "yean",
    "en",
    "did",
    "do",
    "does",
    "we",
    "they",
    "you",
    "switch",
    "move",
    "moved",
}


@dataclass
class Intent:
    kind: str  # why_switch | decision | reviewers | experts | onboarding | search
    args: dict = field(default_factory=dict)


def _clean_tech(text: str) -> str:
    words = [w for w in re.findall(r"[\w./+-]+", text.lower()) if w not in _STOP]
    return " ".join(words[-3:])  # the technology is usually the last words before "to"/"ku"


def classify(question: str) -> Intent:
    q = question.strip()
    pr = _PR_URL.search(q) or _PR_SHORT.search(q)
    if pr and (_REVIEW.search(q) or not _WHY.search(q)):
        return Intent("reviewers", {"pr": pr.group(0).replace("PR", "").replace("pr", "").strip()})
    if _WHY.search(q):
        for rx in _SWITCH_PATTERNS:
            m = rx.search(q)
            if m:
                x, y = _clean_tech(m.group("x")), _clean_tech(m.group("y"))
                if x and y:
                    return Intent("why_switch", {"x": x, "y": y})
    kep = _KEP.search(q)
    if kep:
        return Intent("decision", {"id": f"KEP-{int(kep.group(1))}"})
    if _ONBOARD.search(q):
        topic = brain.resolve_topic(q)
        if topic and topic[0]["kind"] == "component":
            return Intent("onboarding", {"component": topic[0]["id"]})
    if _EXPERTS.search(q) or _REVIEW.search(q):
        topic = brain.resolve_topic(q)
        if topic:
            return Intent("experts", {"topic": topic[0]["id"] if topic[0]["kind"] == "component" else q})
    return Intent("search", {"text": q})


# ---------- evidence + grounding ----------


def collect_evidence(value, out: dict[str, dict]) -> dict[str, dict]:
    """Walk a tool/query result and index everything citable by URL: decisions, PRs, issues, people."""
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.startswith("http"):
            out.setdefault(url, {"id": value.get("id") or url, "title": value.get("title"), "url": url})
        logins = [value["login"]] if isinstance(value.get("login"), str) else []
        for key in ("authors", "reviewers", "author"):  # plain login lists (decision_trace, pr_context)
            if isinstance(value.get(key), list):
                logins += [x for x in value[key] if isinstance(x, str)]
        for login in logins:
            u = f"https://github.com/{login}"
            out.setdefault(u, {"id": login, "title": login, "url": u, "kind": "person"})
        for v in value.values():
            collect_evidence(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            collect_evidence(v, out)
    elif isinstance(value, str):
        if re.fullmatch(r"[\w.-]+/[\w.-]+#\d+", value):
            repo, n = value.split("#")
            u = f"https://github.com/{repo}/pull/{n}"
            out.setdefault(u, {"id": value, "title": None, "url": u})
        for u in _BARE_URL.findall(value):  # links quoted inside source text (KEP summaries, PR bodies)
            u = u.rstrip(".,;:")
            out.setdefault(u, {"id": u, "title": None, "url": u, "kind": "mentioned"})
    return out


_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"(?<![(\[])https?://[^\s)>\]]+")


def ground(answer: str, evidence: dict[str, dict]) -> tuple[str, list[str]]:
    """Strip links whose URL is not in the evidence (keep the link text). Returns (answer, removed URLs)."""
    removed: list[str] = []

    def keep_link(m: re.Match) -> str:
        if _allowed(m.group(2), evidence):
            return m.group(0)
        removed.append(m.group(2))
        return m.group(1)

    answer = _MD_LINK.sub(keep_link, answer)

    def keep_bare(m: re.Match) -> str:
        url = m.group(0).rstrip(".,;:")  # sentence punctuation isn't part of the URL
        tail = m.group(0)[len(url) :]
        if _allowed(url, evidence):
            return m.group(0)
        removed.append(url)
        return "[link removed]" + tail

    return _BARE_URL.sub(keep_bare, answer), removed


def _allowed(url: str, evidence: dict[str, dict]) -> bool:
    url = url.rstrip(".,;:")
    # GitHub serves the same PR at /pull/N and /issues/N; accept either form of a known item.
    alt = url.replace("/issues/", "/pull/") if "/issues/" in url else url.replace("/pull/", "/issues/")
    return url in evidence or alt in evidence


def unknown_keps(answer: str, raw) -> list[str]:
    """KEP ids the answer mentions that appear nowhere in the tool results (reported, not removed).

    Scans the raw results, not just citable evidence: KEP ids also come back as plain strings (e.g. who_knows'
    `keps` lists).
    """
    seen = set(re.findall(r"KEP-\d+", json.dumps(raw, default=str)))
    return sorted({f"KEP-{n}" for n in re.findall(r"KEP-(\d+)", answer)} - seen)


# ---------- graph-only answers ----------


def _date(ts) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "?"


def _pr_link(pr_id: str, url: str | None = None) -> str:
    repo, n = pr_id.split("#")
    short = f"#{n}" if repo == "kubernetes/kubernetes" else pr_id
    return f"[{short}]({url or f'https://github.com/{repo}/pull/{n}'})"


def _person(login: str) -> str:
    return f"[{login}](https://github.com/{login})"


def search_query(text: str, *, all_terms: bool) -> str:
    """Sanitized RediSearch query: plain words only, AND-ed (all_terms) or OR-ed."""
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1 and w not in _STOP]
    return (" " if all_terms else "|").join(dict.fromkeys(words)) or "kubernetes"


def _unique(rows: list[dict]) -> list[dict]:
    """One row per decision (a KEP that moved to two targets matches twice)."""
    return list({r["id"]: r for r in reversed(rows)}.values())[::-1]


def find_switch(x: str, y: str, k: int = 5) -> dict:
    """Decisions that moved from x to y, most specific evidence first:
    extracted MOVES_FROM x and MOVES_TO y; then extracted MOVES_FROM x alone (the KEP may name the target
    differently, e.g. "CRI runtimes" for containerd); then full-text on both terms; then on either.
    """
    rows = _unique(run("decision_switch", {"x": x, "y": y, "k": k}, read_only=True))
    if rows:
        return {"basis": "extracted MOVES_FROM / MOVES_TO edges", "decisions": rows}
    rows = _unique(run("decision_switch", {"x": x, "y": "", "k": k}, read_only=True))
    if rows:
        targets = ", ".join(sorted({r["moves_to"] for r in rows}))
        return {
            "basis": f"extracted MOVES_FROM '{x}' (the KEPs name the target as: {targets})",
            "decisions": rows,
        }
    rows = run("decision_search", {"q": search_query(f"{x} {y}", all_terms=True), "k": k}, read_only=True)
    if rows:
        return {"basis": f"full-text match on both '{x}' and '{y}'", "decisions": rows}
    rows = run("decision_search", {"q": search_query(f"{x} {y}", all_terms=False), "k": k}, read_only=True)
    return {"basis": f"full-text match on '{x}' or '{y}'", "decisions": rows}


def render_trace(t: dict, *, implemented: int = 6) -> list[str]:
    d = t["decision"]
    lines = [
        f"**[{d['id']}]({d['url']}): {d['title']}**",
        "",
        f"Status: {d['status']}" + (f", {d['stage']}" if d.get("stage") else "")
        + (f" (latest milestone {d['latest_milestone']})" if d.get("latest_milestone") else "")
        + (f" · owned by {', '.join(t['team'])}" if t["team"] else ""),
        "",
    ]  # fmt: skip
    # Undo README hard wraps, but keep list items and headings on their own lines.
    brief = re.sub(r"(?<!\n)\n(?!\n|\s*[-*+] |\s*\d+\. |#)", " ", d.get("brief") or d.get("summary") or "")
    if brief:
        lines += [brief if len(brief) < 600 else brief[:600].rsplit(" ", 1)[0] + " …", ""]
    if t.get("rationale"):
        lines += ["Why:", *[f"- {r}" for r in t["rationale"]], ""]
    if t["discussed_in"]:
        disc = t["discussed_in"][0]
        lines.append(
            f"Discussed in [{disc['id']}]({disc['url']})"
            + (f": {disc['title']}" if disc.get("title") else "")
        )
    impl = sorted(t["implemented_by"], key=lambda p: p.get("merged_at") or 0)
    if impl:
        lines.append(f"Implemented by {len(impl)} PR(s), e.g.:")
        lines += [
            f"- {_pr_link(p['id'], p.get('url'))} {p.get('title') or ''} (merged {_date(p.get('merged_at'))})"
            for p in impl[-implemented:]
        ]
    people = []
    if t["authors"]:
        people.append("authors " + ", ".join(_person(a) for a in t["authors"]))
    approvers = [a["login"] for a in t["approvers"] if a["kind"] == "sig"]
    if approvers:
        people.append("approvers " + ", ".join(_person(a) for a in approvers))
    if t["reviewers"]:
        people.append("reviewers " + ", ".join(_person(a) for a in t["reviewers"]))
    if people:
        lines.append("People: " + "; ".join(people))
    for label, key in (("Replaces", "replaces"), ("Replaced by", "replaced_by")):
        if t[key]:
            lines.append(f"{label}: " + ", ".join(f"[{x['id']}]({x['url']})" for x in t[key]))
    return lines


def _trace(decision_id: str) -> dict:
    t = brain.decision(decision_id)
    extra = run("decision_extraction", {"id": t["decision"]["id"]}, read_only=True)
    if extra:
        t["decision"]["brief"] = extra[0]["brief"]
        t["rationale"] = extra[0]["rationale"] or []
    return t


def render_onboarding(o: dict) -> str:
    """An onboarding brief (Markdown) from brain.onboarding() facts."""
    c = o["component"]
    lines = [f"## Onboarding: {c['name']}" + (f" ({', '.join(o['team'])})" if o["team"] else ""), ""]
    lines += ["**Who to ask**"] + [
        f"- {_person(x['login'])}: {'; '.join(x['reasons'])}" for x in o["experts"]
    ]
    lines += ["", "**Decisions that shaped it**"] + [
        f"- [{d['id']}]({d['url']}) {d['title']} ({d['status']}, {d['prs']} PRs)" for d in o["decisions"]
    ]
    lines += ["", "**Files that change most**"] + [
        f"- `{f['path']}` ({f['prs']} PRs)" for f in o["hot_files"][:6]
    ]
    lines += ["", "**Recently merged**"] + [
        f"- {_pr_link(p['id'], p['url'])} {p['title']} by {', '.join(p['author'])}"
        for p in o["recent_prs"][:5]
    ]
    lines += ["", "**In flight**"] + [
        f"- {_pr_link(p['id'], p['url'])} {p['title']} by {', '.join(p['author'])}" for p in o["open_prs"][:5]
    ]
    return "\n".join(lines)


def answer(intent: Intent) -> tuple[str, list]:
    """Graph-only answer for an intent: (markdown, raw results used as evidence)."""
    if intent.kind == "why_switch":
        x, y = intent.args["x"], intent.args["y"]
        found = find_switch(x, y)
        if not found["decisions"]:
            return f"I found no decision about moving from **{x}** to **{y}**.", [found]
        top = _trace(found["decisions"][0]["id"])
        lines = [f"Moving from **{x}** to **{y}** traces back to:", "", *render_trace(top)]
        others = found["decisions"][1:4]
        if others:
            lines += [
                "",
                "Related decisions: " + ", ".join(f"[{d['id']}]({d['url']}) {d['title']}" for d in others),
            ]
        lines += ["", f"_Matched by {found['basis']}._"]
        return "\n".join(lines), [found, top]
    if intent.kind == "decision":
        t = _trace(intent.args["id"])
        return "\n".join(render_trace(t)), [t]
    if intent.kind == "experts":
        e = brain.experts(topic=intent.args["topic"], k=6)
        target = e["component"] or e["team"]
        lines = [
            f"People who know **{target}** best (merged PRs, last {e['window_days']} days, plus KEPs):",
            "",
        ]
        for i, x in enumerate(e["experts"], 1):
            ev = x.get("evidence") or []
            example = f" · e.g. {_pr_link(ev[0]['id'], ev[0]['url'])} {ev[0]['title']}" if ev else ""
            lines.append(f"{i}. {_person(x['login'])}: {'; '.join(x['reasons'])}{example}")
        return "\n".join(lines), [e]
    if intent.kind == "reviewers":
        r = brain.reviewers(intent.args["pr"], k=3)
        pr = r["pr"]["pr"]
        comps = ", ".join(c.removeprefix("dir:") for c in r["pr"]["components"])
        lines = [
            f"Suggested reviewers for {_pr_link(pr['id'], pr['url'])} {pr['title']} (touches {comps}):",
            "",
        ]
        for i, s in enumerate(r["suggestions"], 1):
            ev = ", ".join(_pr_link(p) for p in s.get("evidence", [])[:3])
            lines.append(
                f"{i}. {_person(s['login'])}: {'; '.join(s['reasons'])}" + (f" ({ev})" if ev else "")
            )
        if r["pr"]["reviewers"]:
            lines += [
                "",
                "Already reviewing: " + ", ".join(_person(x["login"]) for x in r["pr"]["reviewers"]),
            ]
        return "\n".join(lines), [r]
    if intent.kind == "onboarding":
        o = brain.onboarding(intent.args["component"])
        return render_onboarding(o), [o]
    text = intent.args["text"]
    decisions = run("decision_search", {"q": search_query(text, all_terms=False), "k": 5}, read_only=True)
    topics = brain.resolve_topic(text)
    lines = ["Here is what the graph has on that:", ""]
    lines += [f"- [{d['id']}]({d['url']}) {d['title']} ({d['status']})" for d in decisions] or [
        "- no decisions"
    ]
    if topics:
        lines += ["", "Related areas: " + ", ".join(f"{t['id']} ({t['kind']})" for t in topics)]
    return "\n".join(lines), [decisions, topics]


def ask_graph_only(question: str) -> dict:
    intent = classify(question)
    try:
        md, raw = answer(intent)
    except brain.NotFound as exc:
        md, raw = f"I couldn't answer that from the graph: {exc}.", []
    evidence = collect_evidence(raw, {})
    md, removed = ground(md, evidence)
    return {
        "mode": "graph-only",
        "intent": {"kind": intent.kind, **intent.args},
        "answer_md": md,
        "evidence": list(evidence.values()),
        "ungrounded": removed,
    }
