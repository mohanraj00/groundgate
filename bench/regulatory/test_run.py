"""Run the claim against synthetic labels and a fake transport."""

from __future__ import annotations

import json
import sys
from itertools import pairwise
from pathlib import Path

import pytest

from groundgate.calibrate.stats import upper_95
from groundgate.read import read

sys.path.insert(0, str(Path(__file__).parents[2]))
from bench.regulatory import run, score
from bench.regulatory.slots import SCHEMA
from bench.requested.run_set import CachedTransportError, CacheError

FEE = "§ 1.1 Fees."
FEE_BODY = "The fee is $5 starting on January 2, 2025."
DEFINITIONS = "§ 1.2 Definitions."
ROWS = "§ 1.3 Rates."
TABLE = "Rates"
XML = f"""<DIV5 TYPE="PART"><HEAD>Part 1</HEAD>
<DIV8 TYPE="SECTION"><HEAD>{FEE}</HEAD>
<P>{FEE_BODY}</P><CITA>[12 FR 34]</CITA></DIV8>
<DIV8 TYPE="SECTION"><HEAD>{DEFINITIONS}</HEAD>
<P><I>Person.</I> A human being.</P><P><I>Other.</I> A different person.</P>
<EDNOTE><P><I>Note.</I> See the next section.</P></EDNOTE></DIV8>
<DIV8 TYPE="SECTION"><HEAD>{ROWS}</HEAD>
<TABLE><CAPTION>{TABLE}</CAPTION><THEAD><TR><TH>Code</TH><TH>Rate</TH></TR></THEAD>
<TBODY><TR><TD>Alpha</TD><TD>33</TD></TR>
<TR><TD>Beta</TD><TD>46</TD></TR></TBODY></TABLE></DIV8></DIV5>""".encode()
TEXT = read("part.xml", data=XML).text.encode()
TRANSPORT = {"id": "fake", "model": "fixed", "effort": "medium", "version": "1"}
REQUESTS = [
    ("section_text", FEE, {}, FEE_BODY, None),
    ("definition", DEFINITIONS, {"term": "Person"}, "A human being.", None),
    ("table_value", FEE, {"row": 1}, "5.0", "$"),
    ("effective_date", FEE, {}, "2025-01-02", None),
    ("table_rows", ROWS, {"name": TABLE, "columns": ["Code", "Rate"]}, [
        {"Code": "Alpha", "Rate": "33"}, {"Code": "Beta", "Rate": "46"},
    ], None),
]  # fmt: skip


def pretty(value):
    return (json.dumps(value, indent=1, ensure_ascii=False) + "\n").encode()


@pytest.fixture
def project(tmp_path):
    directory, sources, cache = [tmp_path / name for name in ("set", "sources", "cache")]
    directory.mkdir()
    sources.mkdir()
    docs, slots, labels = [], [], []
    for i in range(1, 15):
        name = f"cfr-1-{i}"
        side = "calibration" if i % 3 == 1 else "heldout"
        docs.append({
            "id": name, "citation": "Part 1", "split": side, "selection_status": "frozen_member",
            "source_bytes": len(XML), "source_sha256": run.digest(XML),
            "text_sha256": run.digest(TEXT),
        })  # fmt: skip
        (sources / f"{name}.xml").write_bytes(XML)
        (sources / f"{name}.txt").write_bytes(TEXT)
        for field, section, request, gold, unit in REQUESTS:
            # The request identifier records the part order. The reply uses only the request.
            slot = f"r{len(slots) + 1:03}"
            keys = {"slot": slot, "id": name, "field": field, "split": side}
            slots.append(keys | {
                "kind": SCHEMA[field]["type"], "request": {"section": section} | request,
                "request_text": f"The {field} of {section}",
            })  # fmt: skip
            labels.append(keys | {"status": "value", "value": gold, "unit": unit})
    slot_body = pretty({"format": "regulatory-slots/1", "seed": "seed",
                        "schema": SCHEMA, "slots": slots})  # fmt: skip
    (directory / "slots.json").write_bytes(slot_body)
    label_body = pretty({"format": "regulatory-labels/1", "labels": labels})
    path = directory / "labels.json"
    path.write_bytes(label_body)
    ranges = []
    for row in labels:
        if row["split"] == "calibration":
            block = b"\n".join(b"  " + line for line in pretty(row).splitlines())
            start = label_body.index(block)
            ranges.append((start, start + len(block)))
    manifest = {
        "selection_complete": True, "split_rule": {"seed": "seed"}, "documents": docs,
        "slots": {"sha256": run.digest(slot_body), "count": len(slots),
                  "calibration": 25, "heldout": 45},
        "labels": {"file": path.name, "sha256": run.digest(label_body), "sealed": "2026-11-17",
                   "calibration_ranges": ranges,
                   "calibration_sha256": run.digest(b",".join(label_body[a:b] for a, b in ranges))},
    }  # fmt: skip
    (directory / "manifest.json").write_bytes(pretty(manifest))
    return directory, sources, cache


