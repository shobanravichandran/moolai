"""KEPs (kubernetes/enhancements) -> Decision, Team, Person, tracking Issue.

Usage: python -m moolai.ingest.keps [--full]

Clones the repo shallowly into data/enhancements (or fetches if it's there), parses every
keps/<sig>/<NNNN-slug>/kep.yaml plus the Summary / Motivation / Alternatives sections of README.md,
and upserts them. The last loaded commit is kept in (:SyncState); later runs only reload the KEP
dirs that git says changed.
"""

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path

import yaml

from ..config import DATA_DIR
from ..db import run
from ..schema import ensure_schema

REPO = "kubernetes/enhancements"
REPO_URL = f"https://github.com/{REPO}.git"
CLONE_DIR = DATA_DIR / "enhancements"
SYNC_SOURCE = f"git:{REPO}:keps"

STATUSES = {"provisional", "implementable", "implemented", "deferred", "rejected", "withdrawn", "replaced",
            "superseded", "removed"}  # fmt: skip
STAGES = {"alpha", "beta", "stable", "deprecated", "disabled", "removed"}
TYPOS = {"imlpemented": "implemented"}

SECTION_LIMITS = {"summary": 2000, "motivation": 4000, "alternatives": 4000}
_LOGIN = re.compile(r"@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))")
_BARE_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_KEP_REF = re.compile(r"(?:keps/[\w-]+/(\d+)-|enhancements/issues/(\d+)\b|^KEP-(\d+)$)", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


class _Loader(yaml.SafeLoader):
    """SafeLoader that leaves dates as strings: some kep.yaml files have impossible dates (month 13)."""


_Loader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


@dataclass
class Kep:
    number: int
    dir: str  # keps/sig-network/3866-nftables-proxy
    title: str
    status: str
    stage: str | None
    owning_team: str
    participating_teams: list[str]
    authors: list[str]
    reviewers: list[str]
    approvers: list[str]
    prr_approvers: list[str]
    replaces: list[int]
    superseded_by: list[int]
    see_also: list[int]
    created: int | None
    latest_milestone: str | None
    summary: str = ""
    motivation: str = ""
    alternatives: str = ""
    errors: list[str] = field(default_factory=list)
    duplicate_of: str | None = None  # set when a moved KEP left its old dir behind under the same number

    @property
    def id(self) -> str:
        return f"KEP-{self.number}@{self.dir.split('/')[1]}" if self.duplicate_of else f"KEP-{self.number}"


# ---------- parsing (pure functions, unit-tested) ----------


def first_token(value) -> str:
    """'implementable # provisional|...' -> 'implementable'; quotes and case dropped."""
    text = str(value or "").split("#", 1)[0].strip().strip("\"'").lower()
    return text.split()[0] if text else ""


def norm_status(value) -> str:
    token = TYPOS.get(first_token(value), first_token(value))
    return token if token in STATUSES else "unknown"


def norm_stage(value) -> str | None:
    token = first_token(value)
    return token if token in STAGES else None


TEAM_ALIASES = {
    "sig-apimachinery": "sig-api-machinery",
    "sig-machinery": "sig-api-machinery",
    "sig-arch": "sig-architecture",
    "sig-contribex": "sig-contributor-experience",
    "sig-scheduler": "sig-scheduling",
}
NOT_A_TEAM = {"", "tbd", "none", "n/a", "na"}


def norm_team(value) -> str | None:
    """'SIG Network' / 'sig-network # x' -> 'sig-network'; known aliases mapped, placeholders dropped."""
    text = str(value or "").split("#", 1)[0].strip().strip("\"'").lower().replace(" ", "-")
    return None if text in NOT_A_TEAM else TEAM_ALIASES.get(text, text)


def logins(values) -> list[str]:
    """GitHub logins from entries like '@danwinship', 'Dan Winship (@danwinship)' or 'danwinship'.

    Logins are lower-cased: GitHub treats them case-insensitively, and every ingester keys Person on the
    lower-cased login so the same person is one node.
    """
    out: list[str] = []
    for entry in _as_list(values):
        text = str(entry).strip().strip("\"'")
        found = _LOGIN.findall(text) or ([text] if _BARE_LOGIN.match(text) else [])
        for login in found:
            if login.lower() not in out and login.lower() not in {"tbd", "none", "n", "na"}:
                out.append(login.lower())
    return out


def kep_refs(values) -> list[int]:
    """KEP numbers referenced by '/keps/sig-node/4381-dra-...', 'enhancements/issues/1234' or 'KEP-1234'.

    Anything else (design docs, k/k issues, 'n/a') is not a KEP and is dropped.
    """
    out: list[int] = []
    for entry in _as_list(values):
        m = _KEP_REF.search(str(entry).strip().strip("\"'"))
        if m:
            n = int(next(g for g in m.groups() if g))
            if n not in out:
                out.append(n)
    return out


def epoch(value) -> int | None:
    if isinstance(value, datetime):
        return int(value.replace(tzinfo=value.tzinfo or UTC).timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, time(), tzinfo=UTC).timestamp())
    try:
        return epoch(date.fromisoformat(str(value).strip().strip("\"'")[:10]))
    except ValueError:
        return None


