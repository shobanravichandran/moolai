import dataclasses
import uuid
from pathlib import Path

import pytest

from moolai import db
from moolai.ingest import keps as k
from tests.test_schema import _falkordb_up

KEP_3866 = """\
title: Add an nftables-based kube-proxy backend
kep-number: 3866
authors:
  - "@danwinship"
owning-sig: sig-network
participating-sigs:
  - SIG Node
  - tbd
status: implementable # provisional|implementable|implemented
creation-date: 2023-02-01
reviewers: ["@thockin", "Dan Williams (@dcbw)"]
approvers: ["@thockin"]
see-also:
  - "/keps/sig-network/2221-old-thing"
  - "https://docs.google.com/document/d/abc"
stage: "beta"
latest-milestone: "v1.31"
"""

README_3866 = """\
# KEP-3866: Add an nftables-based kube-proxy backend

<!-- toc -->
- [Summary](#summary)
<!-- /toc -->

## Summary

The default kube-proxy implementation on Linux is based on iptables.

## Motivation

### The iptables kernel subsystem has unfixable performance problems

```
iptables -A FOO
```

Rule updates are O(n).

## Design Details

### Alternatives Considered

Continue to improve the `iptables` mode.

## Implementation History
"""


def _kep(root: Path, sig: str, name: str, meta: str, readme: str = "## Summary\n\nx\n") -> Path:
    d = root / sig / name
    d.mkdir(parents=True)
    (d / "kep.yaml").write_text(meta, encoding="utf-8")
    (d / "README.md").write_text(readme, encoding="utf-8")
    return d


@pytest.fixture
def keps_root(tmp_path: Path) -> Path:
    root = tmp_path / "keps"
    _kep(root, "sig-network", "3866-nftables-proxy", KEP_3866, README_3866)
    old = "title: Old thing\nkep-number: 2221\nowning-sig: sig-network\nstatus: implemented\n"
    _kep(root, "sig-network", "2221-old-thing", old + "creation-date: 2019-13-01\nauthors: ['@a']\n")
    # A KEP that moved SIGs and left its old dir behind under the same number.
    moved = "title: Out-of-Tree\nkep-number: 2133\nowning-sig: sig-cloud-provider\nauthors: ['@b']\n"
    _kep(
        root, "sig-cloud-provider", "2133-out-of-tree", moved + "status: replaced # by keps/sig-node/2133-x\n"
    )
    live = "title: Kubelet Credential Providers\nkep-number: 2133\nowning-sig: sig-node\nauthors: ['@b']\n"
    _kep(root, "sig-node", "2133-kubelet-credential-providers", live + "status: implemented\n")
    prr = root / "prod-readiness" / "sig-network"
    prr.mkdir(parents=True)
    (prr / "3866.yaml").write_text('kep-number: 3866\nalpha:\n  approver: "@wojtek-t"\n', encoding="utf-8")
    return root


def test_normalizers():
    assert k.norm_status("implementable # provisional|implementable") == "implementable"
    assert k.norm_status("imlpemented") == "implemented"
    assert k.norm_status("provisional|implementable|implemented") == "unknown"
    assert k.norm_stage('"alpha" # alpha|beta|stable') == "alpha"
    assert k.norm_team("SIG Network") == "sig-network"
    assert k.norm_team("sig-apimachinery") == "sig-api-machinery"
    assert k.norm_team("TBD") is None


def test_logins_and_refs():
    assert k.logins(["@DanWinship", "Dan Williams (@dcbw)", "aojea", "Some Person", "@danwinship"]) == [
        "danwinship",
        "dcbw",
        "aojea",
    ]
    assert k.kep_refs(
        [
            "/keps/sig-node/4381-dra",
            "https://github.com/kubernetes/enhancements/issues/12",
            "n/a",
            "KEP-7",
            "https://github.com/kubernetes/kubernetes/issues/99",
        ]  # fmt: skip
    ) == [4381, 12, 7]


def test_epoch_tolerates_bad_dates():
    assert k.epoch("2023-02-01") == 1675209600
    assert k.epoch("2019-13-01") is None
    assert k.epoch(None) is None


def test_readme_sections():
    s = k.readme_sections(README_3866)
    assert s["summary"] == "The default kube-proxy implementation on Linux is based on iptables."
    assert "O(n)" in s["motivation"] and "iptables -A" not in s["motivation"]  # code blocks dropped
    assert s["alternatives"] == "Continue to improve the `iptables` mode."


def test_parse_kep(keps_root: Path):
    kep = k.parse_kep(keps_root / "sig-network" / "3866-nftables-proxy", keps_root)
    assert kep.id == "KEP-3866"
    assert (kep.status, kep.stage, kep.owning_team) == ("implementable", "beta", "sig-network")
    assert kep.participating_teams == ["sig-node"]
    assert kep.reviewers == ["thockin", "dcbw"]
    assert kep.prr_approvers == ["wojtek-t"]
    assert kep.see_also == [2221]
    assert kep.dir == "keps/sig-network/3866-nftables-proxy"


def test_dedupe_keeps_live_kep_as_canonical(keps_root: Path):
    parsed = k.dedupe([k.parse_kep(d, keps_root) for d in k.kep_dirs(keps_root)])
    ids = sorted(p.id for p in parsed)
    assert ids == ["KEP-2133", "KEP-2133@sig-cloud-provider", "KEP-2221", "KEP-3866"]


@pytest.mark.db
@pytest.mark.skipif(not _falkordb_up(), reason="FalkorDB is not reachable")
def test_load_and_trace(keps_root: Path, monkeypatch):
    name = f"test_keps_{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(db, "settings", dataclasses.replace(db.settings, graph=name))
    parsed = k.dedupe([k.parse_kep(d, keps_root) for d in k.kep_dirs(keps_root)])
    try:
        k.load(parsed)
        counts = db.graph().ro_query("MATCH (n) RETURN count(n)").result_set
        k.load(parsed)  # idempotent
        assert db.graph().ro_query("MATCH (n) RETURN count(n)").result_set == counts

        t = db.run("decision_trace", {"id": "KEP-3866"}, read_only=True)[0]
        # Every list must be filled: guards the FalkorDB comprehension-variable gotcha (see the query file).
        assert t["authors"] == ["danwinship"]
        assert sorted(t["reviewers"]) == ["dcbw", "thockin"]
        approvers = sorted((a["login"], a["kind"]) for a in t["approvers"])
        assert approvers == [("thockin", "sig"), ("wojtek-t", "prr")]
        assert t["involves"] == ["sig-node"]
        assert [x["id"] for x in t["see_also"]] == ["KEP-2221"]
        assert t["discussed_in"][0]["url"] == "https://github.com/kubernetes/enhancements/issues/3866"

        old = db.run("decision_trace", {"id": "KEP-2133@sig-cloud-provider"}, read_only=True)[0]
        assert [x["id"] for x in old["replaced_by"]] == ["KEP-2133"]
        assert not db.graph().ro_query("MATCH (t:Team {id: 'tbd'}) RETURN t").result_set
    finally:
        db.graph().delete()
