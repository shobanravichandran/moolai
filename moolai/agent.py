"""/api/ask: Claude answers company-brain questions using the graph as its only source.

Every tool is a brain/router function over named Cypher queries. Everything a tool returns goes into an
evidence set, and the grounding check strips any link in the answer that isn't in it. With graph_only=True,
with no Claude key, or if the model call fails, the keyword router answers instead: the same facts, templated
wording.
"""

import json
import logging
import time
from dataclasses import dataclass, field

import anthropic
from anthropic import beta_tool
from anthropic.lib.tools import ToolError

from . import brain, llm, router
from .db import run

log = logging.getLogger("moolai.agent")

EFFORT = "medium"
MAX_ITERATIONS = 8

# Byte-stable (no dates, no per-request text) so the tools + system prefix stays cached.
SYSTEM = """You are Moolai, the company brain for the Kubernetes open-source project. You answer questions
about who knows what, why design decisions were made, who should review a change, and how to get started in an
area.

Use the tools for every fact. They read a graph built from KEPs (Kubernetes Enhancement Proposals), the KEP
tracking issues, and kubernetes/kubernetes pull requests, reviews and comments.
- "Why did they switch from X to Y?": call why_switch, then decision_trace on the best match.
- "Who knows X?" / "who owns X?": call who_knows.
- "Who should review this PR?": call suggest_reviewers with the PR reference.
- Onboarding or "where do I start with X?": call onboarding_brief.
- Anything else: start with find_decisions or who_knows.

Answering:
- Cite sources with markdown links copied exactly from tool results: KEPs, PRs, issues, and people as
  [login](https://github.com/login). Never write a URL, KEP number or PR number that no tool returned.
- Lead with the direct answer, then the trace (decision -> discussion -> implementing PRs -> people), short.
- Reply in the language and style of the question. A Tanglish question gets a Tanglish answer; keep technical
  terms, names and links as they are.
- If the graph doesn't have the answer, say so plainly and say what it does have."""


@dataclass
class AgentState:
    raw: list = field(default_factory=list)  # every tool result, for the evidence set
    calls: list = field(default_factory=list)  # tool name, input, ms, ok