def readme_sections(text: str) -> dict[str, str]:
    """Summary, Motivation and Alternatives sections of a KEP README, without template comments or code."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    lines = text.splitlines()
    out: dict[str, str] = {}
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if not m:
            continue
        level, title = len(m.group(1)), m.group(2).strip().lower()
        key = (
            "summary" if title == "summary"
            else "motivation" if title == "motivation"
            else "alternatives" if title.startswith("alternative")
            else None
        )  # fmt: skip
        if not key or key in out:
            continue
        body: list[str] = []
        for nxt in lines[i + 1 :]:
            h = _HEADING.match(nxt)
            if h and len(h.group(1)) <= level:
                break
            body.append(nxt)
        section = re.sub(r"\n{3,}", "\n\n", "\n".join(body)).strip()
        if section:
            out[key] = _trim(section, SECTION_LIMITS[key])
    return out


def parse_kep(kep_dir: Path, keps_root: Path) -> Kep | None:
    """Parse one KEP dir; None if it has no kep.yaml (legacy single-file KEPs, the template)."""
    meta_file = kep_dir / "kep.yaml"
    if not meta_file.is_file():
        return None
    errors: list[str] = []
    try:
        meta = yaml.load(meta_file.read_text(encoding="utf-8"), Loader=_Loader) or {}
    except yaml.YAMLError as exc:
        return None if not kep_dir.name[:1].isdigit() else _broken(kep_dir, keps_root, f"kep.yaml: {exc}")
    number = _int(meta.get("kep-number")) or _int(kep_dir.name.split("-", 1)[0])
    if not number:
        return None
    sig_dir = kep_dir.parent.name
    readme = kep_dir / "README.md"
    sections = readme_sections(readme.read_text(encoding="utf-8")) if readme.is_file() else {}
    if not readme.is_file():
        errors.append("no README.md")
    return Kep(
        number=number,
        dir=kep_dir.relative_to(keps_root.parent).as_posix(),
        title=str(meta.get("title") or kep_dir.name).strip(),
        status=norm_status(meta.get("status")),
        stage=norm_stage(meta.get("stage")),
        owning_team=norm_team(meta.get("owning-sig")) or sig_dir,
        participating_teams=[
            t for t in (norm_team(v) for v in _as_list(meta.get("participating-sigs"))) if t
        ],
        authors=logins(meta.get("authors")),
        reviewers=logins(meta.get("reviewers")),
        approvers=logins(meta.get("approvers")),
        prr_approvers=prr_approvers(keps_root, sig_dir, number),
        replaces=[n for n in kep_refs(meta.get("replaces")) if n != number],
        superseded_by=[n for n in kep_refs(meta.get("superseded-by")) if n != number],
        see_also=[n for n in kep_refs(meta.get("see-also")) if n != number],
        created=epoch(meta.get("creation-date")),
        latest_milestone=(str(meta["latest-milestone"]).strip() if meta.get("latest-milestone") else None),
        summary=sections.get("summary", ""),
        motivation=sections.get("motivation", ""),
        alternatives=sections.get("alternatives", ""),
        errors=errors,
    )


def prr_approvers(keps_root: Path, sig_dir: str, number: int) -> list[str]:
    """Production-readiness approvers from keps/prod-readiness/<sig>/<number>.yaml."""
    path = keps_root / "prod-readiness" / sig_dir / f"{number}.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_Loader) or {}
    except yaml.YAMLError:
        return []
    return logins([v.get("approver") for v in data.values() if isinstance(v, dict)])


def kep_dirs(keps_root: Path) -> list[Path]:
    return sorted(
        d
        for sig in keps_root.iterdir()
        if sig.is_dir() and sig.name not in {"prod-readiness", "NNNN-kep-template"}
        for d in sig.iterdir()
        if d.is_dir() and d.name[:1].isdigit()
    )


def dedupe(keps: list[Kep]) -> list[Kep]:
    """Two dirs can share a KEP number when a KEP moved SIGs (the old copy says 'replaced').

    The live one keeps KEP-N; the others become KEP-N@<sig> and are linked as replaced by it.
    """
    by_number: dict[int, list[Kep]] = {}
    for k in keps:
        by_number.setdefault(k.number, []).append(k)
    for group in by_number.values():
        if len(group) > 1:
            group.sort(key=lambda k: k.status in {"replaced", "superseded", "withdrawn", "unknown"})
            for old in group[1:]:
                old.duplicate_of = group[0].id
    return keps


# ---------- graph rows + loading ----------


def decision_row(k: Kep) -> dict:
    return {
        "id": k.id,
        "number": k.number,
        "team": k.owning_team,
        "issue_id": f"{REPO}#{k.number}",
        "issue_repo": REPO,
        "issue_url": f"https://github.com/{REPO}/issues/{k.number}",
        "props": {
            "kind": "kep",
            "number": k.number,
            "title": k.title,
            "status": k.status,
            "stage": k.stage,
            "latest_milestone": k.latest_milestone,
            "created": k.created,
            "summary": k.summary,
            "motivation": k.motivation,
            "alternatives": k.alternatives,
            "dir": k.dir,
            "url": f"https://github.com/{REPO}/tree/master/{k.dir}",
        },
    }


def people_rows(k: Kep) -> list[dict]:
    """One row per (person, role); approvers carry kind 'sig' or 'prr' (production readiness)."""
    rows = [{"decision": k.id, "login": p, "role": "author", "kind": None} for p in k.authors]
    rows += [{"decision": k.id, "login": p, "role": "reviewer", "kind": None} for p in k.reviewers]
    rows += [{"decision": k.id, "login": p, "role": "approver", "kind": "sig"} for p in k.approvers]
    rows += [{"decision": k.id, "login": p, "role": "approver", "kind": "prr"} for p in k.prr_approvers]
    return rows


def load(keps: list[Kep]) -> dict:
    """Upsert KEPs. Their people/team/ref edges are replaced, so edits to kep.yaml show up on re-sync."""
    ensure_schema()  # also creates the graph: read-only queries fail on a graph that doesn't exist yet
    ids = [k.id for k in keps]
    teams = sorted({k.owning_team for k in keps} | {t for k in keps for t in k.participating_teams})
    known = {r["number"] for r in run("decision_numbers", read_only=True)} | {k.number for k in keps}
    run(
        "upsert_teams",
        {"rows": [{"id": t, "name": _team_name(t), "kind": _team_kind(t)} for t in teams]},
    )
    for chunk in _chunks(ids, 200):
        run("unlink_decisions", {"ids": chunk})
    for chunk in _chunks([decision_row(k) for k in keps], 100):
        run("upsert_decisions", {"rows": chunk})
    people = [r for k in keps for r in people_rows(k)]
    for chunk in _chunks(people, 500):
        run("link_decision_people", {"rows": chunk})
    involves = [
        {"decision": k.id, "team": t} for k in keps for t in k.participating_teams if t != k.owning_team
    ]
    run("link_decision_teams", {"rows": involves})
    refs = [
        {"from": k.id, "to": f"KEP-{n}", "rel": rel}
        for k in keps
        for rel, nums in (("replaces", k.replaces), ("see_also", k.see_also))
        for n in nums
        if n in known
    ]
    refs += [{"from": k.duplicate_of, "to": k.id, "rel": "replaces"} for k in keps if k.duplicate_of]
    # "A is superseded by B" is stored as (B)-[:REPLACES]->(A).
    refs += [
        {"from": f"KEP-{n}", "to": k.id, "rel": "replaces"}
        for k in keps
        for n in k.superseded_by
        if n in known
    ]
    run("link_decision_refs", {"rows": refs})
    run("delete_orphan_teams")
    return {"decisions": len(keps), "teams": len(teams), "people_edges": len(people), "refs": len(refs)}


# ---------- git + sync ----------


def git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def update_clone() -> str:
    """Shallow clone or fetch kubernetes/enhancements; returns the new HEAD sha."""
    if not (CLONE_DIR / ".git").is_dir():
        CLONE_DIR.parent.mkdir(parents=True, exist_ok=True)
        git("clone", "--depth", "1", "--quiet", REPO_URL, str(CLONE_DIR))
    else:
        git("fetch", "--depth", "1", "--quiet", "origin", "HEAD", cwd=CLONE_DIR)
        git("reset", "--hard", "--quiet", "FETCH_HEAD", cwd=CLONE_DIR)
    return git("rev-parse", "HEAD", cwd=CLONE_DIR)


def changed_kep_dirs(old_sha: str, new_sha: str) -> set[str] | None:
    """KEP dirs (keps/<sig>/<NNNN-slug>) touched between two commits; None if the old commit is gone."""
    try:
        names = git("diff", "--name-only", old_sha, new_sha, "--", "keps/", cwd=CLONE_DIR).splitlines()
    except subprocess.CalledProcessError:
        return None
    out = set()
    for name in names:
        parts = name.split("/")
        if parts[1:2] == ["prod-readiness"] and len(parts) == 4:  # keps/prod-readiness/<sig>/<n>.yaml
            out.update(_dirs_for_number(parts[2], parts[3].split(".")[0]))
        elif len(parts) >= 3:
            out.add("/".join(parts[:3]))
    return out


def sync(full: bool = False) -> dict:
    ensure_schema()
    new_sha = update_clone()
    keps_root = CLONE_DIR / "keps"
    state = run("sync_state_get", {"source": SYNC_SOURCE}, read_only=True)
    old_sha = state[0]["cursor"] if state else None
    dirs = kep_dirs(keps_root)
    if old_sha and not full:
        if old_sha == new_sha:
            return {"source": SYNC_SOURCE, "sha": new_sha, "changed": 0}
        changed = changed_kep_dirs(old_sha, new_sha)
        if changed is not None:
            # Reload every dir sharing a number with a changed one, so dedupe() sees the whole group.
            numbers = {
                d.name.split("-", 1)[0] for d in dirs if d.relative_to(CLONE_DIR).as_posix() in changed
            }
            dirs = [d for d in dirs if d.name.split("-", 1)[0] in numbers]
    keps, skipped = [], []
    for d in dirs:
        kep = parse_kep(d, keps_root)
        (keps if kep else skipped).append(kep or d.name)
    stats = load(dedupe(keps))
    stats.update({"skipped": len(skipped), "parse_warnings": sum(1 for k in keps if k.errors)})
    run("sync_state_set", {"source": SYNC_SOURCE, "cursor": new_sha, "stats": _json(stats)})
    return {"source": SYNC_SOURCE, "sha": new_sha, **stats}


# ---------- helpers ----------


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _int(value) -> int | None:
    try:
        return int(str(value).strip().strip("\"'"))
    except (TypeError, ValueError):
        return None


def _trim(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def _team_name(team_id: str) -> str:
    kind, _, rest = team_id.partition("-")
    return f"{kind.upper()} {rest.replace('-', ' ').title()}" if rest else team_id


def _team_kind(team_id: str) -> str:
    if team_id.startswith("wg-") or team_id.endswith("-wg"):
        return "wg"
    return team_id.split("-", 1)[0]


def _chunks(rows: list, size: int):
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def _json(value) -> str:
    return json.dumps(value, sort_keys=True)


def _dirs_for_number(sig: str, number: str) -> set[str]:
    sig_dir = CLONE_DIR / "keps" / sig
    return {f"keps/{sig}/{d.name}" for d in sig_dir.glob(f"{number}-*") if d.is_dir()}


def _broken(kep_dir: Path, keps_root: Path, error: str) -> Kep | None:
    number = _int(kep_dir.name.split("-", 1)[0])
    if not number:
        return None
    return Kep(
        number=number, dir=kep_dir.relative_to(keps_root.parent).as_posix(), title=kep_dir.name,
        status="unknown", stage=None, owning_team=kep_dir.parent.name, participating_teams=[], authors=[],
        reviewers=[], approvers=[], prr_approvers=[], replaces=[], superseded_by=[], see_also=[],
        created=None, latest_milestone=None, errors=[error],
    )  # fmt: skip


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", action="store_true", help="reload every KEP, not just the changed ones")
    print(sync(full=parser.parse_args().full))
