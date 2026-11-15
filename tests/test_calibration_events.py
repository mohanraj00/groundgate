"""Calibration events of an outside approver (SPEC §4.19, #642): the vectors in
``conformance/events/``, the events log of the store and ``calibrate events``. The expectations
are written by hand."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from groundgate.calibrate import audit, events
from groundgate.calibrate.cli import main
from groundgate.canonical import jcs
from groundgate.profile import check_profile
from groundgate.store import FolderStore
from groundgate.store.export import admitted_facts
from groundgate.store.maintain import check
from groundgate.store.packets import admit_packet, load_packet

ROOT = Path(__file__).parent.parent / "conformance" / "events"
VECTORS = [json.loads(p.read_text("utf-8")) for p in sorted(ROOT.glob("*.json"))]
FIXTURE = Path(__file__).parent / "fixtures" / "approver"
PROFILE = json.loads((FIXTURE / "profile.json").read_text("utf-8"))
TEXT = (FIXTURE / "invoice.txt").read_text("utf-8")
DIGEST = "sha256:982dd1d45fbd207c9e35803016652bbc56cc0c0d9fd5918ef7d794c1e6e1b18e"
PACKET = "sha256:cd6842292fea8fc33b6d67004b5eda3a24a8d195e6e02f9d58e35f21f819ee07"


def of(kind: str) -> list[Any]:
    return [pytest.param(v, id=v["name"]) for v in VECTORS if v["kind"] == kind]


@pytest.mark.parametrize("v", of("event"))
def test_event_vector(v: dict[str, Any]) -> None:
    if v["expected"]["valid"]:
        assert events.check_event(v["event"]) == v["event"]
    else:
        with pytest.raises(events.EventError):
            events.check_event(v["event"])


@pytest.mark.parametrize("v", of("log"))
def test_log_vector(v: dict[str, Any]) -> None:
    if v["expected"]["valid"]:
        got = events.counted(v["profile"], v["records"])
        assert [e["origin"]["id"] for e in got] == v["expected"]["counted"]
    else:
        with pytest.raises(events.EventError):
            events.counted(v["profile"], v["records"])


def test_each_kind_has_a_vector() -> None:
    assert {v["kind"] for v in VECTORS} == {"event", "log"}
    assert any(v["expected"]["valid"] for v in VECTORS)
    assert any(not v["expected"]["valid"] for v in VECTORS)


def test_an_event_is_not_an_audit_label() -> None:
    (v,) = [v for v in VECTORS if v["name"] == "event-03-correct"]
    with pytest.raises(audit.AuditError):
        audit.check_label(v["event"])


def test_the_measure_and_the_audit_never_read_events() -> None:
    """An event never enters a bound: the measure and the audit do not know the events."""
    for name in ("measure.py", "audit.py"):
        source = Path(audit.__file__).with_name(name).read_text("utf-8")
        assert "events" not in source and "calibration_event" not in source, name


# ------------------------------------------------------------------ the approver fixture


def _ev(quote: str) -> dict[str, Any]:
    start = TEXT.encode().index(quote.encode())
    return {"start": start, "end": start + len(quote.encode()), "text": quote}


CANDIDATES = [
    {"id": "total", "field": "total", "value": "90", "unit": "USD", "evidence": _ev("$90.00")},
    {"id": "tax", "field": "tax", "value": "8", "unit": "USD", "evidence": _ev("$8.00")},
    {"id": "shipping", "field": "shipping", "value": "12", "unit": "USD",
     "evidence": _ev("$12.00")},
]  # fmt: skip


def _store(root: Path) -> None:
    """The store of the fixture: the packet of the invoice, decided with the terms of the
    profile."""
    with FolderStore(root) as store:
        found = admit_packet(store, TEXT, PROFILE["schema"], CANDIDATES, document_id="inv-0007")
        assert found[0] == PACKET


def test_the_fixture_names_the_facts_of_the_packet(tmp_path: Path) -> None:
    """Each event of the fixture names a fact of the export of the packet, by its digest."""
    _store(tmp_path / "s")
    found = events.read_file(FIXTURE / "events.jsonl")
    assert [e["decision"] for e in found] == ["approve", "reject", "correct"]
    with FolderStore(tmp_path / "s") as store:
        facts = admitted_facts(store, load_packet(store, PACKET))["facts"]
    by_field = {f["field"]: f for f in facts}
    for e in found:
        fact = by_field[e["field"]]
        assert e["profile"] == DIGEST and e["packet_sha256"] == PACKET
        assert e["fact_sha256"] == events.fact_sha256(fact)
        assert e["receipt_sha256"] == fact["citation"]["receipt_sha256"]
        assert e["value"] == fact["value"]


WANT_DRAFTS = {
    "groundgate_profile_drafts": 1,
    "profile": {"id": "invoice-x-test", "version": "1.0.0", "sha256": DIGEST},
    "events": 3,
    "drafts": [
        {"draft": "review_share", "field": "shipping", "key": None, "approved": 0,
         "rejected": 1, "corrected": 0, "share": "1.00"},
        {"draft": "review_share", "field": "tax", "key": None, "approved": 1, "rejected": 0,
         "corrected": 0, "share": "0.00"},
        {"draft": "review_share", "field": "total", "key": None, "approved": 0, "rejected": 0,
         "corrected": 1, "share": "1.00"},
        {"draft": "value_test", "field": "shipping", "key": None, "packet": PACKET,
         "refuse": "12", "admit": None, "origin": {"system": "approvals", "id": "d-0002"}},
        {"draft": "value_test", "field": "total", "key": None, "packet": PACKET,
         "refuse": "90", "admit": "95", "origin": {"system": "approvals", "id": "d-0003"}},
        {"draft": "term", "field": "total", "alias": "Amount due after fees", "packet": PACKET,
         "line": 3, "origin": {"system": "approvals", "id": "d-0003"}},
    ],
    "missing_packets": [],
}  # fmt: skip


def test_the_events_steps(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    _store(root)
    (tmp_path / "profile.json").write_text(json.dumps(PROFILE), "utf-8")
    add = ["events", "add", "--store", str(root), "--events", str(FIXTURE / "events.jsonl")]
    main(add)
    assert capsys.readouterr().out == "added 3 events; 0 copies were not added\n"
    main(add)  # the same file again: each event is a copy
    assert capsys.readouterr().out == "added 0 events; 3 copies were not added\n"
    out = tmp_path / "drafts.json"
    suggest = [
        "events",
        "suggest",
        "--store",
        str(root),
        "--profile",
        str(tmp_path / "profile.json"),
    ]
    main([*suggest, "--out", str(out)])
    assert json.loads(out.read_text("utf-8")) == WANT_DRAFTS
    with pytest.raises(SystemExit, match="exists"):
        main([*suggest, "--out", str(out)])  # never write over a file
    with FolderStore(root) as store:
        records = store.read(("events", DIGEST))
        assert len(records) == 3 and check(store).findings == []
        assert load_packet(store, PACKET).receipt  # suggest changed nothing in the store


def test_suggest_reads_only_the_events_of_its_profile_version(tmp_path: Path) -> None:
    """A new profile version has a new digest, so it starts with no events."""
    root = tmp_path / "s"
    _store(root)
    with FolderStore(root) as store:
        events.add(store, events.read_file(FIXTURE / "events.jsonl"))
        newer = {**PROFILE, "version": "1.0.1"}
        drafts = events.suggest(store, newer)
    assert drafts["events"] == 0 and drafts["drafts"] == []


def test_a_term_needs_one_line_and_words_before_the_value() -> None:
    assert events._term("Total: $90.00\nDue: $95.00\n", "95") == ("Due", 2)
    assert events._term("Due: 95\nAgain 95\n", "95") is None  # two lines
    assert events._term("Due: 1950\n", "95") is None  # not a whole number
    assert events._term("95 due\n", "95") is None  # no words before the value
    assert events._term("Amount (net): 95\n", "95") == ("Amount (net)", 1)
    assert events._term("Due: x\n", " ") is None


def test_a_known_alias_gives_no_term(tmp_path: Path) -> None:
    known = json.loads(json.dumps(PROFILE))
    known["schema"]["fields"]["total"]["aliases"].append("amount due after FEES")
    digest = check_profile(known).sha256
    with FolderStore(tmp_path / "s") as store:
        (found,) = admit_packet(store, TEXT, PROFILE["schema"], CANDIDATES)[:1]
        line = (FIXTURE / "events.jsonl").read_text("utf-8").splitlines()[2]
        event = {**json.loads(line), "profile": digest, "packet_sha256": found}
        events.add(store, [event])
        drafts = events.suggest(store, known)
    assert [d["draft"] for d in drafts["drafts"]] == ["review_share", "value_test"]


def test_a_correction_of_a_missing_packet_gives_no_term(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        events.add(store, events.read_file(FIXTURE / "events.jsonl"))
        drafts = events.suggest(store, PROFILE)
    assert drafts["missing_packets"] == [PACKET]
    assert "term" not in [d["draft"] for d in drafts["drafts"]]
    assert len(drafts["drafts"]) == 5


def test_add_checks_each_event_before_it_writes_one(tmp_path: Path) -> None:
    lines = (FIXTURE / "events.jsonl").read_text("utf-8").splitlines()
    bad = json.loads(lines[2])
    bad["corrected"] = bad["value"]
    path = tmp_path / "events.jsonl"
    path.write_text(lines[0] + "\n" + json.dumps(bad) + "\n", "utf-8")
    with pytest.raises(SystemExit, match="line 2: an event has a member with a wrong form"):
        main(["events", "add", "--store", str(tmp_path / "s"), "--events", str(path)])
    with FolderStore(tmp_path / "s") as store:
        assert store.read(("events", DIGEST)) == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"a": 1}', "no line break"),
        ("[1]\n", "line 1: an event must be an object"),
        ('{"a": 1, "a": 2}\n', "line 1 is not JSON"),
        ("NaN\n", "line 1 is not JSON"),
        ("\n", "line 1 is not JSON"),
    ],
)
def test_a_bad_events_file_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(text, "utf-8")
    with pytest.raises(events.EventError, match=message):
        events.read_file(path)


def test_store_check_finds_a_bad_events_log(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        events.add(store, events.read_file(FIXTURE / "events.jsonl"))
        other = "sha256:" + "a" * 64
        store.append(("events", other), json.loads(jcs(events.read_file(
            FIXTURE / "events.jsonl")[0])))  # fmt: skip
        found = check(store).findings
    assert len(found) == 1 and "record 1 is of another profile" in found[0]
    with FolderStore(tmp_path / "s") as store, pytest.raises(events.EventError):
        events.read_events(store, other)
