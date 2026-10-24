"""The runner on a document: node chunks and node citations (#508), with fixed replies."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.extract import ExtractInputError, RunPolicy, RunResult, extract, replay
from groundgate.read.document import Document, read_document
from groundgate.store import FolderStore, key
from groundgate.store.maintain import check, forget_packet

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


def bare(text: str) -> Document:
    """A document with no nodes."""
    obj = {
        "format": "document@1",
        "source": key("source@1", text.encode()),
        "reader": {"name": "groundgate.read", "version": "0.13.0"},
        "options": {"pages": None},
        "text": key("text@1", text.encode()),
        "nodes": [],
        "doubt": [],
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
    assert named["reader"] == {"name": "groundgate.read", "version": "0.13.0"}
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
        node(3, "7"),  # the quote is not in the node
        node(3, "e"),  # the quote is in the node two or more times
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


def test_the_record_names_the_document_and_the_store_keeps_it(tmp_path: Path) -> None:
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
        done = forget_packet(store, packet, "the owner asked")
        assert ("document@1", named["document_key"], "deleted", 0) in done


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