class Client:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        body = json.loads(prompt.removeprefix(run.extract.INSTRUCTIONS))
        assert body["citation"] == "Part 1"
        assert "labels" not in body
        answers = [
            {"heading": "1.1", "quote": f"{FEE}\n\n{FEE_BODY}"},
            {"heading": "Person", "quote": "Person. A human being."},
            {"value": "5", "unit": "USD", "evidence": {"value": "$5"}},
            {"value": "2025-01-02", "evidence": {"value": "January 2, 2025"}},
            {"rows": [[{"value": x, "quote": x} for x in row]
                      for row in (("Alpha", "33"), ("Beta", "46"))]},
        ]  # fmt: skip
        return json.dumps({"slots": [
            {"slot": request["slot"], "status": "value"} | answer
            for request, answer in zip(body["requests"], answers, strict=True)
        ]})  # fmt: skip


def freeze(project):
    run.Benchmark(*project).calibrate(TRANSPORT, Client())
    run.Benchmark(*project).freeze("2026-11-19")
    return run.Benchmark(*project)


def unused(prompt):
    pytest.fail("the transport was called")


def test_full_run_and_labels_access(project, monkeypatch):
    directory, sources, cache = project
    label_path = directory / "labels.json"
    labels = label_path.read_bytes()
    # A non-calibration byte can be unreadable while the calibration slices still verify.
    position = labels.index(b'"heldout"')
    label_path.write_bytes(labels[:position] + b"\xff" + labels[position + 1 :])
    cal = Client()
    run.Benchmark(*project).calibrate(TRANSPORT, cal)
    assert len(cal.prompts) == 5
    run.Benchmark(*project).calibrate(TRANSPORT, unused)
    run.Benchmark(*project).freeze("2026-11-19")
    label_path.write_bytes(labels)
    bench = run.Benchmark(directory, sources, cache)
    freeze_data = bench.manifest["freeze"]
    assert freeze_data["profile_sha256"] == run.profile_digest(freeze_data["profile"])
    assert freeze_data["code_sha256"] == run.code_digest()
    cal_report = json.loads((cache / "calibration" / "measure.json").read_text())
    assert cal_report["measure"]["documents"]["test"] == 5
    assert cal_report["score"]["total"]["admitted_right"] == 25
    heldout = Client()
    read_file = run._read

    def checked_read(path, *args):
        if path == label_path:
            assert len(heldout.prompts) == 9
        return read_file(path, *args)

    monkeypatch.setattr(run, "_read", checked_read)
    bench.heldout(TRANSPORT, heldout)
    result = json.loads((directory / "results.json").read_text())
    assert result["run"]["transport"] == TRANSPORT
    assert result["total"]["admitted_right"] == 45
    assert result["fields"]["definition"]["admitted_right"] == 9
    assert result["kinds"]["passage"]["admitted_right"] == 18
    assert result["total"]["admitted_error_upper_95"] == upper_95(0, 45)
    assert (directory / "RESULTS.md").read_text() == score.markdown(result)
    assert "#548" in score.markdown(result)
    with pytest.raises(ValueError, match="result already exists"):
        bench.heldout(TRANSPORT, unused)


@pytest.mark.parametrize("change", ["missing", "code", "profile", "transport"])
def test_heldout_refuses_changes(project, change, monkeypatch):
    directory, _, _ = project
    transport = TRANSPORT
    if change != "missing":
        bench = freeze(project)
        if change == "code":
            monkeypatch.setattr(run, "code_digest", lambda: "different")
        if change == "profile":
            bench.manifest["freeze"]["profile"]["description"] = "Different profile."
            (directory / "manifest.json").write_bytes(pretty(bench.manifest))
        if change == "transport":
            transport = TRANSPORT | {"version": "2"}
    with pytest.raises(ValueError, match=change):
        run.Benchmark(*project).heldout(transport, unused)
    assert not (directory / "heldout-run.json").exists()


