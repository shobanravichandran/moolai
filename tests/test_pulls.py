import dataclasses
import gzip
import json
import uuid
from pathlib import Path

import pytest

from moolai import db
from moolai.components import load_components
from moolai.ingest import keps as k
from moolai.ingest import mapping as m
from moolai.ingest import pulls
from tests.test_keps import keps_root  # noqa: F401  (fixture)
from tests.test_schema import _falkordb_up

BOTS = ["k8s-ci-robot", "*[bot]"]


def _actor(login, typename="User"):
    return {"login": login, "__typename": typename}


def _comment(i, login, body, at="2026-05-02T10:00:00Z", typename="User"):
    return {"id": f"IC_{i}", "author": _actor(login, typename), "body": body, "createdAt": at,
            "url": f"https://github.com/kubernetes/kubernetes/pull/130001#issuecomment-{i}"}  # fmt: skip


PR_NODE = {
    "number": 130001,
    "title": "kube-proxy: nftables: fix NodePort handling",
    "body": "#### What type of PR is this?\n/kind bug\n\nFixes #129999\n\n"
    "Additional documentation:\n- [KEP]: https://github.com/kubernetes/enhancements/issues/3866\n",
    "url": "https://github.com/kubernetes/kubernetes/pull/130001",
    "state": "MERGED",
    "isDraft": False,
    "createdAt": "2026-05-01T09:00:00Z",
    "updatedAt": "2026-05-03T09:00:00Z",
    "mergedAt": "2026-05-03T08:00:00Z",
    "closedAt": "2026-05-03T08:00:00Z",
    "additions": 40,
    "deletions": 7,
    "author": _actor("DanWinship"),
    "labels": {"nodes": [{"name": "sig/network"}, {"name": "kind/bug"}, {"name": "lgtm"}]},
    "files": {
        "totalCount": 4,
        "nodes": [
            {"path": "pkg/proxy/nftables/proxier.go", "additions": 30, "deletions": 5},
            {"path": "staging/src/k8s.io/apiserver/pkg/authentication/x.go", "additions": 5, "deletions": 1},
            {"path": "vendor/github.com/foo/bar.go", "additions": 5, "deletions": 1},
            {"path": "pkg/volume/util/util.go", "additions": 0, "deletions": 0},
        ],
    },
    "reviews": {
        "nodes": [
            {"author": _actor("aojea"), "state": "COMMENTED", "submittedAt": "2026-05-01T12:00:00Z"},
            {"author": _actor("danwinship"), "state": "COMMENTED", "submittedAt": "2026-05-01T13:00:00Z"},
            {
                "author": _actor("copilot-pull-request-reviewer", "Bot"),
                "state": "COMMENTED",
                "submittedAt": None,
            },
        ]
    },
    "comments": {
        "nodes": [
            _comment(1, "aojea", "/lgtm\nthanks", "2026-05-02T10:00:00Z"),
            _comment(2, "thockin", "/approve", "2026-05-02T11:00:00Z"),
            _comment(3, "thockin", "/lgtm cancel\nwait, one more thing", "2026-05-02T11:30:00Z"),
            _comment(4, "danwinship", "/lgtm", "2026-05-02T12:00:00Z"),  # author: not a review
            _comment(5, "k8s-ci-robot", "LGTM label has been added.", typename="Bot"),
        ]
    },
    "closingIssuesReferences": {
        "nodes": [
            {
                "number": 129999,
                "title": "NodePort broken with nftables",
                "state": "CLOSED",
                "url": "https://github.com/kubernetes/kubernetes/issues/129999",
                "repository": {"nameWithOwner": "kubernetes/kubernetes"},
            }  # fmt: skip
        ]
    },
}

TRACKING_NODE = {
    "number": 3866,
    "title": "Add an nftables-based kube-proxy backend",
    "body": "Enhancement Description\n- KEP: keps/sig-network/3866-nftables-proxy",
    "url": "https://github.com/kubernetes/enhancements/issues/3866",
    "state": "CLOSED",
    "createdAt": "2023-02-01T00:00:00Z",
    "updatedAt": "2026-05-04T00:00:00Z",
    "closedAt": "2025-04-23T00:00:00Z",
    "author": _actor("danwinship"),
    "labels": {"nodes": [{"name": "sig/network"}, {"name": "stage/stable"}]},
    "first": {
        "nodes": [
            _comment(
                10,
                "release-team-person",
                "PRs: kubernetes/kubernetes#121046, https://github.com/kubernetes/kubernetes/pull/130001",
            )
        ]
    },  # fmt: skip
    "last": {
        "nodes": [
            _comment(10, "release-team-person", "dup of first page"),
            _comment(11, "k8s-triage-robot", "kubernetes/kubernetes#1 stale", typename="Bot"),
        ]
    },  # fmt: skip
}


