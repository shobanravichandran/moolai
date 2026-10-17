import copy
import dataclasses
import itertools
import uuid

import pytest

from moolai import brain, db
from moolai.components import load_components
from moolai.ingest import mapping as m
from moolai.ingest import pulls
from scripts.backtest_reviewers import random_pool_metrics, ranks_metrics
from tests.test_pulls import BOTS, PR_NODE, _actor
from tests.test_schema import _falkordb_up

DAY = 86400


def test_resolve_topic():
    assert [r["id"] for r in brain.resolve_topic("Auth module pathi yaarukku theriyum?")] == ["auth"]
    assert {r["id"] for r in brain.resolve_topic("who knows kube-proxy and DRA?")} == {"kube-proxy", "dra"}
    assert brain.resolve_topic("how do I drain a node") == []  # 'dra' must not match inside 'drain'
    assert brain.resolve_topic("Dynamic Resource Allocation")[0]["id"] == "dra"
    assert brain.resolve_topic("experts in SIG Network")[0] == {
        "kind": "team",
        "id": "sig-network",
        "name": "sig network",
        "matched": "sig network",
    }


def test_parse_pr_ref():
    assert brain.parse_pr_ref("https://github.com/kubernetes/kubernetes/pull/143065") == (
        "kubernetes/kubernetes",
        143065,
    )
    assert brain.parse_pr_ref("kubernetes/enhancements#3866") == ("kubernetes/enhancements", 3866)
    assert brain.parse_pr_ref("#42") == ("kubernetes/kubernetes", 42)
    assert brain.parse_pr_ref("42") == ("kubernetes/kubernetes", 42)
    with pytest.raises(brain.NotFound):
        brain.parse_pr_ref("kubernetes/kubernetes")


def test_rank_metrics():
    assert ranks_metrics(["a", "b", "c"], {"b"}) == {"hit1": 0.0, "hit3": 1.0, "mrr": 0.5, "covered": 1.0}
    assert ranks_metrics([], {"b"})["covered"] == 0.0


def test_random_pool_metrics_are_exact():
    # Brute force over every ordering of a small pool must match the closed form.
    pool, truth = {"a", "b", "c", "d", "e"}, {"b", "e", "z"}
    perms = list(itertools.permutations(sorted(pool)))
    brute = {
        k: sum(ranks_metrics(list(p), truth)[k] for p in perms) / len(perms) for k in ("hit1", "hit3", "mrr")
    }
    exact = random_pool_metrics(pool, truth)
    for k in brute:
        assert exact[k] == pytest.approx(brute[k])


def _pr(number, author, files, reviewers, merged_day):
    """A fixture PR node: merged `merged_day` days after day 0, reviewed (approved) by `reviewers`."""
    node = copy.deepcopy(PR_NODE)
    iso = f"2026-05-{merged_day:02d}T00:00:00Z"
    url = f"https://github.com/kubernetes/kubernetes/pull/{number}"
    node.update(number=number, title=f"PR {number}", url=url, author=_actor(author), body="",
                createdAt=iso, updatedAt=iso, mergedAt=iso, closedAt=iso)  # fmt: skip
    node["files"] = {
        "totalCount": len(files),
        "nodes": [{"path": f, "additions": 1, "deletions": 0} for f in files],
    }
    node["reviews"] = {
        "nodes": [{"author": _actor(r), "state": "APPROVED", "submittedAt": iso} for r in reviewers]
    }
    node["comments"] = {"nodes": []}
    node["closingIssuesReferences"] = {"nodes": []}
    return node


@pytest.mark.db
@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB is not reachable")
def test_reviewers_and_experts_on_fixture_graph(monkeypatch):
    name = f"test_brain_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, graph=name))
    nft = "pkg/proxy/nftables/proxier.go"
    nodes = [
        _pr(1, "alice", [nft], ["proxy-pro"], 1),  # same file as the target
        _pr(2, "bob", [nft], ["proxy-pro"], 2),
        _pr(3, "carol", ["pkg/proxy/ipvs/proxier.go"], ["ipvs-person"], 3),  # same component, other dir
        _pr(4, "dave", ["pkg/kubelet/kubelet.go"], ["kubelet-person"], 4),  # unrelated component
        _pr(5, "erin", [nft], ["future-person"], 20),  # merged after the target was opened: must not count
        _pr(6, "target-author", [nft], [], 10),  # the target (its own reviews are not used)
    ]
    nodes[5].update(createdAt="2026-05-10T00:00:00Z", mergedAt=None, state="OPEN")
    rows = m.Rows()
    for node in nodes:
        m.add_pr(rows, node, "kubernetes/kubernetes", components=load_components(), bots=BOTS, keps=set())
    try:
        pulls.ensure_components()
        pulls.load_rows(rows)
        out = brain.reviewers("kubernetes/kubernetes#6", k=3, fetch_missing=False)
        logins = [s["login"] for s in out["suggestions"]]
        assert logins[0] == "proxy-pro"  # reviewed two PRs on the same file
        assert "future-person" not in logins and "erin" not in logins  # time travel: nothing after as_of
        assert "target-author" not in logins and "kubelet-person" not in logins
        assert out["suggestions"][0]["reasons"] == [
            "worked on 2 earlier PR(s) in kube-proxy",
            "2 of them touched the same files",
        ]

        e = brain.experts(topic="kube-proxy", k=5, as_of=pulls.mapping.epoch("2026-05-30T00:00:00Z"))
        assert e["component"] == "kube-proxy"
        assert e["experts"][0]["login"] == "proxy-pro"  # approved both same-file PRs
        assert "kubelet-person" not in [x["login"] for x in e["experts"]]
    finally:
        db.graph().delete()
