import dataclasses
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from moolai import agent, brain, db, extract, llm, router
from moolai.ingest import keps as k
from tests.test_keps import keps_root  # noqa: F401  (fixture)
from tests.test_schema import _falkordb_up

# ---------- router ----------


@pytest.mark.parametrize(
    ("question", "kind", "args"),
    [
        ("Why did kube-proxy switch from iptables to nftables?", "why_switch", {"x": "iptables", "y": "nftables"}),
        ("Ean iptables-la irundhu nftables-ku switch pannanga?", "why_switch", {"x": "iptables", "y": "nftables"}),
        ("Why did we replace PodSecurityPolicy with Pod Security Admission?", "why_switch",
         {"x": "podsecuritypolicy", "y": "pod security admission"}),
        ("why dockershim -> containerd", "why_switch", {"x": "dockershim", "y": "containerd"}),
        ("Auth module pathi yaarukku theriyum?", "experts", {"topic": "auth"}),
        ("Who maintains kube-proxy?", "experts", {"topic": "kube-proxy"}),
        ("Indha PR-ku yaar review pannanum? kubernetes/kubernetes#143065", "reviewers",
         {"pr": "kubernetes/kubernetes#143065"}),
        ("Who should review https://github.com/kubernetes/kubernetes/pull/143065", "reviewers",
         {"pr": "github.com/kubernetes/kubernetes/pull/143065"}),
        ("Tell me about KEP-2579", "decision", {"id": "KEP-2579"}),
        ("Onboard me to kube-proxy", "onboarding", {"component": "kube-proxy"}),
        ("what about cgroup v2", "search", {"text": "what about cgroup v2"}),
    ],
)  # fmt: skip
def test_classify(question, kind, args):
    intent = router.classify(question)
    assert (intent.kind, intent.args) == (kind, args)


EVIDENCE = router.collect_evidence(
    [
        {
            "id": "KEP-3866",
            "title": "nftables",
            "url": "https://github.com/kubernetes/enhancements/issues/3866",
        },
        {"authors": ["danwinship"], "approvers": [{"login": "thockin", "kind": "sig"}]},
        "kubernetes/kubernetes#121046",
        {"summary": "See https://k8s.io/dockershim for details."},
    ],
    {},
)


def test_collect_evidence():
    assert set(EVIDENCE) == {
        "https://github.com/kubernetes/enhancements/issues/3866",
        "https://github.com/danwinship",
        "https://github.com/thockin",
        "https://github.com/kubernetes/kubernetes/pull/121046",
        "https://k8s.io/dockershim",
    }


def test_ground_strips_only_unsupported_links():
    answer = (
        "Per [KEP-3866](https://github.com/kubernetes/enhancements/pull/3866), written by "
        "[danwinship](https://github.com/danwinship) and merged in [#121046](https://github.com/kubernetes/kubernetes/pull/121046). "
        "Also [#999999](https://github.com/kubernetes/kubernetes/pull/999999) and https://example.com/made-up. "
        "See https://k8s.io/dockershim."
    )
    grounded, removed = router.ground(answer, EVIDENCE)
    assert removed == ["https://github.com/kubernetes/kubernetes/pull/999999", "https://example.com/made-up"]
    assert "[KEP-3866](https://github.com/kubernetes/enhancements/pull/3866)" in grounded  # /pull == /issues
    assert "Also #999999 and [link removed]." in grounded
    assert "https://k8s.io/dockershim" in grounded
    raw = [{"id": "KEP-3866", "url": "https://x"}, {"login": "liggitt", "keps": ["KEP-740", "KEP-4633"]}]
    assert router.unknown_keps("KEP-3866, KEP-740 and KEP-42", raw) == ["KEP-42"]  # plain-string ids count


# ---------- agent (fake Claude client) ----------


def _message(text: str, stop_reason: str = "end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0),
    )


class FakeClient:
    """Stands in for anthropic.Anthropic(): its tool_runner calls one tool, then returns a scripted answer."""

    def __init__(self, tool: str, tool_input: dict, answer: str, stop_reason: str = "end_turn"):
        self.tool, self.tool_input, self.answer, self.stop_reason = tool, tool_input, answer, stop_reason
        self.kwargs = None
        self.beta = SimpleNamespace(messages=SimpleNamespace(tool_runner=self.tool_runner))

    def tool_runner(self, **kwargs):
        self.kwargs = kwargs
        tools = {t.name: t for t in kwargs["tools"]}
        tools[self.tool].call(self.tool_input)
        yield _message("", "tool_use")
        yield _message(self.answer, self.stop_reason)


EXPERTS = {
    "component": "auth",
    "team": None,
    "window_days": 365,
    "experts": [
        {
            "login": "liggitt",
            "score": 15.7,
            "reasons": ["reviewed 39 merged PR(s)"],
            "evidence": [
                {"id": "kubernetes/kubernetes#138469", "title": "delete PSA webhook",
                 "url": "https://github.com/kubernetes/kubernetes/pull/138469", "merged_at": 1792122366}
            ],
        }
    ],
}  # fmt: skip


