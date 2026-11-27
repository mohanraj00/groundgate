"""Calibration events of an outside approver (SPEC §4.19, #642): the vectors in
``conformance/events/``, the events log of the store and ``calibrate events``. The expectations
are written by hand."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from groundgate.calibrate import audit, events
from groundgate.calibrate.cli import main
from groundgate.canonical import jcs
from groundgate.profile import check_profile
from groundgate.store import FolderStore
from groundgate.store.export import admitted_facts
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import admit_packet, load_packet

ROOT = Path(__file__).parent.parent / "conformance" / "events"
VECTORS = [json.loads(p.read_text("utf-8")) for p in sorted(ROOT.glob("*.json"))]
FIXTURE = Path(__file__).parent / "fixtures" / "approver"
PROFILE = json.loads((FIXTURE / "profile.json").read_text("utf-8"))
TEXT = (FIXTURE / "invoice.txt").read_text("utf-8")
DIGEST = "sha256:bee5f0692ae4083b4553985b398dd59dfacda812840598064e86dd97db08c54a"
PACKET = "sha256:3da8b3fec5cafbec116431a29b9a141cfeb41ee633d68d692a827f40f7072952"
ENTELOS_HOST = "github.com/mohanraj00/entelos/src/lifecycle-core"


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
    "unscanned_corrections": 0,
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


def _entelos_events(
    checkout: Path, work: Path, facts: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    module = work / "entelos-seam"
    shutil.copytree(Path(__file__).with_name("entelos-seam"), module)
    lifecycle = checkout.resolve() / "src" / "lifecycle-core"
    assert (lifecycle / "go.mod").is_file(), "Set GROUNDGATE_ENTELOS to the release checkout."
    go_env = {**os.environ, "GOWORK": "off"}
    subprocess.run(
        ["go", "mod", "edit", "-replace", f"{ENTELOS_HOST}={lifecycle}"],
        cwd=module,
        env=go_env,
        check=True,
        timeout=30,
    )
    cited = []
    for (fact_digest, receipt_digest), fact in facts.items():
        citation = fact["citation"]
        cited.append({
            "fact_id": fact["field"], "decision_digest": fact_digest,
            "receipt_digest": receipt_digest, "packet_digest": PACKET,
            "source_kind": citation["source"], "source_digest": citation["source_sha256"],
            "text_digest": citation["text_sha256"],
            "spans": [{key: citation["span"][key] for key in ("start", "end")}],
            "outcome": "admitted", "codes": [],
            "data": {key: fact[key] for key in ("field", "key", "value", "unit")},
        })  # fmt: skip
    evidence = work / "evidence.json"
    evidence.write_text(jcs({
        "format": "entelos.evidence/1",
        "producer": {"id": "groundgate", "version": "1", "digest_scheme": "groundgate/facts@1"},
        "facts": cited,
    }), "utf-8")  # fmt: skip
    output = work / "decisions.jsonl"
    subprocess.run(
        ["go", "run", ".", "-evidence", str(evidence), "-out", str(output)],
        cwd=module,
        env=go_env,
        check=True,
        timeout=120,
    )
    return [json.loads(line) for line in output.read_text("utf-8").splitlines()]


def test_entelos_decision_events(tmp_path: Path) -> None:
    checkout = os.environ.get("GROUNDGATE_ENTELOS")
    if not checkout:
        pytest.skip("Set GROUNDGATE_ENTELOS to a checkout of entelos v0.7.0.")
    root = tmp_path / "store"
    _store(root)
    with FolderStore(root) as store:
        export = admitted_facts(store, load_packet(store, PACKET))
    by_field = {fact["field"]: fact for fact in export["facts"]}
    facts = {
        (events.fact_sha256(fact), fact["citation"]["receipt_sha256"]): fact
        for fact in (by_field["tax"], by_field["shipping"], by_field["total"])
    }
    decisions = _entelos_events(Path(checkout), tmp_path, facts)
    assert [e["disposition"] for e in decisions] == ["approve", "reject", "correct"]
    assert len({e["decision_ref"] for e in decisions}) == 3

    profile = check_profile(PROFILE)
    records = []
    for e in decisions:
        assert e["format"] == "entelos.decision-event/1" and e["blind"] is False
        fact = facts[e["fact_digest"], e["evidence_receipt_digest"]]
        records.append(events.check_event({
            "groundgate_calibration_event": 1, "decision": e["disposition"],
            "profile": profile.sha256, "packet_sha256": export["packet_sha256"],
            "receipt_sha256": e["evidence_receipt_digest"], "fact_sha256": e["fact_digest"],
            "field": fact["field"], "key": fact["key"], "value": fact["value"],
            "corrected": e.get("corrected_value"),
            "actor": {"human": "person", "model": "program", "policy": "program"}[e["actor_kind"]],
            "origin": {"system": "entelos", "id": e["decision_ref"]}, "date": None,
        }))  # fmt: skip

    expected = events.read_file(FIXTURE / "events.jsonl")
    origins = {
        want["origin"]["id"]: {"system": "entelos", "id": e["decision_ref"]}
        for want, e in zip(expected, decisions, strict=True)
    }
    assert records == [
        {**want, "origin": origins[want["origin"]["id"]], "date": None} for want in expected
    ]
    input_file = tmp_path / "calibration.jsonl"
    input_file.write_text("".join(jcs(record) + "\n" for record in records), "utf-8")
    first, replay = tmp_path / "first.json", tmp_path / "replay.json"
    add = ["events", "add", "--store", str(root), "--events", str(input_file)]
    profile_file = FIXTURE / "profile.json"
    suggest = ["events", "suggest", "--store", str(root), "--profile", str(profile_file)]
    main(add)
    main([*suggest, "--out", str(first)])
    main(add)
    main([*suggest, "--out", str(replay)])

    with FolderStore(root) as store:
        assert len(store.read(("events", profile.sha256))) == 3
        assert events.read_events(store, profile.sha256) == records
    assert first.read_bytes() == replay.read_bytes()
    assert json.loads(first.read_bytes()) == {
        **WANT_DRAFTS,
        "drafts": [
            {**draft, "origin": origins[draft["origin"]["id"]]} if "origin" in draft else draft
            for draft in WANT_DRAFTS["drafts"]
        ],
    }


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


@pytest.mark.parametrize(
    ("line", "value", "want"),
    [
        ("xa!a!a!a!", "a!a!", 5),
        ("a---", "---", -1),
        ("²a a", "a", 3),
        ("a\u0301a", "a", 0),
        ("aa_a_", "a", 3),
        ("a--a", "", 2),
        ("a-a", "", -1),
        ("", "", 0),
    ],
)
def test_found_checks_both_neighbors_of_literal_matches(line: str, value: str, want: int) -> None:
    assert events._found(line, value) == want


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


def test_forget_all_removes_the_events_of_the_packet(tmp_path: Path) -> None:
    """An event holds a value of the document, so ``forget --all`` removes it. The events of
    another packet stay in the log, as a new chain (#684)."""
    root = tmp_path / "s"
    _store(root)
    found = events.read_file(FIXTURE / "events.jsonl")
    other = {**found[0], "packet_sha256": "sha256:" + "b" * 64,
             "origin": {"system": "approvals", "id": "d-0009"}}  # fmt: skip
    with FolderStore(root) as store:
        events.add(store, [found[0], other, *found[1:]])
    with FolderStore(root) as store:
        done = forget_packet(store, PACKET, "the owner asked", everything=True)
    rel = f"logs/events/{DIGEST.removeprefix('sha256:')}.jsonl"
    assert ("events", rel, "deleted", 0) in done
    assert ("packet@1", PACKET, "deleted", 0) in done
    with FolderStore(root) as store:
        assert events.read_events(store, DIGEST) == [other]
        assert events.suggest(store, PROFILE)["drafts"][-1]["draft"] == "review_share"
        (entry,) = [e for e in store.read(("deleted",)) if e.get("log") == ["events", DIGEST]]
        assert entry["records"] == 3 and entry["reason"] == "the owner asked"
        assert check(store).findings == []
    with FolderStore(root) as store:  # a second call finds no event of the packet
        assert store.forget_records(("events", DIGEST), "again", lambda r: False) == 0


def test_forget_all_keeps_the_packet_if_an_events_log_cannot_be_read(tmp_path: Path) -> None:
    root = tmp_path / "s"
    _store(root)
    with FolderStore(root) as store:
        events.add(store, events.read_file(FIXTURE / "events.jsonl"))
    path = root / "logs" / "events" / f"{DIGEST.removeprefix('sha256:')}.jsonl"
    path.write_bytes(path.read_bytes()[:-1])  # a torn last line
    with FolderStore(root) as store:
        done = forget_packet(store, PACKET, "the owner asked", everything=True)
    assert ("packet@1", PACKET, "kept", 0) in done
    assert any(kind == "log" and state == "unchecked" for kind, _, state, _ in done)


def test_forget_records_changes_a_splits_or_events_log_only(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        for log in [("deleted",), ("answers", PACKET, DIGEST)]:
            with pytest.raises(ValueError, match="splits log or an events log"):
                store.forget_records(log, "x", lambda r: True)
        with pytest.raises(ValueError, match="reason"):
            store.forget_records(("events", DIGEST), "", lambda r: True)
        assert store.forget_records(("events", DIGEST), "x", lambda r: True) == 0


def test_an_event_with_a_lone_surrogate_is_refused(tmp_path: Path) -> None:
    """A lone surrogate has no UTF-8 form, so ``suggest --out`` could not write it (#684)."""
    line = (FIXTURE / "events.jsonl").read_text("utf-8").splitlines()[0]
    path = tmp_path / "events.jsonl"
    path.write_text(line.replace('"field": "tax"', '"field": "tax\\ud800"') + "\n", "utf-8")
    assert "\\ud800" in path.read_text("utf-8")
    with pytest.raises(events.EventError, match="line 1: an event has a string with a lone"):
        events.read_file(path)


def test_a_correction_to_null_gives_a_value_test_and_no_term(tmp_path: Path) -> None:
    """A correction can give null as the right value, and the day can be unknown (#684)."""
    root = tmp_path / "s"
    _store(root)
    line = (FIXTURE / "events.jsonl").read_text("utf-8").splitlines()[2]
    event = {**json.loads(line), "corrected": None, "date": None}
    with FolderStore(root) as store:
        events.add(store, [event])
        drafts = events.suggest(store, PROFILE)["drafts"]
    assert [d["draft"] for d in drafts] == ["review_share", "value_test"]
    assert drafts[1]["refuse"] == "90" and drafts[1]["admit"] is None


def test_suggest_scans_each_packet_and_value_once_and_has_a_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many corrections of one packet cannot make suggest scan its text without a bound (#684)."""
    root = tmp_path / "s"
    _store(root)
    line = json.loads((FIXTURE / "events.jsonl").read_text("utf-8").splitlines()[2])
    same = [{**line, "origin": {"system": "approvals", "id": f"s-{n}"}} for n in range(5)]
    other = [{**line, "corrected": str(100 + n), "origin": {"system": "approvals", "id": f"o-{n}"}}
             for n in range(4)]  # fmt: skip
    calls: list[str] = []
    real = events._term

    def counted_term(text: str, value: str) -> tuple[str, int] | None:
        calls.append(value)
        return real(text, value)

    monkeypatch.setattr(events, "_term", counted_term)
    monkeypatch.setattr(events, "MAX_SCANS", 3)
    with FolderStore(root) as store:
        events.add(store, [*same, *other])
        drafts = events.suggest(store, PROFILE)
    assert calls == ["95", "100", "101"]
    assert drafts["unscanned_corrections"] == 2
    assert [d["draft"] for d in drafts["drafts"]].count("term") == 1


def test_calibrate_suggest_bounds_term_scan_characters(tmp_path: Path) -> None:
    root = tmp_path / "s"
    head = "Repeated: "
    tail = "\nFirst label: é\nLast label: " + "é" * 64 + "\nOver limit: " + "é" * 65
    text = head + "é" * ((1 << 20) - len(head) - len(tail)) + tail
    template = events.read_file(FIXTURE / "events.jsonl")[2]
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, text, PROFILE["schema"], [])
        corrections = [
            {
                **template,
                "packet_sha256": packet,
                "corrected": "é" * n,
                "origin": {"system": "approvals", "id": str(n)},
            }
            for n in range(1, 97)
        ]
        cached = {
            **corrections[63],
            "field": "tax",
            "origin": {"system": "approvals", "id": "cached"},
        }
        skipped = {**corrections[64], "origin": {"system": "approvals", "id": "skipped"}}
        events.add(store, [*corrections, cached, skipped])

    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "groundgate.cli",
            "calibrate",
            "events",
            "suggest",
            "--store",
            str(root),
            "--profile",
            str(FIXTURE / "profile.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    drafts = json.loads(run.stdout)
    assert drafts["unscanned_corrections"] == 33
    assert [d["draft"] for d in drafts["drafts"]].count("value_test") == 98
    assert [
        (d["field"], d["alias"], d["line"]) for d in drafts["drafts"] if d["draft"] == "term"
    ] == [
        ("total", "First label", 2),
        ("total", "Last label", 3),
        ("tax", "Last label", 3),
    ]