def _dates(value):
    """Epoch-second timestamps -> YYYY-MM-DD so the model reads dates, not integers."""
    if isinstance(value, dict):
        return {
            k: time.strftime("%Y-%m-%d", time.gmtime(v))
            if isinstance(v, int)
            and (k.endswith("_at") or k in {"created", "last_active", "last_pr"})
            and v > 10**8
            else _dates(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_dates(v) for v in value]
    return value


def build_tools(state: AgentState) -> list:
    def done(name: str, args: dict, started: float, result) -> str:
        state.raw.append(result)
        state.calls.append(
            {"tool": name, "input": args, "ms": round((time.perf_counter() - started) * 1000), "ok": True}
        )
        return json.dumps(_dates(result), default=str, ensure_ascii=False)

    def fail(name: str, args: dict, started: float, exc: Exception):
        state.calls.append(
            {"tool": name, "input": args, "ms": round((time.perf_counter() - started) * 1000), "ok": False}
        )
        raise ToolError(str(exc)) from exc

    @beta_tool
    def find_decisions(query: str) -> str:
        """Full-text search over KEP titles and summaries. Returns up to 8 decisions with status and links.

        Args:
            query: A few keywords, e.g. "dockershim removal" or "structured authentication".
        """
        t = time.perf_counter()
        q = router.search_query(query, all_terms=False)
        try:
            return done(
                "find_decisions",
                {"query": query},
                t,
                run("decision_search", {"q": q, "k": 8}, read_only=True),
            )
        except Exception as exc:  # report to the model as a tool error
            fail("find_decisions", {"query": query}, t, exc)

    @beta_tool
    def why_switch(from_tech: str, to_tech: str) -> str:
        """Find the decisions (KEPs) behind moving from one technology or mechanism to another.

        Args:
            from_tech: What was moved away from, e.g. "iptables", "dockershim", "podsecuritypolicy".
            to_tech: What it moved to, e.g. "nftables", "containerd", "pod security admission".
        """
        t = time.perf_counter()
        args = {"from_tech": from_tech, "to_tech": to_tech}
        try:
            return done("why_switch", args, t, router.find_switch(from_tech.lower(), to_tech.lower()))
        except Exception as exc:
            fail("why_switch", args, t, exc)

    @beta_tool
    def decision_trace(decision_id: str) -> str:
        """Everything linked to one decision: summary, status, owning team, tracking issue, implementing PRs,
        authors, reviewers, approvers, and the decisions it replaces or relates to.

        Args:
            decision_id: A KEP id such as "KEP-3866".
        """
        t = time.perf_counter()
        try:
            trace = router._trace(decision_id)
            trace["implemented_by"] = sorted(trace["implemented_by"], key=lambda p: p.get("merged_at") or 0)[
                -12:
            ]
            return done("decision_trace", {"decision_id": decision_id}, t, trace)
        except Exception as exc:
            fail("decision_trace", {"decision_id": decision_id}, t, exc)

    @beta_tool
    def who_knows(topic: str) -> str:
        """Rank the people who know an area best, from merged PRs they authored or reviewed in the last year
        and the KEPs they wrote or approved. Each person comes with reasons and example PRs.

        Args:
            topic: A component or team, e.g. "auth", "kube-proxy", "kubelet", "DRA", "sig-network".
        """
        t = time.perf_counter()
        try:
            return done("who_knows", {"topic": topic}, t, brain.experts(topic=topic, k=6))
        except Exception as exc:
            fail("who_knows", {"topic": topic}, t, exc)

    @beta_tool
    def suggest_reviewers(pr: str) -> str:
        """Suggest reviewers for a pull request from who recently worked on the same files and components.
        Backtested: a suggested person actually reviewed the PR in 79% of past cases (top 3).

        Args:
            pr: A PR URL or reference, e.g. "https://github.com/kubernetes/kubernetes/pull/143065", "#143065".
        """
        t = time.perf_counter()
        try:
            return done("suggest_reviewers", {"pr": pr}, t, brain.reviewers(pr, k=3))
        except Exception as exc:
            fail("suggest_reviewers", {"pr": pr}, t, exc)

    @beta_tool
    def onboarding_brief(component: str) -> str:
        """Facts for onboarding to a component: who to ask, decisions that shaped it, files that change most,
        recently merged and in-flight PRs.

        Args:
            component: A component id or name, e.g. "kube-proxy", "auth", "kubelet", "scheduler".
        """
        t = time.perf_counter()
        try:
            matches = [m for m in brain.resolve_topic(component) if m["kind"] == "component"]
            if not matches:
                raise brain.NotFound(f"no component matches {component!r}")
            return done("onboarding_brief", {"component": component}, t, brain.onboarding(matches[0]["id"]))
        except Exception as exc:
            fail("onboarding_brief", {"component": component}, t, exc)

    return [find_decisions, why_switch, decision_trace, who_knows, suggest_reviewers, onboarding_brief]


def ask_agent(question: str) -> dict:
    state = AgentState()
    runner = llm.client().beta.messages.tool_runner(
        max_tokens=16000,
        system=SYSTEM,
        tools=build_tools(state),
        messages=[{"role": "user", "content": question}],
        max_iterations=MAX_ITERATIONS,
        cache_control={"type": "ephemeral"},
        **llm.request_kwargs(EFFORT),
    )
    final = None
    for message in runner:  # one item per model call, so each call's cost is recorded
        llm.record_usage("agent", message)
        final = message
    if final is None or final.stop_reason == "refusal":
        raise RuntimeError("the model declined to answer")
    evidence = router.collect_evidence(state.raw, {})
    answer_md, removed = router.ground(llm.text_of(final), evidence)
    return {
        "mode": "agent",
        "answer_md": answer_md,
        "tool_calls": state.calls,
        "evidence": list(evidence.values()),
        "ungrounded": removed,
        "unknown_keps": router.unknown_keps(answer_md, evidence),
    }


def ask(question: str, *, graph_only: bool = False) -> dict:
    """Answer with Claude unless graph_only is set or unavailable; fall back to graph-only on model errors."""
    intent = router.classify(question)
    if graph_only or not llm.available():
        out = router.ask_graph_only(question)
        if not graph_only:
            out["note"] = "No Claude key configured: answered in graph-only mode."
        return out
    try:
        out = ask_agent(question)
    except (anthropic.APIError, RuntimeError) as exc:
        log.warning("agent failed, answering graph-only: %s", exc)
        out = router.ask_graph_only(question)
        out["note"] = f"Claude unavailable ({type(exc).__name__}); answered in graph-only mode."
    out.setdefault("intent", {"kind": intent.kind, **intent.args})
    return out