def test_prow_commands():
    assert m.prow_commands("/lgtm") == ["LGTM"]
    assert m.prow_commands("looks good\n/approve no-issue") == ["APPROVED"]
    assert m.prow_commands("/lgtm\n/approve") == ["LGTM", "APPROVED"]
    assert m.prow_commands("/lgtm cancel") == []
    assert m.prow_commands("I will /lgtm later") == []  # commands must start a line


def test_refs():
    assert m.kep_numbers_in(
        "KEP-3866, kubernetes/enhancements#2221, keps/sig-node/9999-x, KEP 42", {3866, 2221, 42}
    ) == [
        3866,
        2221,
        42,
    ]
    assert m.kk_pr_numbers_in(
        "kubernetes/kubernetes#5 and https://github.com/kubernetes/kubernetes/pull/6"
    ) == [5, 6]
    assert m.kk_pr_numbers_in("https://github.com/kubernetes/kubernetes/issues/7") == []  # issues aren't PRs


def test_actor_and_labels():
    assert m.actor(_actor("K8s-CI-Robot"), BOTS) == ("k8s-ci-robot", True)
    assert m.actor(_actor("dependabot[bot]"), BOTS) == ("dependabot[bot]", True)
    assert m.actor(_actor("someone", "Bot"), BOTS) == ("someone", True)
    assert m.actor(None, BOTS) is None
    assert not m.is_bot_login("liggitt", BOTS)  # fnmatch('*[bot]') would have flagged this
    assert m.team_from_label("sig/api-machinery") == "sig-api-machinery"
    assert m.team_from_label("kind/bug") is None


def test_components():
    c = load_components()
    assert c.resolve("staging/src/k8s.io/apiserver/pkg/authentication/x.go").id == "auth"  # beats apiserver
    assert c.resolve("staging/src/k8s.io/apiserver/pkg/server/x.go").id == "apiserver"
    assert c.resolve("pkg/kubelet/cm/dra/manager.go").id == "dra"  # beats kubelet
    assert c.resolve("pkg/volume/util/util.go").id == "dir:pkg/volume"
    assert c.resolve("staging/src/k8s.io/client-go/rest/x.go").id == "dir:staging/src/k8s.io/client-go"
    assert c.resolve("go.mod").id == "dir:(root)"
    assert c.skipped("vendor/x/y.go") and c.skipped("pkg/apis/core/v1/zz_generated.conversion.go")
    assert c.skipped("staging/src/k8s.io/api/core/v1/generated.pb.go")
    assert not c.skipped("pkg/proxy/nftables/proxier.go")


def test_add_pr():
    rows = m.Rows()
    m.add_pr(rows, PR_NODE, "kubernetes/kubernetes", components=load_components(), bots=BOTS, keps={3866})
    pr = rows.prs[0]
    assert pr["id"] == "kubernetes/kubernetes#130001" and pr["author"] == "danwinship"
    assert pr["props"]["state"] == "merged" and pr["props"]["merged_at"] == 1777795200
    assert [f["component"] for f in rows.files] == ["kube-proxy", "auth", "dir:pkg/volume"]  # vendor skipped
    assert rows.skipped_files == 1
    reviews = {r["login"]: (r["state"], r["via"]) for r in rows.reviews}
    # aojea: GitHub COMMENTED + Prow /lgtm -> LGTM via both.
    # thockin: /approve (the later '/lgtm cancel' cancels only lgtm).
    # The author's own /lgtm and review, and bots, are not reviews.
    assert reviews == {"aojea": ("LGTM", "both"), "thockin": ("APPROVED", "prow")}
    assert rows.teams == [{"pr": "kubernetes/kubernetes#130001", "team": "sig-network"}]
    assert rows.fixes[0]["issue"] == "kubernetes/kubernetes#129999"
    assert [(i["decision"], i["via"]) for i in rows.implements] == [("KEP-3866", "pr_body")]
    assert {c["id"] for c in rows.comments} == {"IC_1", "IC_2", "IC_3", "IC_4"}  # bot comment dropped
    assert rows.people["copilot-pull-request-reviewer"] is True