def test_cache_binds_reply_and_inputs(project):
    directory, sources, cache = project
    bench = run.Benchmark(*project)
    bench.calibrate(TRANSPORT, Client())
    with pytest.raises(CacheError, match="immutable cache differs"):
        bench.calibrate(TRANSPORT | {"model": "new"}, unused)
    with pytest.raises(CacheError, match="outside the repository"):
        run.Benchmark(directory, sources, run.HERE / "cache")
    path = cache / "calibration" / "cfr-1-1" / "0001.json"
    entry = json.loads(path.read_bytes())
    path.write_bytes(pretty(entry | {"reply": "changed"}))
    with pytest.raises(CacheError, match="cached call differs"):
        bench.calibrate(TRANSPORT, unused)
    (sources / "cfr-1-1.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="reader text differs"):
        bench.calibrate(TRANSPORT, unused)


def test_heldout_reservation_survives_failure(project):
    directory, sources, cache = project
    bench = freeze(project)
    client = Client()

    def fail_second(prompt):
        if client.prompts:
            raise RuntimeError("fake interruption")
        return client(prompt)

    with pytest.raises(CachedTransportError, match="transport_error"):
        bench.heldout(TRANSPORT, fail_second)
    assert not (directory / "results.json").exists()
    assert (cache / "heldout" / "cfr-1-2" / "0001.json").exists()
    with pytest.raises(CachedTransportError, match="transport_error"):
        bench.heldout(TRANSPORT, unused)
    with pytest.raises(CacheError, match="immutable cache differs"):
        run.Benchmark(directory, sources, cache.with_name("new-cache")).heldout(TRANSPORT, unused)


def test_malformed_reply_counts_as_misses(project):
    directory, _, _ = project
    bench = freeze(project)
    client = Client()
    calls = 0

    def malformed_first(prompt):
        nonlocal calls
        calls += 1
        return "invalid JSON" if calls == 1 else client(prompt)

    bench.heldout(TRANSPORT, malformed_first)
    assert calls == 9
    result = json.loads((directory / "results.json").read_text())
    assert result["total"]["invalid"] == result["total"]["missed"] == 5
    assert result["total"]["admitted_error_upper_95"] == upper_95(0, 40)


@pytest.mark.parametrize(
    ("notes", "first_note"),
    [
        ("<SECAUTH>(Act 1)</SECAUTH>", "(Act 1)"),
        ("<CITA>[12 FR 34]</CITA>", "[12 FR 34]"),
        ("<EDNOTE><P>Editorial Note. Text.</P></EDNOTE>", "Editorial Note. Text."),
        ("<CITA>[12 FR 34]</CITA><EDNOTE>Editorial Note. Text.</EDNOTE>", "[12 FR 34]"),
    ],
    ids=["authority", "source", "editorial", "source-and-editorial"],
)
def test_passage_ends_before_trailing_notes(notes, first_note):
    body = "The café pays the fee.\n\n[12 FR 34]\n\nSee [12 FR 34]"
    xml = f"""<DIV5 TYPE="PART"><HEAD>Part 1</HEAD>
    <DIV8 TYPE="SECTION"><HEAD>{FEE}</HEAD><P>The café pays the fee.</P>
    <CITA>[12 FR 34]</CITA><P>See [12 FR 34]</P>{notes}</DIV8>
    </DIV5>""".encode()
    slot = {
        "slot": "r001",
        "field": "section_text",
        "kind": "passage",
        "request": {"section": FEE},
    }
    text = read("part.xml", data=xml).text
    view = run.extract.section_views(text, xml, [slot])[FEE]
    quote = f"{FEE}\n\n{body}"
    end = len(quote.encode())
    start = end + len(b"\n\n")
    assert view.outline[-1] == {"start": start, "end": start + len(first_note.encode()), "level": 1}
    profile = run.extract.base_profile(SCHEMA)

    def decide(heading, quote):
        answer = {"slot": "r001", "status": "value", "heading": heading, "quote": quote}
        items = run.extract.candidates(slot, answer, view, 0)
        receipt = run.gg.admit(view.text, None, items, profile=profile, outline=view.outline)
        return receipt.decisions[0]

    decision = decide("1.1", quote)
    assert decision.outcome == "admitted"
    assert decision.evidence == (0, end)
    assert run.extract.passage_value(view, decision.evidence) == body
    assert "PASSAGE_OVERRUN" in decide("1.1", view.text).codes
    note_quote = view.text.encode()[start:].decode()
    assert "PASSAGE_NOT_AT_HEADING" in decide(first_note.split()[0], note_quote).codes


def table_reply(xml, rows, monkeypatch):
    slot = {
        "slot": "r001",
        "field": "table_rows",
        "kind": "record",
        "request": {"section": ROWS, "name": TABLE, "columns": ["Code", "Rate"]},
    }
    text = read("part.xml", data=xml).text
    part = run.Part("part", text, [slot], run.extract.section_views(text, xml, [slot]), "")
    answer = {
        "slot": "r001", "status": "value",
        "rows": [[None if v is None else {"value": v, "quote": v} for v in row] for row in rows],
    }  # fmt: skip
    receipts = []
    admit = run.gg.admit

    def capture(*args, **kwargs):
        receipt = admit(*args, **kwargs)
        if receipt.records:
            receipts.append(receipt)
        return receipt

    monkeypatch.setattr(run.gg, "admit", capture)
    replies = {"part": run.parse_reply(json.dumps({"slots": [answer]}), [slot])}
    outputs, _ = run.admit([part], replies, run.extract.base_profile(SCHEMA))
    return outputs["r001"], receipts


def test_missing_body_row_goes_to_review(monkeypatch):
    xml = XML.replace(b"<TBODY>", b"<TBODY><TR><TD></TD><TD>GL BP</TD></TR>")
    answer, (receipt,) = table_reply(xml, [("Alpha", "33"), ("Beta", "46")], monkeypatch)
    assert answer == score.Answer("needs_verification")
    assert {row.record: row.outcome for row in receipt.records} == {
        "1": "needs_verification",
        "2": "admitted",
        "3": "admitted",
    }
    missing = next(d for d in receipt.decisions if d.candidate_id == "r001.1.2.structure")
    assert "NOT_CORROBORATED" in missing.codes
    assert any(d.candidate_id == "r001.2.1.model" for d in receipt.decisions)


@pytest.mark.parametrize("code", ["Alpha", None])
def test_null_member_at_cell_with_text_goes_to_review(code, monkeypatch):
    answer, (receipt,) = table_reply(XML, [(code, None), ("Beta", "46")], monkeypatch)
    assert answer == score.Answer("needs_verification")
    missing = next(d for d in receipt.decisions if d.candidate_id == "r001.1.2.structure")
    assert "NOT_CORROBORATED" in missing.codes


def test_full_table_is_admitted_in_source_order(monkeypatch):
    xml = XML.replace(b"Alpha", "Álpha".encode()).replace(b"<TD>46", b"<TD>33")
    answer, _ = table_reply(xml, [("Beta", "33"), ("Álpha", "33")], monkeypatch)
    assert answer == score.Answer(
        "admitted", [{"Code": "Álpha", "Rate": "33"}, {"Code": "Beta", "Rate": "33"}]
    )


def test_empty_cell_stays_null(monkeypatch):
    xml = XML.replace(b"<TD>33</TD>", b"<TD></TD>")
    answer, (receipt,) = table_reply(xml, [("Alpha", None), ("Beta", "46")], monkeypatch)
    assert answer == score.Answer(
        "admitted", [{"Code": "Alpha", "Rate": None}, {"Code": "Beta", "Rate": "46"}]
    )
    assert not any(d.candidate_id.startswith("r001.1.2.") for d in receipt.decisions)


@pytest.mark.parametrize("code", ["Alpha", None])
def test_cell_that_spans_rows_needs_a_match_in_each_row(code, monkeypatch):
    xml = XML.replace(b"<TD>Alpha</TD>", b'<TD rowspan="2">Alpha</TD>').replace(
        b"<TD>Beta</TD>", b""
    )
    answer, receipts = table_reply(xml, [("Alpha", "33"), (code, "46")], monkeypatch)
    if code is not None:
        assert answer == score.Answer(
            "admitted", [{"Code": "Alpha", "Rate": "33"}, {"Code": "Alpha", "Rate": "46"}]
        )
    else:
        assert answer == score.Answer("needs_verification")
        missing = next(
            d for receipt in receipts for d in receipt.decisions
            if d.candidate_id == "r001.2.1.structure"
        )  # fmt: skip
        assert "NOT_CORROBORATED" in missing.codes


def test_unreadable_table_goes_to_review(monkeypatch):
    xml = XML.replace(b"<TD>33</TD>", b"")
    answer, receipts = table_reply(xml, [("Alpha", "33"), ("Beta", "46")], monkeypatch)
    assert answer == score.Answer("needs_verification")
    assert receipts == []


def test_null_literal_goes_to_review(monkeypatch):
    # #736 cause 2. SPEC step 3 rejects the structure candidate for n/a, and spec 0.13
    # sends its record to review with RECORD_MEMBER_REJECTED.
    xml = XML.replace(b"<TD>33</TD>", b"<TD>n/a</TD>")
    answer, (receipt,) = table_reply(xml, [("Alpha", None), ("Beta", "46")], monkeypatch)
    assert answer == score.Answer("needs_verification")
    literal = next(d for d in receipt.decisions if d.candidate_id == "r001.1.2.structure")
    assert literal.outcome == "rejected"
    assert "NULL_STRING_LITERAL" in literal.codes
    line = next(r for r in receipt.records if "RECORD_MEMBER_REJECTED" in r.codes)
    assert line.outcome == "needs_verification"
    assert dict(line.rejected) == {"c2": ("NULL_STRING_LITERAL",)}


def test_score_escapes_misses_reviews_and_bound():
    templates = [
        ("table_value", "number", "5", "$", score.Answer("admitted", "5.00", "USD")),
        ("table_value", "number", "5", "$", score.Answer("admitted", "5", "%")),
        ("effective_date", "date", None, None, score.Answer("admitted", "2025-01-02")),
        ("effective_date", "date", "2025-01-02", None, score.Answer("needs_verification")),
        ("section_text", "passage", "A sentence", None, score.Answer(invalid=True)),
        ("definition", "passage", "Two  words", None, score.Answer("admitted", "Two\nwords")),
        ("table_rows", "record", [{"A": "first"}, {"A": "second"}], None,
         score.Answer("admitted", [{"A": "second"}, {"A": "first"}])),
    ]  # fmt: skip
    slots, labels, answers = [], {}, {}
    for i, (field, kind, value, unit, answer) in enumerate(templates):
        key = str(i)
        slots.append({"slot": key, "field": field, "kind": kind})
        labels[key] = {
            "status": "absent" if value is None else "value",
            "value": value,
            "unit": unit,
        }
        answers[key] = answer
    result = score.score(slots, labels, answers)
    assert result["total"] == {
        "slots": 7, "with_value": 6, "admitted_right": 2, "escapes": 3, "reviews": 1,
        "missed": 4, "invalid": 1, "admitted": 5, "miss_rate": round(4 / 6, 4),
        "admitted_error_upper_95": upper_95(3, 5),
    }  # fmt: skip
    assert result["fields"]["section_text"]["admitted_error_upper_95"] == 1
    assert result["kinds"]["number"]["admitted_error_upper_95"] == upper_95(1, 2)


def test_cli_transport_flags_and_tools(tmp_path):
    seen = []

    def runner(cmd, stdin, env):
        seen.append((cmd, stdin))
        if cmd == ["codex", "--version"]:
            return 0, "cli version", ""
        message = {"type": "item.completed", "item": {"type": "agent_message", "text": "{}"}}
        tool = {"type": "item.completed", "item": {"type": "command_execution"}}
        events = [message] if len(seen) == 2 else [tool, message]
        return 0, "\n".join(map(json.dumps, events)), ""

    client = run.Codex("fixed", "low", runner=runner, workdir=str(tmp_path))
    assert client.version() == "cli version"
    assert client.call("example") == "{}"
    cmd, stdin = seen[-1]
    assert cmd[:2] == ["codex", "exec"] and stdin == "example"
    assert cmd[cmd.index("-C") + 1] == str(tmp_path)
    assert cmd[cmd.index("-s") + 1] == "read-only"
    assert 'web_search="disabled"' in cmd and 'model_reasoning_effort="low"' in cmd
    assert set(run.judge.DISABLED) | {"unified_exec", "shell_tool"} <= {
        b for a, b in pairwise(cmd) if a == "--disable"
    }
    with pytest.raises(run.judge.JudgeError, match="used 1 tool"):
        client.call("example")


def test_checked_in_calibration_index(tmp_path):
    bench = run.Benchmark(run.HERE, tmp_path / "sources", tmp_path / "cache")
    slots = [s for s in bench.requests["slots"] if s["split"] == "calibration"]
    labels = bench.labels(slots, calibration=True)
    assert set(labels) == {s["slot"] for s in slots}
