"""KEP decision extraction: what a KEP moves away from and towards, and why (Claude, cached).

Usage: python -m moolai.extract [--mode batch|direct] [--limit N] [--load-only]

For KEPs owned by `extract_teams` (config/sources.yaml), Claude reads the title + Summary + Motivation +
Alternatives already in the graph and returns a validated Extraction. Results are cached in
data/extract/KEP-N.json, keyed by a hash of that input, so unchanged KEPs are never re-sent and `--load-only`
rebuilds the Technology edges without an API key:

  (Decision)-[:MOVES_FROM]->(Technology)   (Decision)-[:MOVES_TO]->(Technology)
  Decision.rationale (list), Decision.alternatives_considered (list of "option: why rejected")

Batch mode (default) uses the Message Batches API at half price; the refusal fallback isn't available there.
"""

import argparse
import hashlib
import json
import logging
import re
import time

from pydantic import BaseModel, Field, ValidationError

from . import llm
from .config import DATA_DIR, settings
from .db import run
from .ingest.pulls import sources

log = logging.getLogger("moolai.extract")

CACHE_DIR = DATA_DIR / "extract"
PROMPT_VERSION = "v1"

SYSTEM = """You extract design decisions from Kubernetes Enhancement Proposals (KEPs).

Return only what the KEP text supports:
- summary: two or three plain sentences: what the KEP changes and why.
- moves_from / moves_to: only when the KEP replaces, migrates away from, deprecates or supersedes one
  mechanism in favor of another (e.g. iptables -> nftables, dockershim -> CRI runtimes, PodSecurityPolicy ->
  Pod Security Admission). Use short canonical lower-case names of the mechanisms (e.g. "iptables",
  "nftables", "podsecuritypolicy", "pod security admission", "endpoints", "endpointslice", "cgroup v1",
  "cgroup v2").
  Leave both empty when the KEP only adds or improves something without replacing anything.
- rationale: up to five short reasons the KEP gives for the change, in the KEP's own terms.
- alternatives: options the KEP considered and why each was not chosen (empty if it lists none)."""


class Alternative(BaseModel):
    option: str
    why_rejected: str


class Extraction(BaseModel):
    summary: str
    moves_from: list[str] = Field(default_factory=list)
    moves_to: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)


SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "moves_from": {"type": "array", "items": {"type": "string"}},
        "moves_to": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "array", "items": {"type": "string"}},
        "alternatives": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"option": {"type": "string"}, "why_rejected": {"type": "string"}},
                "required": ["option", "why_rejected"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "moves_from", "moves_to", "rationale", "alternatives"],
    "additionalProperties": False,
}


# ---------- inputs and cache ----------


def render(kep: dict) -> str:
    parts = [f"KEP: {kep['id']}: {kep['title']}", f"Status: {kep['status']}, stage: {kep['stage']}"]
    for name in ("summary", "motivation", "alternatives"):
        if kep.get(name):
            parts.append(f"<{name}>\n{kep[name]}\n</{name}>")
    return "\n\n".join(parts)


def input_hash(kep: dict) -> str:
    return hashlib.sha256((PROMPT_VERSION + settings.model + render(kep)).encode()).hexdigest()[:16]


def cached(kep: dict) -> Extraction | None:
    path = CACHE_DIR / f"{kep['id']}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return Extraction.model_validate(data["output"]) if data.get("hash") == input_hash(kep) else None


def save(kep: dict, out: Extraction) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    body = {"id": kep["id"], "hash": input_hash(kep), "model": settings.model, "output": out.model_dump()}
    (CACHE_DIR / f"{kep['id']}.json").write_text(
        json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8"
    )


def tech_name(name: str) -> str:
    """Canonical Technology key: lower-case, single spaces, no surrounding punctuation."""
    return re.sub(r"\s+", " ", name.strip().strip(".,;:()\"'`").lower())


# ---------- Claude ----------


def extract_direct(keps: list[dict]) -> int:
    done = 0
    for kep in keps:
        response = llm.client().beta.messages.parse(
            max_tokens=4000,
            system=SYSTEM,
            messages=[{"role": "user", "content": render(kep)}],
            output_format=Extraction,
            **llm.request_kwargs("low"),
        )
        llm.record_usage("extract", response)
        if response.stop_reason == "refusal" or response.parsed_output is None:
            log.warning("%s: no extraction (%s)", kep["id"], response.stop_reason)
            continue
        save(kep, response.parsed_output)
        done += 1
    return done


def extract_batch(keps: list[dict], poll_s: int = 30) -> int:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    by_id = {k["id"].replace("@", "_"): k for k in keps}  # custom_id allows [a-zA-Z0-9_-] only
    batch = llm.client().messages.batches.create(
        requests=[
            Request(
                custom_id=cid,
                params=MessageCreateParamsNonStreaming(
                    model=settings.model,
                    max_tokens=4000,
                    system=SYSTEM,
                    messages=[{"role": "user", "content": render(kep)}],
                    output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
                ),
            )
            for cid, kep in by_id.items()
        ]
    )
    log.info("batch %s submitted with %d KEPs", batch.id, len(by_id))
    while batch.processing_status != "ended":
        time.sleep(poll_s)
        batch = llm.client().messages.batches.retrieve(batch.id)
        log.info("batch %s: %s", batch.id, batch.request_counts)
    done = 0
    for result in llm.client().messages.batches.results(batch.id):
        kep = by_id[result.custom_id]
        if result.result.type != "succeeded":
            log.warning("%s: %s", kep["id"], result.result.type)
            continue
        message = result.result.message
        llm.record_usage("extract-batch", message, batch=True)
        if message.stop_reason == "refusal":
            log.warning("%s: refused", kep["id"])
            continue
        try:
            save(kep, Extraction.model_validate_json(llm.text_of(message)))
            done += 1
        except ValidationError as exc:
            log.warning("%s: invalid output (%s)", kep["id"], exc.error_count())
    return done


# ---------- graph ----------


def load(keps: list[dict]) -> dict:
    """Write cached extractions to the graph (replacing earlier MOVES_* edges for those KEPs)."""
    rows = []
    for kep in keps:
        out = cached(kep)
        if out is None:
            continue
        rows.append(
            {
                "decision": kep["id"],
                "summary": out.summary,
                "rationale": out.rationale,
                "alternatives": [f"{a.option}: {a.why_rejected}" for a in out.alternatives],
                "from": sorted({tech_name(t) for t in out.moves_from if tech_name(t)}),
                "to": sorted({tech_name(t) for t in out.moves_to if tech_name(t)}),
            }
        )
    for i in range(0, len(rows), 200):
        run("link_decision_tech", {"rows": rows[i : i + 200]})
    return {"loaded": len(rows), "switches": sum(1 for r in rows if r["from"] and r["to"])}


def sync(mode: str = "batch", limit: int | None = None, load_only: bool = False) -> dict:
    keps = run("extract_candidates", {"teams": sources()["extract_teams"]}, read_only=True)
    todo = [k for k in keps if cached(k) is None][:limit]
    sent = 0
    if todo and not load_only:
        if not llm.available():
            raise SystemExit("ANTHROPIC_API_KEY is not set: add it to .env, or use --load-only")
        sent = extract_batch(todo) if mode == "batch" else extract_direct(todo)
    return {"candidates": len(keps), "to_extract": len(todo), "extracted": sent, **load(keps)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mode", choices=["batch", "direct"], default="batch")
    p.add_argument("--limit", type=int)
    p.add_argument("--load-only", action="store_true", help="only write cached extractions to the graph")
    a = p.parse_args()
    print(json.dumps(sync(a.mode, a.limit, a.load_only), indent=2))
