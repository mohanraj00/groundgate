"""The member list of the 1.0 release set (#748)."""

from __future__ import annotations

import importlib.util
import json
from collections import Counter
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SET = ROOT / "bench" / "release1"


def select() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release1_select", SET / "select.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_member_list_comes_from_metadata_only() -> None:
    body = json.loads((SET / "members.json").read_text())
    assert body["body_read"] is False
    assert body["download_approved"] is None
    assert not (SET / "manifest.json").exists()
    opinions = body["kinds"]["opinions"]["members"]
    reports = body["kinds"]["reports"]["members"]
    assert len(opinions) == len(reports) == 30
    ids = [m["package"] for m in opinions + reports]
    assert len(set(ids)) == 60
    for m in opinions:
        assert m["court_type"] == "Appellate" and m["granules"] == 1
        assert 6 <= m["pages"] <= 60 and m["date_issued"].startswith("2025")
    assert max(Counter(m["court"] for m in opinions).values()) <= 3
    assert Counter(m["doc_class"] for m in reports) == {"HRPT": 15, "SRPT": 15}
    for m in reports:
        assert m["bill"] and m["committee"] not in ("hsru00", "ssra00")
        assert 8 <= m["pages"] <= 150
    rejected = body["kinds"]["opinions"]["rejected"] + body["kinds"]["reports"]["rejected"]
    assert not {r["package"] for r in rejected} & set(ids)


def test_a_document_in_two_packages_is_one_member() -> None:
    twins = select().Twins()
    first = {"court": "ca2", "entry": "3646899", "title": "In Re: A", "date_issued": "2025-08-05"}
    twins.add("USCOURTS-ca2-22-02166", {**first, "pages": 51})
    other_docket = {**first, "title": "In Re: B", "pages": 50}
    assert twins.problem(other_docket) == "the same document as USCOURTS-ca2-22-02166"
    same_text = {**first, "court": "ca3", "entry": "", "title": "IN RE: A", "pages": 51}
    assert twins.problem(same_text) == "the same document as USCOURTS-ca2-22-02166"
    assert twins.problem({**first, "court": "ca3", "pages": 51, "title": "In Re: C"}) is None
    report = {"title": "A BILL", "date_issued": "2025-06-10", "pages": 12}
    twins.add("CRPT-119hrpt1", report)
    assert twins.problem({**report}) == "the same document as CRPT-119hrpt1"
    assert twins.problem({**report, "pages": 13}) is None


def test_the_members_have_no_twins_and_the_set_does_not_exclude_itself() -> None:
    body = json.loads((SET / "members.json").read_text())
    mod = select()
    twins = mod.Twins()
    for kind in ("opinions", "reports"):
        for m in body["kinds"][kind]["members"]:
            assert twins.problem(m) is None, m["package"]
            twins.add(m["package"], m)
    names = mod.named_in_bench()
    assert not names & {m["package"] for k in body["kinds"].values() for m in k["members"]}