def test_agent_grounds_answer_and_records_tools(monkeypatch):
    fake = FakeClient(
        "who_knows",
        {"topic": "auth"},
        "Auth-ku [liggitt](https://github.com/liggitt) dhaan best, e.g. "
        "[#138469](https://github.com/kubernetes/kubernetes/pull/138469); also [bob](https://github.com/bob).",
    )
    monkeypatch.setattr(llm, "client", lambda: fake)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(brain, "experts", lambda **kw: EXPERTS)
    out = agent.ask("Auth module pathi yaarukku theriyum?")
    assert out["mode"] == "agent"
    assert out["ungrounded"] == ["https://github.com/bob"]  # never returned by a tool
    assert "[liggitt](https://github.com/liggitt)" in out["answer_md"] and "also bob." in out["answer_md"]
    assert [(c["tool"], c["input"], c["ok"]) for c in out["tool_calls"]] == [
        ("who_knows", {"topic": "auth"}, True)
    ]
    # Request shape: model, effort, refusal fallback, caching, and no forced tool choice (Opus 5.5 rejects it).
    kw = fake.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["output_config"] == {"effort": "medium"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["cache_control"] == {"type": "ephemeral"} and "tool_choice" not in kw


def test_agent_tool_dates_are_readable(monkeypatch):
    fake = FakeClient("who_knows", {"topic": "auth"}, "ok")
    monkeypatch.setattr(llm, "client", lambda: fake)
    monkeypatch.setattr(brain, "experts", lambda **kw: EXPERTS)
    state = agent.AgentState()
    tools = {t.name: t for t in agent.build_tools(state)}
    payload = json.loads(tools["who_knows"].call({"topic": "auth"}))
    assert payload["experts"][0]["evidence"][0]["merged_at"] == "2026-10-16"


@pytest.mark.parametrize("failure", ["api_error", "refusal"])
def test_agent_falls_back_to_graph_only(monkeypatch, failure):
    if failure == "api_error":
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

        def broken():
            raise anthropic.APIConnectionError(request=request)

        monkeypatch.setattr(llm, "client", broken)
    else:
        fake = FakeClient("who_knows", {"topic": "auth"}, "", stop_reason="refusal")
        monkeypatch.setattr(llm, "client", lambda: fake)
        monkeypatch.setattr(brain, "experts", lambda **kw: EXPERTS)
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(
        router, "ask_graph_only", lambda q: {"mode": "graph-only", "answer_md": "graph answer"}
    )
    out = agent.ask("Who knows auth?")
    assert out["mode"] == "graph-only" and out["note"].startswith("Claude unavailable")


def test_no_key_means_graph_only(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)
    monkeypatch.setattr(
        router, "ask_graph_only", lambda q: {"mode": "graph-only", "answer_md": "graph answer"}
    )
    out = agent.ask("Who knows auth?")
    assert out["mode"] == "graph-only" and "No Claude key" in out["note"]


# ---------- extraction ----------


def test_extraction_schema_and_names():
    out = extract.Extraction.model_validate_json(
        '{"summary": "s", "moves_from": [" IPTables. "], "moves_to": ["nftables"], "rationale": [],'
        ' "alternatives": [{"option": "ipvs", "why_rejected": "also old"}]}'
    )
    assert [extract.tech_name(t) for t in out.moves_from] == ["iptables"]
    assert extract.SCHEMA["required"] == list(extract.Extraction.model_fields)


@pytest.mark.db
@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB is not reachable")
def test_extraction_cache_loads_switch_edges(keps_root: Path, tmp_path: Path, monkeypatch):  # noqa: F811
    name = f"test_extract_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, graph=name))
    monkeypatch.setattr(extract, "CACHE_DIR", tmp_path / "extract")
    try:
        k.load(k.dedupe([k.parse_kep(d, keps_root) for d in k.kep_dirs(keps_root)]))
        candidates = db.run("extract_candidates", {"teams": ["sig-network"]}, read_only=True)
        kep = next(c for c in candidates if c["id"] == "KEP-3866")
        extract.save(kep, extract.Extraction(summary="Adds an nftables kube-proxy backend.",
                                             moves_from=["iptables"], moves_to=["NFTables"],
                                             rationale=["iptables has unfixable performance problems"]))  # fmt: skip
        assert extract.load(candidates) == {"loaded": 1, "switches": 1}
        assert extract.load(candidates) == {"loaded": 1, "switches": 1}  # idempotent
        rows = db.run("decision_switch", {"x": "iptables", "y": "nftables", "k": 5}, read_only=True)
        assert [(r["id"], r["moves_from"], r["moves_to"]) for r in rows] == [
            ("KEP-3866", "iptables", "nftables")
        ]
        found = router.find_switch("iptables", "nftables")
        assert found["basis"] == "extracted MOVES_FROM / MOVES_TO edges"
        # The KEP names the target differently: fall back to "moved away from X", still from extracted edges.
        other = router.find_switch("iptables", "ebpf")
        assert [d["id"] for d in other["decisions"]] == ["KEP-3866"] and "MOVES_FROM 'iptables'" in other[
            "basis"
        ]
        # A changed input (e.g. the KEP was edited) invalidates the cache entry.
        assert extract.cached({**kep, "summary": "edited"}) is None
    finally:
        db.graph().delete()


# ---------- hosted demo: shared daily budget ----------


def test_budget_spent_means_graph_only(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(agent, "budget_left", lambda: 0.0)
    monkeypatch.setattr(
        llm, "client", lambda: pytest.fail("Claude must not be called once the budget is spent")
    )
    monkeypatch.setattr(
        router, "ask_graph_only", lambda q: {"mode": "graph-only", "answer_md": "graph answer"}
    )
    out = agent.ask("Who knows auth?")
    assert out["mode"] == "graph-only" and "budget" in out["note"]


@pytest.mark.db
@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB is not reachable")
def test_budget_is_shared_through_the_graph(monkeypatch):
    name = f"test_budget_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, graph=name))
    monkeypatch.setattr(agent, "settings", dataclasses.replace(agent.settings, daily_budget_usd=0.10))
    try:
        from moolai.schema import ensure_schema

        ensure_schema()
        assert agent.budget_left() == pytest.approx(0.10)
        agent._spend(0.04)
        agent._spend(0.04)
        assert agent.budget_left() == pytest.approx(0.02)
    finally:
        db.graph().delete()
