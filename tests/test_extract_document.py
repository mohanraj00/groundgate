"""The runner on a document: node chunks and node citations (#508), with fixed replies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.canonical import jcs
from groundgate.cli import main
from groundgate.extract import ExtractInputError, RunPolicy, RunResult, extract, replay
from groundgate.extract.runner import _WORD_NODE_INSTRUCTIONS
from groundgate.read.document import Document, read_document
from groundgate.store import FolderStore, key
from groundgate.store.maintain import check, forget_packet
from groundgate.store.packets import load_packet

SCHEMA = {"fields": {"amount": {"type": "integer"}}}
TABLE = (
    "<h1>Annual report</h1><p>Intro text.</p><h2>Results</h2>"
    "<table><tr><th>Item</th><th>2024</th></tr>"
    "<tr><td>Revenue</td><td>5</td></tr><tr><td>Cost</td><td>3</td></tr>"
    "<tr><td>Other</td><td></td></tr></table>"
)


def plain(text: str) -> str:
    """The text of a prompt region without its node markers (#526)."""
    return re.sub("\u27e6[0-9]+\u27e7", "", text)


def document(tmp_path: Path, html: str) -> Document:
    path = tmp_path / "doc.html"
    path.write_text(f"<html><body>{html}</body></html>", encoding="utf-8")
    return read_document(path)[1]


def bare(text: str, doubt: list[Any] | None = None) -> Document:
    """A document with no nodes, and the doubt spans of a scan if ``doubt`` is given."""
    obj = {
        "format": "document@1",
        "source": key("source@1", text.encode()),
        "reader": {"name": "groundgate.read", "version": "0.14.0"},
        "options": {"pages": None},
        "text": key("text@1", text.encode()),
        "nodes": [],
        "doubt": doubt or [],
    }
    return Document.from_dict(obj, text)


class Client:
    """Each reply in turn; then "not found" for each requested field."""

    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.replies:
            return json.dumps(self.replies.pop(0))
        return json.dumps({"candidates": [], "not_found": body(prompt)["fields"]})


def body(prompt: str) -> Any:
    return json.loads(prompt.split("\n", 1)[1])


def cited(*evidence: Any, value: str = "5") -> dict[str, Any]:
    candidate = {"field": "amount", "value": value, "unit": None, "key": None}
    return {"candidates": [{**candidate, "evidence": list(evidence)}], "not_found": []}


def node(n: Any, text: str | None = None, **extra: Any) -> dict[str, Any]:
    item = {"source": "document", "role": "value", "node": n, **extra}
    return item if text is None else {**item, "text": text}


def run(doc: Document | str, client: Client, schema: Any = SCHEMA, **settings: Any) -> RunResult:
    return extract(doc, schema, client=client, model_id="fixed-1", run_policy=RunPolicy(**settings))


def test_a_large_table_splits_between_rows_and_sends_its_header_rows(tmp_path: Path) -> None:
    rows = "".join(f"<tr><td>Line {i}</td><td>{i}</td></tr>" for i in range(30))
    head = "<tr><th>Item</th><th>2024</th></tr>"
    doc = document(tmp_path, f"<h1>Report</h1><h2>Results</h2><table>{head}{rows}</table>")
    client = Client()
    result = run(doc, client, chunk_chars=60, overlap_chars=10, targeted=False)
    assert result.complete
    starts = {n.start for n in doc.of_kind("row")}
    ends = {n.end for n in doc.of_kind("row")}
    sent = [body(p)["sources"] for p in client.prompts]
    plan = next(e for e in result.record if e["kind"] == "plan")["chunks"]
    assert len(sent) == len(plan) > 3
    table = doc.of_kind("table")[0]
    data = doc.text.encode()
    for chunk, sources in zip(plan, sent, strict=True):
        assert sources[0]["start"] == chunk["start"] and sources[0]["end"] == chunk["end"]
        if chunk["start"] <= table.start:
            continue  # the headings, and the part of the table with its header row
        # Whole rows: the chunk starts at a row and ends after a row and its line break.
        assert chunk["start"] in starts
        assert len(data[: chunk["end"]].rstrip(b"\n")) in ends
        texts = [plain(s["text"]) for s in sources[1:]]
        assert texts == ["Report", "Results", "Item\t2024"]
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


def test_a_chunk_sends_only_the_headings_whose_sections_hold_it(tmp_path: Path) -> None:
    html = "<h1>A</h1><p>one</p><h2>B</h2><p>two</p><h2>C</h2><p>three</p>"
    client = Client()
    run(document(tmp_path, html), client, chunk_chars=8, overlap_chars=1, targeted=False)
    sent = [[s["text"] for s in body(p)["sources"]] for p in client.prompts]
    assert sent == [["A\n\none\n\n"], ["B\n\ntwo\n\n", "A"], ["C\n\nthree", "A"]]


def test_a_large_row_falls_back_to_the_character_window(tmp_path: Path) -> None:
    long = " ".join(f"w{i}" for i in range(40))
    html = f"<table><tr><th>Item</th></tr><tr><td>{long}</td></tr></table>"
    client = Client()
    result = run(document(tmp_path, html), client, chunk_chars=50, overlap_chars=5)
    plan = next(e for e in result.record if e["kind"] == "plan")["chunks"]
    assert len(plan) > 2
    assert all(e["end"] - e["start"] <= 50 for e in plan)
    # Each window after the header row also sends the header row.
    heads = [[plain(s["text"]) for s in body(p)["sources"][1:]] for p in client.prompts[1:4]]
    assert heads == [["Item"]] * 3


def test_a_document_with_no_nodes_gives_the_prompts_of_its_text() -> None:
    text = "".join(f"Line {i} of the text.\n" for i in range(40))
    settings = {"chunk_chars": 100, "overlap_chars": 20}
    on_text, on_document = Client(), Client()
    a = run(text, on_text, **settings)
    b = run(bare(text), on_document, **settings)
    assert len(on_text.prompts) > 3
    # The same regions. The prompt of a run on a document also names node citations (#526).
    assert [body(p)["sources"] for p in on_text.prompts] == [
        body(p)["sources"] for p in on_document.prompts
    ]
    named = b.record[0]["inputs"]["document"]
    assert a.record[0]["inputs"]["document"]["kind"] == "text"
    assert named["kind"] == "document"
    assert named["reader"] == {"name": "groundgate.read", "version": "0.14.0"}
    assert replay(b.record, b.artifacts, bare(text), SCHEMA).ok
    # A run on a document replays with its document, not its text.
    assert not replay(b.record, b.artifacts, text, SCHEMA).ok
    assert not replay(a.record, a.artifacts, bare(text), SCHEMA).ok


def test_a_node_citation_becomes_a_span(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    cell = doc.find("5")[0].node
    assert cell is not None and cell.kind == "cell"
    row = doc.nodes[cell.parent or 0]
    assert row.kind == "row"
    for evidence in (node(cell.id), node(cell.id, "5"), node(cell.id, " 5 ")):
        result = run(doc, Client(cited(evidence)))
        assert result.complete
        assert result.receipt.decisions[0].outcome == "admitted"
        item = result.candidates[0]["evidence"][0]
        assert item == {"source": "document", "role": "value", "start": cell.start, "end": cell.end}
        assert gg.verify(result.receipt.to_dict(), doc.text, SCHEMA, result.candidates).ok
        assert replay(result.record, result.artifacts, doc, SCHEMA).ok


@pytest.mark.parametrize(
    "evidence",
    [
        node(99, "5"),  # an unknown id
        node(-1, "5"),
        node(True, "5"),
        node("9", "5"),
        node(9.0, "5"),
        node(None),
        node(3, "  "),  # a blank quote
        node(3),  # a node alone that is not a cell
        node(4),  # a row
        node("empty"),  # an empty cell: nothing can cite it
        node(3, "5", start=55),  # an offset beside the node
        {"source": "reference", "role": "value", "node": 9, "text": "5", "ref": "r"},
    ],
)
def test_an_invalid_node_citation_makes_the_reply_invalid(tmp_path: Path, evidence: Any) -> None:
    doc = document(tmp_path, TABLE)
    if evidence.get("node") == "empty":
        evidence = node(next(n.id for n in doc.of_kind("cell") if n.start == n.end))
    result = run(doc, Client(cited(evidence)))
    call = next(e for e in result.record if e["kind"] == "call")
    assert call["status"] == "invalid_reply"
    assert not result.complete and not result.candidates


@pytest.mark.parametrize("quote", ["7", "e"])
def test_a_quote_not_once_in_its_node_fails_only_its_candidate(tmp_path: Path, quote: str) -> None:
    # A quote that is in its node zero times, or two or more times, drops only its candidate.
    # The other candidates of the reply stay, and the run stays complete (#632). With no repair
    # round, the candidate gets no quote repair (#645).
    doc = document(tmp_path, TABLE)
    revenue, five, three = (doc.find(t)[0].node for t in ("Revenue", "5", "3"))
    assert revenue is not None and five is not None and three is not None
    schema = {"fields": {"amount": {"type": "integer"}, "cost": {"type": "integer"}}}
    reply = {
        "candidates": [
            {
                "field": "amount",
                "value": "5",
                "unit": None,
                "key": None,
                "evidence": [node(revenue.id, quote)],
            },
            {
                "field": "cost",
                "value": "3",
                "unit": None,
                "key": None,
                "evidence": [node(three.id, "3")],
            },
        ],
        "not_found": [],
    }
    result = run(doc, Client(reply), schema, targeted=False, max_repair_rounds=0)
    call = next(e for e in result.record if e["kind"] == "call")
    assert call["status"] == "ok"
    assert result.complete
    assert [c["field"] for c in result.candidates] == ["cost"]
    assert result.receipt.decisions[0].outcome == "admitted"
    failure = next(e for e in result.record if e["kind"] == "protocol_failure")
    assert (failure["phase"], failure["field"], failure["reason"]) == (
        "initial",
        "amount",
        "node_quote",
    )
    assert replay(result.record, result.artifacts, doc, schema).ok


def test_a_repair_quote_not_once_in_its_node_fails_only_its_candidate(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    revenue = doc.find("Revenue")[0].node
    assert revenue is not None
    first = cited()  # no evidence: the repair may add a value item
    repair = cited(node(revenue.id, "e"))["candidates"][0]
    result = run(doc, Client(first, repair), targeted=False)
    calls = [e for e in result.record if e["kind"] == "call"]
    assert [c["phase"] for c in calls] == ["initial", "repair"]
    assert all(c["status"] == "ok" for c in calls)
    assert result.complete
    assert any(e["kind"] == "repair" and e["status"] == "protocol_failure" for e in result.record)
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


REPEATED = "<table><tr><td>Deductible</td><td>5 single 5 family 5 single</td></tr></table>"


def test_the_prompt_asks_for_a_node_quote_that_is_once(tmp_path: Path) -> None:
    client = Client()
    run(document(tmp_path, TABLE), client, targeted=False)
    assert "A quote inside a node must be once in that node." in client.prompts[0]


def repeated(tmp_path: Path) -> tuple[Document, int]:
    doc = document(tmp_path, REPEATED)
    cell = doc.find("5 family")[0].node
    assert cell is not None
    return doc, cell.id


def test_a_repeated_node_quote_gets_a_quote_repair(tmp_path: Path) -> None:
    # A quote that is 3 times in its node gets a repair round. A quote that is once in the
    # repair gives the candidate, and the targeted search does not run (#645).
    doc, cell = repeated(tmp_path)
    repair = cited(node(cell, "5 family"))["candidates"][0]
    client = Client(cited(node(cell, "5")), repair)
    result = run(doc, client)
    calls = [e for e in result.record if e["kind"] == "call"]
    assert [(c["phase"], c.get("reason")) for c in calls] == [
        ("initial", None),
        ("repair", "node_quote"),
    ]
    sent = body(client.prompts[1])
    assert sent["candidate_id"] == "c1-1" and sent["allowed_roles"] == ["value"]
    assert f'quote "5" is 3 times in node {cell}.' in sent["feedback"]
    assert result.complete
    [candidate] = result.candidates
    start = doc.text.encode().index(b"5 family")
    assert candidate["id"] == "c1-1"
    assert candidate["evidence"][0] == {
        "source": "document",
        "role": "value",
        "start": start,
        "end": start + len("5 family"),
    }
    assert result.receipt.decisions[0].outcome == "admitted"
    assert any(e.get("status") == "quote_repair" for e in result.record)
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


def test_a_quote_repair_that_repeats_the_quote_fails_only_its_candidate(tmp_path: Path) -> None:
    # The runner never takes the first match. After the last round, the candidate fails (#632).
    doc, cell = repeated(tmp_path)
    first = cited(node(cell, "5"))
    client = Client(first, *(cited(node(cell, t))["candidates"][0] for t in ("5 single", "single")))
    result = run(doc, client, targeted=False)
    calls = [e for e in result.record if e["kind"] == "call"]
    assert [c["phase"] for c in calls] == ["initial", "repair", "repair"]
    assert [c["round"] for c in calls[1:]] == [1, 2]
    assert result.complete and not result.candidates
    repairs = [e["status"] for e in result.record if e["kind"] == "repair"]
    assert repairs == ["protocol_failure", "protocol_failure"]
    assert '"5 single" is 2 times' in body(client.prompts[2])["feedback"]
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


@pytest.mark.parametrize(
    "change",
    [
        {"value": "6"},  # a changed value
        {"evidence": [node("other", "Deductible")]},  # another node
        {"evidence": [node("cell", "5 family"), node("cell", "single", role="sign")]},
    ],
)
def test_a_quote_repair_changes_only_the_quote(tmp_path: Path, change: Any) -> None:
    doc, cell = repeated(tmp_path)
    other = doc.find("Deductible")[0].node
    assert other is not None
    ids = {"cell": cell, "other": other.id}
    for item in change.get("evidence", []):
        item["node"] = ids[item["node"]]
    repair = {**cited(node(cell, "5 family"))["candidates"][0], **change}
    result = run(doc, Client(cited(node(cell, "5")), repair), targeted=False)
    assert result.complete and not result.candidates
    repairs = [e for e in result.record if e["kind"] == "repair"]
    assert [(e["status"], e["reason"]) for e in repairs] == [("protocol_failure", "node_quote")]


def test_a_node_citation_on_a_run_on_text_is_invalid() -> None:
    result = run("Amount 5.", Client(cited(node(0, "5"))))
    assert next(e for e in result.record if e["kind"] == "call")["status"] == "invalid_reply"


def test_a_cited_node_outside_the_prompt_makes_the_reply_invalid(tmp_path: Path) -> None:
    doc = document(tmp_path, "<p>Amount 5.</p><p>Other 7.</p>")
    seven = doc.find("7")[0].node
    assert seven is not None
    result = run(
        doc, Client(cited(node(seven.id, "7"), value="7")), chunk_chars=14, overlap_chars=1
    )
    # The prompt marked no node, so no id is valid (#526).
    assert any(e.get("status") == "invalid_reply" for e in result.record)
    assert not result.complete and not result.candidates


def test_a_cut_region_ends_at_row_boundaries_and_keeps_the_header_rows(tmp_path: Path) -> None:
    rows = "".join(f"<tr><td>Cost {i}</td><td>{i}</td></tr>" for i in range(10))
    rows += "".join(f"<tr><td>Revenue line {i}</td><td>{i}</td></tr>" for i in range(20))
    html = f"<table><tr><th>Item</th><th>2024</th></tr>{rows}</table>"
    doc = document(tmp_path, html)
    schema = {"fields": {"revenue": {"type": "integer"}}}
    client = Client()
    settings = {"search_context_chars": 40, "max_region_chars": 100}
    result = run(doc, client, schema, **settings)
    assert result.complete
    search = next(e for e in result.record if e["kind"] == "search")
    (cut,) = search["cut_regions"]
    bounds = {x for n in doc.of_kind("row") for x in (n.start, n.end)}
    assert cut["kept_start"] in bounds and cut["kept_end"] in bounds
    assert cut["kept_start"] != cut["start"] or cut["kept_end"] != cut["end"]
    sources = body(client.prompts[-1])["sources"]
    assert plain(sources[0]["text"]) == "Item\t2024"
    assert sources[1]["start"] == cut["kept_start"] and sources[1]["end"] == cut["kept_end"]
    assert replay(result.record, result.artifacts, doc, schema).ok


def test_the_same_cut_on_text_keeps_its_window(tmp_path: Path) -> None:
    rows = "".join(f"<tr><td>Cost {i}</td><td>{i}</td></tr>" for i in range(10))
    rows += "".join(f"<tr><td>Revenue line {i}</td><td>{i}</td></tr>" for i in range(20))
    doc = document(tmp_path, f"<table><tr><th>Item</th><th>2024</th></tr>{rows}</table>")
    schema = {"fields": {"revenue": {"type": "integer"}}}
    result = run(doc.text, Client(), schema, search_context_chars=40, max_region_chars=100)
    (cut,) = next(e for e in result.record if e["kind"] == "search")["cut_regions"]
    assert cut["kept_end"] - cut["kept_start"] == 100


def test_the_record_names_the_document_and_the_store_keeps_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = document(tmp_path, TABLE)
    result = run(doc, Client(cited(node(doc.find("5")[0].node.id))))  # type: ignore[union-attr]
    named = result.record[0]["inputs"]["document"]
    assert named["kind"] == "document"
    assert named["document_key"] == key("document@1", doc.to_json())
    assert result.artifacts[named["document_sha256"]].encode() == doc.to_json()
    result.write(tmp_path / "run")
    assert RunResult.read(tmp_path / "run").run_sha256 == result.run_sha256
    with FolderStore(tmp_path / "store") as store:
        packet = result.save(store)
        assert store.get("document@1", named["document_key"]) == doc.to_json()
        assert not check(store).findings
        # The store replays the run from its packet key, with its document (#429).
        loaded = RunResult.load(store, packet)
        assert loaded.run_sha256 == result.run_sha256
        assert loaded.candidates == result.candidates
        assert main(["export", "--store", str(tmp_path / "store"), packet]) == 0
        (fact,) = json.loads(capsys.readouterr().out)["facts"]
        assert fact["citation"]["source_sha256"] == doc.source
        done = forget_packet(store, packet, "the owner asked")
        assert ("document@1", named["document_key"], "deleted", 0) in done


def test_a_scan_with_doubt_gets_the_same_receipt_from_extract_and_the_store(
    tmp_path: Path,
) -> None:
    text = "Total 5 and 6.\n"
    doc = bare(text, [{"start": 6, "end": 7, "confidence": 0.4}])
    quote = {"source": "document", "role": "value", "text": "5"}
    result = run(doc, Client(cited(quote)))
    decision = result.receipt.decisions[0]
    assert decision.outcome == "needs_verification" and "READ_DOUBT" in decision.codes
    assert result.receipt.doubt_sha256 is not None
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok
    result.write(tmp_path / "run")
    assert RunResult.read(tmp_path / "run").receipt.to_dict() == result.receipt.to_dict()
    with FolderStore(tmp_path / "store") as store:
        packet = result.save(store)
        assert not check(store).findings
        found = load_packet(store, packet)
        assert found.doubt == doc.doubt
        assert found.receipt == result.receipt.to_dict()
        assert gg.verify(found.receipt, found.text, found.schema, found.candidates,
                         **found.inputs()).ok  # fmt: skip
        assert RunResult.load(store, packet).receipt.to_dict() == result.receipt.to_dict()
        # a packet with no doubt, or another doubt, does not name the inputs of its run
        obj = json.loads(store.get("packet@1", packet))
        other = store.put("doubt@1", jcs([{"start": 0, "end": 1, "confidence": 0.4}]).encode())
        for changed in ({k: v for k, v in obj.items() if k != "doubt"}, {**obj, "doubt": other}):
            bad = store.put("packet@1", jcs(changed).encode())
            with pytest.raises(ValueError, match="another doubt"):
                RunResult.load(store, bad)
        # the doubt spans hold offsets and confidences, no text: forget keeps them
        done = forget_packet(store, packet, "the owner asked")
        assert not [d for d in done if d[0] == "doubt@1"]
        assert store.get("doubt@1", json.loads(store.get("packet@1", packet))["doubt"])
    # a document with no doubt gives a packet with no member doubt
    clean = run(bare(text), Client(cited(quote)))
    assert clean.receipt.decisions[0].outcome == "admitted"
    with FolderStore(tmp_path / "store2") as store:
        assert "doubt" not in json.loads(store.get("packet@1", clean.save(store)))


def test_the_empty_receipt_of_a_run_keeps_the_doubt() -> None:
    # The admission limit stops the run before its first admission: the run keeps the receipt
    # with no candidates, and that receipt binds the doubt too.
    doc = bare("Amount 5.\n", [{"start": 7, "end": 8, "confidence": 0.4}])
    nothing = {"candidates": [], "not_found": ["amount"]}
    result = run(doc, Client(nothing), max_admission_bytes=100)
    assert not result.complete and result.receipt.doubt_sha256 is not None
    assert gg.verify(result.receipt.to_dict(), doc.text, SCHEMA, result.candidates,
                     doubt=doc.doubt).ok  # fmt: skip
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


def test_the_rounding_rule_reads_the_doubt_of_the_exact_figure() -> None:
    # The exact figure is on a doubted word, so it is not admitted, and the rounded figure
    # stays: a drop stands only when the exact figure is admitted without it.
    schema = {"fields": {"revenue": {"type": "number", "aliases": ["Revenue"]}}}
    text = "Revenue rose to 17.3bn.\n(in millions)\nRevenue\t17,284\n"
    start = text.encode().index(b"17,284")
    doc = bare(text, [{"start": start, "end": start + 6, "confidence": 0.4}])

    def item(quote: str, role: str = "value") -> dict[str, Any]:
        return {"source": "document", "role": role, "text": quote}

    rounded = {"field": "revenue", "value": "17300000000", "unit": None, "key": None,
               "evidence": [item("17.3bn")]}  # fmt: skip
    exact = {"field": "revenue", "value": "17284000000", "unit": None, "key": None,
             "evidence": [item("17,284"), item("Revenue", "field"),
                          item("in millions", "scale")]}  # fmt: skip
    reply = {"candidates": [rounded, exact], "not_found": []}
    result = run(doc, Client(reply), schema, drop_rounded=True)
    assert [c["id"] for c in result.candidates] == ["c1-1", "c1-2"]
    assert any("READ_DOUBT" in d.codes for d in result.receipt.decisions)
    assert replay(result.record, result.artifacts, doc, schema).ok
    # without the doubt, the same reply drops the rounded figure
    clean = run(bare(text), Client(reply), schema, drop_rounded=True)
    assert [c["id"] for c in clean.candidates] == ["c1-2"]


def test_the_runner_checks_the_document() -> None:
    doc = bare("Amount 5.")
    doc.text = "Amount 7."  # the text key no longer names the text
    with pytest.raises(ExtractInputError, match="not valid"):
        run(doc, Client())


def test_a_first_pass_quote_in_a_context_region_is_found_there(tmp_path: Path) -> None:
    # The reproduction of the review of #527: the value is only in the heading region.
    doc = document(tmp_path, "<h1>Amount 5</h1><p>nothing here</p><p>nothing there</p>")
    replies = [envelope_missing(), cited({"source": "document", "role": "value", "text": "5"})]
    client = Client(*replies)
    result = run(doc, client, chunk_chars=16, overlap_chars=1)
    texts = [s["text"] for s in body(client.prompts[1])["sources"]]
    assert texts[1] == "Amount 5" and "5" not in texts[0]
    heading = doc.of_kind("heading")[0]
    region = result.candidates[0]["search_region"]
    assert (region["start"], region["end"]) == (heading.start, heading.end)
    assert result.receipt.decisions[0].outcome == "admitted"
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


def envelope_missing() -> dict[str, Any]:
    return {"candidates": [], "not_found": ["amount"]}


def test_header_rows_never_take_the_place_of_a_match_region(tmp_path: Path) -> None:
    # The reproduction of the review of #527: one region, and it must hold the matches.
    rows = "".join(f"<tr><td>Cost {i}</td><td>{i}</td></tr>" for i in range(10))
    rows += "".join(f"<tr><td>Revenue line {i}</td><td>{i}</td></tr>" for i in range(20))
    doc = document(tmp_path, f"<table><tr><th>Item</th><th>2024</th></tr>{rows}</table>")
    schema = {"fields": {"revenue": {"type": "integer"}}}
    client = Client()
    settings = {"search_context_chars": 40, "max_region_chars": 100, "max_target_regions": 1}
    result = run(doc, client, schema, **settings)
    (sent,) = body(client.prompts[-1])["sources"]
    assert "Revenue line 0" in sent["text"]
    search = next(e for e in result.record if e["kind"] == "search")
    assert search["omitted_regions"] == 0
    assert replay(result.record, result.artifacts, doc, schema).ok


def test_a_node_of_any_role_outside_the_prompt_is_refused(tmp_path: Path) -> None:
    # The reproduction of the security review of #527: an unsent scale node must not
    # make 5 into 5000.
    filler = "".join(f"<p>Filler line {i}.</p>" for i in range(6))
    doc = document(tmp_path, f"<p>(in thousands)</p>{filler}<p>Revenue 5</p>")
    scale = doc.of_kind("paragraph")[0]
    reply = cited(
        {"source": "document", "role": "value", "text": "5"},
        node(scale.id, "in thousands", role="scale"),
        value="5000",
    )
    prompts: list[str] = []

    def client(prompt: str) -> str:
        prompts.append(prompt)
        texts = [s["text"] for s in body(prompt)["sources"]]
        if body(prompt)["fields"] == ["amount"] and any("Revenue 5" in t for t in texts):
            assert not any("(in thousands)" in t for t in texts)
            return json.dumps(reply)
        return json.dumps({"candidates": [], "not_found": body(prompt)["fields"]})

    result = extract(
        doc,
        SCHEMA,
        client=client,
        model_id="fixed-1",
        run_policy=RunPolicy(chunk_chars=30, overlap_chars=1),
    )
    # The prompt did not mark the node, so the reply is invalid (#526).
    assert any(e.get("status") == "invalid_reply" for e in result.record)
    assert all(d.outcome != "admitted" for d in result.receipt.decisions)


def kept_match(tmp_path: Path, rows: list[str]) -> tuple[dict[str, Any], str]:
    """The cut region and the text of the last prompt, for a search of "revenue" in a table."""
    cells = "".join(f"<tr><td>{r}</td></tr>" for r in rows)
    doc = document(tmp_path, f"<table><tr><th>Item</th><th>Year</th></tr>{cells}</table>")
    schema = {"fields": {"revenue": {"type": "integer"}}}
    client = Client()
    result = run(doc, client, schema, search_context_chars=100, max_region_chars=100)
    search = next(e for e in result.record if e["kind"] == "search")
    match = min(search["matches"], key=lambda m: m["rank"])
    (cut,) = search["cut_regions"]
    assert cut["kept_start"] <= match["start"] and match["end"] <= cut["kept_end"]
    assert replay(result.record, result.artifacts, doc, schema).ok
    return cut, " ".join(s["text"] for s in body(client.prompts[-1])["sources"])


def test_a_snapped_cut_keeps_its_match(tmp_path: Path) -> None:
    # The reproduction of the review of #527: both ends snapped past the match.
    _, sent = kept_match(tmp_path, ["filler " * 50 + "Revenue 5", "other " * 20])
    assert "Revenue 5" in sent


def test_the_left_end_of_a_cut_does_not_move_past_its_match(tmp_path: Path) -> None:
    _, sent = kept_match(tmp_path, ["filler " * 50 + "Revenue 5", "other " * 50])
    assert "Revenue 5" in sent


def test_the_right_end_of_a_cut_does_not_move_past_its_match(tmp_path: Path) -> None:
    _, sent = kept_match(tmp_path, ["other " * 50, "Revenue 5 " + "filler " * 50])
    assert "Revenue 5" in sent


def test_a_snapped_cut_stays_within_max_region_chars(tmp_path: Path) -> None:
    # The reproduction of the review of #527: snapping to the ends of one long row must not
    # grow a 100-character window into the whole row.
    cell = "filler " * 700 + "Revenue 5 " + "other " * 700
    doc = document(tmp_path, f"<table><tr><th>Item</th></tr><tr><td>{cell}</td></tr></table>")
    schema = {"fields": {"revenue": {"type": "integer"}}}
    settings = {
        "chunk_chars": 500,
        "overlap_chars": 10,
        "search_context_chars": 10000,
        "max_region_chars": 100,
        "max_prompt_chars": 6000,
    }
    client = Client()
    result = run(doc, client, schema, **settings)
    search = next(e for e in result.record if e["kind"] == "search")
    (cut,) = search["cut_regions"]
    assert cut["kept_end"] - cut["kept_start"] <= 100
    assert search["status"] != "search_limit"
    assert "Revenue 5" in " ".join(s["text"] for s in body(client.prompts[-1])["sources"])
    assert replay(result.record, result.artifacts, doc, schema).ok


MARK = re.compile("⟦([0-9]+)⟧")


def test_only_a_cell_with_text_gets_a_marker_before_its_text(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    client = Client()
    result = run(doc, client)
    (entry,) = body(client.prompts[0])["sources"]
    text = entry["text"]
    cells = {n.id for n in doc.of_kind("cell") if n.start < n.end}
    assert {int(m) for m in MARK.findall(text)} == cells
    assert len(MARK.findall(text)) == len(cells)
    data = doc.text.encode()
    for found in MARK.finditer(text):
        cell = doc.nodes[int(found[1])]
        assert text[found.end() :].startswith(data[cell.start : cell.end].decode())
    # The region keeps its document offsets, and its length is the length of the marked text.
    assert plain(text) == doc.text and entry["length"] == len(text)
    assert "node_ids" not in entry
    assert replay(result.record, result.artifacts, doc, SCHEMA).ok


def test_a_region_with_a_marker_bracket_of_its_own_gets_no_markers(tmp_path: Path) -> None:
    doc = document(tmp_path, f"<p>Note ⟦3⟧ here.</p>{TABLE}")
    cell = doc.find("5")[0].node
    assert cell is not None
    client = Client(cited(node(cell.id)))
    result = run(doc, client)
    (entry,) = body(client.prompts[0])["sources"]
    assert entry["node_ids"] is False and entry["text"] == doc.text
    # The prompt marked no node: the forged id and the real cell id are both invalid.
    assert next(e for e in result.record if e["kind"] == "call")["status"] == "invalid_reply"
    forged = run(doc, Client(cited(node(3, "5"))))
    assert next(e for e in forged.record if e["kind"] == "call")["status"] == "invalid_reply"


def test_a_marker_in_a_quote_is_removed(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    cell = doc.find("5")[0].node
    assert cell is not None
    marker = f"⟦{cell.id}⟧"
    for evidence in (
        {"source": "document", "role": "value", "text": f"{marker}5"},
        node(cell.id, f"{marker}5"),
    ):
        result = run(doc, Client(cited(evidence)))
        assert result.receipt.decisions[0].outcome == "admitted"
        assert "⟦" not in json.dumps(result.candidates)
        assert replay(result.record, result.artifacts, doc, SCHEMA).ok
    # A quote of only a marker quotes nothing.
    only = run(doc, Client(cited({"source": "document", "role": "value", "text": marker})))
    assert not only.candidates


def test_the_output_schema_of_a_run_on_a_document_names_node(tmp_path: Path) -> None:
    on_document, on_text = Client(), Client()
    run(document(tmp_path, TABLE), on_document)
    run("Amount 5.", on_text)
    defs = body(on_document.prompts[0])["output_schema"]["$defs"]
    assert defs["document_node"]["properties"]["node"] == {
        "type": "integer",
        "description": "The id in the marker before a cell, without the brackets.",
    }
    assert {"$ref": "#/$defs/document_node"} in defs["evidence"]["items"]["anyOf"]
    assert "document_node" not in body(on_text.prompts[0])["output_schema"]["$defs"]
    assert "⟦" in on_document.prompts[0].split("\n", 1)[0]
    assert "⟦" not in on_text.prompts[0].split("\n", 1)[0]


def test_a_cell_that_the_prompt_did_not_mark_makes_the_reply_invalid(tmp_path: Path) -> None:
    # Two tables in two chunks: the first prompt marks only the cells of the first table.
    first = "<table><tr><td>Amount</td><td>5</td></tr></table>"
    doc = document(tmp_path, f"{first}<p>{'filler ' * 10}</p><table><tr><td>7</td></tr></table>")
    seven = doc.find("7")[0].node
    assert seven is not None and seven.kind == "cell"
    client = Client(cited(node(seven.id), value="7"))
    result = run(doc, client, chunk_chars=40, overlap_chars=1)
    assert str(seven.id) not in MARK.findall(body(client.prompts[0])["sources"][0]["text"])
    call = next(e for e in result.record if e["kind"] == "call")
    assert call["status"] == "invalid_reply" and not result.candidates


def test_the_markers_count_against_the_chunk_and_the_prompt_size(tmp_path: Path) -> None:
    rows = "".join(f"<tr><td>{i}</td></tr>" for i in range(8))
    doc = document(tmp_path, f"<table>{rows}</table>")
    assert len(doc.text) <= 40
    result = run(doc, Client(), chunk_chars=40, overlap_chars=1, targeted=False)
    # Without the markers the table fits one chunk. With them it does not.
    chunks = next(e for e in result.record if e["kind"] == "plan")["chunks"]
    assert len(chunks) > 1
    client = Client()
    probe = run(doc, client, targeted=False)
    limit = len(client.prompts[0]) - 1
    assert len(client.prompts[0]) - len(plain(client.prompts[0])) > 1
    assert probe.complete
    with pytest.raises(ExtractInputError, match="max_prompt_chars"):
        run(doc, Client(), targeted=False, max_prompt_chars=limit)


def test_a_quote_of_literal_marker_text_keeps_its_text(tmp_path: Path) -> None:
    # The reproduction of the review of #528: the region holds ⟦12⟧ of its own.
    doc = document(tmp_path, "<p>Code A⟦12⟧B.</p><p>Amount 5</p>")
    schema = {"fields": {"code": {"type": "string"}}}
    quote = "A⟦12⟧B"
    reply = {
        "candidates": [
            {
                "field": "code",
                "value": quote,
                "unit": None,
                "key": None,
                "evidence": [{"source": "document", "role": "value", "text": quote}],
            }
        ],
        "not_found": [],
    }
    result = run(doc, Client(reply), schema)
    assert result.receipt.decisions[0].outcome == "admitted"
    assert result.candidates[0]["evidence"][0]["text"] == quote
    # The decision span (UTF-8 bytes) is inside the one true place of the quote.
    start = doc.text.encode().index(quote.encode())
    span = result.receipt.decisions[0].evidence
    assert span is not None
    assert start <= span[0] < span[1] <= start + len(quote.encode())
    assert replay(result.record, result.artifacts, doc, schema).ok


def test_a_copied_marker_in_a_marked_region_gives_the_cell_span(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    cell = doc.find("5")[0].node
    assert cell is not None
    marker = f"⟦{cell.id}⟧"
    for evidence in (
        {"source": "document", "role": "value", "text": f"{marker}5"},
        node(cell.id, f"{marker}5"),
    ):
        result = run(doc, Client(cited(evidence)))
        assert result.receipt.decisions[0].outcome == "admitted"
        span = result.receipt.decisions[0].evidence
        assert span is not None and cell.start <= span[0] < span[1] <= cell.end


def test_a_column_item_can_cite_a_header_cell(tmp_path: Path) -> None:
    # A marker word is document text, not a node id: the prompt says so (#554).
    schema = {"fields": {"amount": {"aliases": ["Revenue"], "columns": ["2024"]}}}
    doc = document(tmp_path, TABLE)
    value, label, header = (doc.find(text)[0].node for text in ("5", "Revenue", "2024"))
    assert value is not None and label is not None and header is not None
    evidence = [node(value.id), node(label.id, role="field"), node(header.id, role="column")]
    client = Client(cited(*evidence))
    result = run(doc, client, schema)
    assert result.receipt.decisions[0].outcome == "admitted"
    assert client.prompts[0].split("\n", 1)[0].endswith(_WORD_NODE_INSTRUCTIONS)
    assert replay(result.record, result.artifacts, doc, schema).ok