def test_add_tracking_issue():
    rows = m.Rows()
    linked = m.add_tracking_issue(rows, TRACKING_NODE, "kubernetes/enhancements", 3866, bots=BOTS)
    assert linked == [121046, 130001]
    assert rows.issues[0]["props"]["kind"] == "kep-tracking"
    assert [c["id"] for c in rows.comments] == ["IC_10"]  # deduped across first/last, bot dropped
    assert {(i["pr"], i["via"]) for i in rows.implements} == {
        ("kubernetes/kubernetes#121046", "tracking_issue"),
        ("kubernetes/kubernetes#130001", "tracking_issue"),
    }


@pytest.mark.db
@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB is not reachable")
def test_offline_replay_end_to_end(keps_root: Path, tmp_path: Path, monkeypatch):  # noqa: F811
    name = f"test_pulls_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, graph=name))
    cache = tmp_path / "cache"
    cache.mkdir()
    responses = [
        {"data": {"search": {"issueCount": 1, "pageInfo": {"hasNextPage": False}, "nodes": [PR_NODE]}}},
        {"data": {"repository": {"n3866": TRACKING_NODE}}},
        # An older copy of the same PR: replay must keep the newest one.
        {"data": {"search": {"nodes": [{**PR_NODE, "title": "OLD", "updatedAt": "2026-05-01T00:00:00Z"}]}}},
    ]
    for i, body in enumerate(responses):
        (cache / f"{i}.json.gz").write_bytes(gzip.compress(json.dumps(body).encode()))
    monkeypatch.setattr(pulls, "CACHE_DIR", cache)
    try:
        k.load(k.dedupe([k.parse_kep(d, keps_root) for d in k.kep_dirs(keps_root)]))
        out = pulls.sync(offline=True)["offline_replay"]
        assert out["prs"] == 1 and out["issues"] == 1 and out["reviews"] == 2
        counts = db.graph().ro_query("MATCH (n) RETURN count(n)").result_set
        pulls.sync(offline=True)  # idempotent
        assert db.graph().ro_query("MATCH (n) RETURN count(n)").result_set == counts

        g = db.graph()
        t = db.run("decision_trace", {"id": "KEP-3866"}, read_only=True)[0]
        impl = {p["id"]: p for p in t["implemented_by"]}
        assert set(impl) == {"kubernetes/kubernetes#130001", "kubernetes/kubernetes#121046"}
        assert impl["kubernetes/kubernetes#130001"]["title"] == "kube-proxy: nftables: fix NodePort handling"
        assert t["discussed_in"][0]["title"] == "Add an nftables-based kube-proxy backend"  # stub filled

        def one(q):
            return g.ro_query(q).result_set

        assert one(
            "MATCH (:PR {number: 130001})-[:TOUCHES]->(:File)-[:PART_OF]->(c:Component)"
            "-[:OWNED_BY]->(t:Team) "
            "RETURN c.id, t.id ORDER BY c.id"
        ) == [["auth", "sig-auth"], ["kube-proxy", "sig-network"]]
        assert one(
            "MATCH (p:Person)-[r:REVIEWED]->(:PR {number: 130001}) "
            "RETURN p.login, r.state, r.via ORDER BY p.login"
        ) == [["aojea", "LGTM", "both"], ["thockin", "APPROVED", "prow"]]
        assert one("MATCH (:PR {number: 130001})-[:FIXES]->(i:Issue) RETURN i.id") == [
            ["kubernetes/kubernetes#129999"]
        ]
        assert one("MATCH (:PR {number: 130001})-[:TAGGED]->(t:Team) RETURN t.id") == [["sig-network"]]
        assert one("MATCH (p:Person {login: 'danwinship'})-[:AUTHORED]->(pr:PR) RETURN pr.number") == [
            [130001]
        ]
        assert one("MATCH (pr:PR {number: 121046}) RETURN pr.fetched") == [[False]]  # stub, awaiting backfill
        # Bots are kept as flagged people (so rankings can exclude them), but their comments aren't stored.
        assert one("MATCH (p:Person {login: 'k8s-ci-robot'}) RETURN p.is_bot") == [[True]]
        assert one("MATCH (:Person {login: 'k8s-ci-robot'})-[:AUTHORED]->(c) RETURN count(c)") == [[0]]
    finally:
        db.graph().delete()
