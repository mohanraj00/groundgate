"""The structure reader, a proposer with no model (#510, docs/design/document-model.md §8)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from groundgate.canonical import jcs
from groundgate.extract import RunPolicy, RunResult, extract, replay
from groundgate.extract import structure as structure_module
from groundgate.extract.structure import propose
from groundgate.model import Schema
from groundgate.read.document import Document, read_document
from groundgate.store import FolderStore

KEYED = {
    "fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024", "2023"]}}
}
PLAIN = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"]}}}
TABLE = (
    "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
    "<tr><td>Revenue</td><td>5</td><td>4</td></tr>"
    "<tr><td>Cost</td><td>3</td><td>2</td></tr></table>"
)
TWO_COLUMNS = "<table><tr><td>Revenue</td><td>5</td></tr><tr><td>Cost</td><td>3</td></tr></table>"
CORROBORATE = {"proposers": {"structure": "corroborate"}}


def document(tmp_path: Path, html: str) -> Document:
    path = tmp_path / "doc.html"
    path.write_text(f"<html><body>{html}</body></html>", encoding="utf-8")
    return read_document(path)[1]


def found(tmp_path: Path, html: str, schema: Any = KEYED) -> list[dict[str, Any]]:
    doc = document(tmp_path, html)
    return propose(doc.text, doc, Schema.from_dict(schema))


def quiet(prompt: str) -> str:
    """A model that finds nothing."""
    fields = json.loads(prompt.split("\n", 1)[1])["fields"]
    return json.dumps({"candidates": [], "not_found": fields})


def run(
    text: Any, schema: Any = KEYED, policy: Any = CORROBORATE, client: Any = quiet
) -> RunResult:
    return extract(text, schema, client=client, model_id="fixed-1", policy=policy)


def spans(doc: Document, candidate: dict[str, Any]) -> dict[str, str]:
    data = doc.text.encode()
    return {
        item["role"]: data[item["start"] : item["end"]].decode() for item in candidate["evidence"]
    }


def test_the_module_imports_nothing_from_text_or_admit() -> None:
    assert structure_module.__file__ is not None
    tree = ast.parse(Path(structure_module.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = f"{'.' * node.level}{node.module or ''}"
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    parts = {part for name in names for part in name.split(".")}
    assert names and not parts & {"text", "admit"}


def test_a_table_cell_cites_the_value_the_row_label_and_the_header(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    out = propose(doc.text, doc, Schema.from_dict(KEYED))
    assert [(c["key"], c["value"], spans(doc, c)) for c in out] == [
        ("2024", "5", {"value": "5", "field": "Revenue", "key": "2024"}),
        ("2023", "4", {"value": "4", "field": "Revenue", "key": "2023"}),
    ]
    assert out[0]["basis"] == {"value": "markup", "field": "markup", "key": "markup"}
    assert "proposer" not in out[0] and "id" not in out[0]


def test_a_keyless_field_reads_the_one_value_in_its_row(tmp_path: Path) -> None:
    doc = document(tmp_path, TWO_COLUMNS)
    out = propose(doc.text, doc, Schema.from_dict(PLAIN))
    assert [(c["key"], c["value"], spans(doc, c)) for c in out] == [
        (None, "5", {"value": "5", "field": "Revenue"})
    ]


def test_a_label_value_line_outside_a_table() -> None:
    text = "Report\n  Revenue :  1,234 units\nCost: 3\n"
    out = propose(text, None, Schema.from_dict(PLAIN))
    assert [c["value"] for c in out] == ["1234"]
    data = text.encode()
    got = {i["role"]: data[i["start"] : i["end"]].decode() for i in out[0]["evidence"]}
    assert got == {"value": "1,234 units", "field": "Revenue"}
    assert out[0]["basis"] == {"value": "layout", "field": "layout"}


def test_a_string_field_gives_the_whole_cell(tmp_path: Path) -> None:
    schema = {"fields": {"maker": {"type": "string", "aliases": ["Maker"]}}}
    html = "<table><tr><td>Maker</td><td>Acme  Works</td></tr></table>"
    assert [c["value"] for c in found(tmp_path, html, schema)] == ["Acme Works"]


@pytest.mark.parametrize(
    "html",
    [
        pytest.param(TABLE + TABLE, id="two tables match"),
        pytest.param(
            TABLE.replace("</table>", "<tr><td>Revenue</td><td>6</td><td>7</td></tr></table>"),
            id="two rows match",
        ),
        pytest.param(TABLE.replace("<th>2023</th>", "<th>2024</th>"), id="two headers match"),
        pytest.param(TABLE.replace("<th>2024", '<th colspan="1" rowspan="2">2024'), id="span head"),
        pytest.param(
            "<table><tr><th>Item</th><th>Note</th><th>2024</th></tr>"
            '<tr><td>Revenue</td><td rowspan="2">n</td><td>5</td></tr>'
            "<tr><td>Cost</td><td>3</td></tr></table>",
            id="the row path crosses a spanned cell",
        ),
        pytest.param(
            "<table><tr><th>Item</th><th>2024</th></tr>"
            '<tr><td colspan="2">Group</td></tr>'
            "<tr><td>Revenue</td><td>5</td></tr></table>",
            id="the column path crosses a spanned cell",
        ),
        pytest.param(
            '<table><tr><th>Item</th><th>2024</th></tr><tr><td rowspan="2">Revenue</td>'
            "<td>5</td></tr><tr><td>6</td></tr></table>",
            id="the label is spanned",
        ),
        pytest.param(TABLE.replace("<td>5</td>", '<td colspan="2">5</td>'), id="the value spans"),
        pytest.param(TABLE.replace("<td>5</td>", "<td></td>"), id="the value is empty"),
        pytest.param(TABLE.replace("<td>5</td>", "<td>(5)</td>"), id="brackets"),
        pytest.param(TABLE.replace("<td>5</td>", "<td>5 and 6</td>"), id="two numbers"),
        pytest.param(TABLE.replace("<td>5</td>", "<td>none</td>"), id="no number"),
        pytest.param(TABLE.replace("<th>2024</th>", "<td>2024</td>"), id="a data cell header"),
        pytest.param(
            TABLE.replace("<td>5</td>", "<td><table><tr><td>5</td></tr></table></td>"),
            id="the value holds a table",
        ),
    ],
)
def test_no_candidate_for_2024_when_a_cell_is_not_clear(tmp_path: Path, html: str) -> None:
    assert [c for c in found(tmp_path, html) if c["key"] == "2024"] == []


def test_a_null_header_gives_nothing(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    obj = doc.to_dict()
    for node in obj["nodes"]:
        if node["kind"] == "cell":
            node["header"] = None
    null = Document.from_dict(obj, doc.text)
    assert propose(null.text, null, Schema.from_dict(KEYED)) == []
    assert propose(null.text, null, Schema.from_dict(PLAIN)) == []


@pytest.mark.parametrize(
    "html",
    [
        pytest.param(TWO_COLUMNS + TWO_COLUMNS, id="two tables"),
        pytest.param(TABLE, id="two values in the row"),
        pytest.param(TWO_COLUMNS.replace("<td>5", "<th>5"), id="a header as the value"),
        pytest.param(
            TWO_COLUMNS.replace("<td>Cost</td>", '<td rowspan="1" colspan="2">Cost</td>')
            .replace("<td>3</td>", "")
            .replace("<td>5</td>", '<td>5</td><td rowspan="2">n</td>'),
            id="a spanned cell in the row",
        ),
        pytest.param(TWO_COLUMNS + "<p>Revenue: 7</p>", id="a table and a line"),
    ],
)
def test_no_candidate_for_a_keyless_field(tmp_path: Path, html: str) -> None:
    assert found(tmp_path, html, PLAIN) == []


def test_two_fields_with_one_label_give_nothing(tmp_path: Path) -> None:
    schema = {
        "fields": {
            "a": {"type": "integer", "aliases": ["Revenue"]},
            "b": {"type": "integer", "aliases": ["Revenue"]},
        }
    }
    assert found(tmp_path, TWO_COLUMNS, schema) == []
    assert propose("Revenue: 5\n", None, Schema.from_dict(schema)) == []


def test_two_lines_a_keyed_field_and_a_table_line_give_nothing(tmp_path: Path) -> None:
    plain = Schema.from_dict(PLAIN)
    assert propose("Revenue: 5\nRevenue: 6\n", None, plain) == []
    assert propose("Revenue: 5\n", None, Schema.from_dict(KEYED)) == []
    assert propose("Revenue:\n", None, plain) == []
    assert found(tmp_path, "<table><tr><td>Revenue: 5</td></tr></table>", PLAIN) == []


def test_a_field_with_no_alias_gives_nothing(tmp_path: Path) -> None:
    schema = {"fields": {"revenue": {"type": "integer", "keys": ["2024"]}}}
    assert found(tmp_path, TABLE, schema) == []


def test_a_large_loaded_span_or_position_does_not_cost_time(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    obj = doc.to_dict()
    for node in obj["nodes"]:
        if node["kind"] == "cell" and node["column"] == 2:
            node["column"] = 2**52
        elif node["kind"] == "cell" and node["column"] == 1 and node["row"] == 2:
            node["rows"] = 2**52
    loaded = Document.from_dict(obj, doc.text)
    assert [
        c for c in propose(loaded.text, loaded, Schema.from_dict(KEYED)) if c["key"] == "2023"
    ] == []


def test_the_runner_sets_the_proposer_and_records_the_candidates(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    result = run(doc)
    assert [(c["id"], c["proposer"]) for c in result.candidates] == [
        ("s1", "structure"),
        ("s2", "structure"),
    ]
    assert [d.proposer for d in result.receipt.decisions] == ["structure", "structure"]
    line = next(e for e in result.record if e.get("phase") == "structure")
    assert line["kind"] == "admission"
    packet = json.loads(result.artifacts[line["admission_sha256"]])
    assert packet["candidates"] == result.candidates
    assert replay(result.record, result.artifacts, doc, KEYED, CORROBORATE).ok


def test_a_changed_record_does_not_replay(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    result = run(doc)
    other = document(tmp_path, TABLE.replace("<td>5</td>", "<td>6</td>"))
    assert not replay(result.record, result.artifacts, other, KEYED, CORROBORATE).ok


def test_a_run_saves_and_loads_with_the_candidates(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    result = run(doc)
    folder = tmp_path / "run"
    result.write(folder)
    assert RunResult.read(folder).candidates == result.candidates
    store = FolderStore(tmp_path / "store")
    packet = result.save(store)
    assert RunResult.load(store, packet).candidates == result.candidates


def test_a_run_reads_back_when_the_schema_order_is_not_sorted(tmp_path: Path) -> None:
    """A saved schema loads its fields in sorted order, so the candidate IDs must not follow
    the order of the schema (#510)."""
    schema = {
        "fields": {
            "z": {"type": "integer", "aliases": ["Revenue"]},
            "a": {"type": "integer", "aliases": ["Cost"]},
        }
    }
    doc = document(tmp_path, TWO_COLUMNS)
    assert [c["field"] for c in propose(doc.text, doc, Schema.from_dict(schema))] == ["a", "z"]
    result = run(doc, schema)
    folder = tmp_path / "run"
    result.write(folder)
    assert RunResult.read(folder).candidates == result.candidates


def test_a_lone_candidate_needs_verification_under_corroborate(tmp_path: Path) -> None:
    result = run(document(tmp_path, TABLE))
    for decision in result.receipt.decisions:
        assert decision.outcome == "needs_verification"
        assert decision.codes == ("NOT_CORROBORATED", "KEY_CITED")


@pytest.mark.parametrize(
    "line", ["Revenue: N/A, Cost: 5", "Revenue: N/A, Cost 5", "Revenue: 5, Cost: 4"]
)
def test_a_line_with_a_second_label_gives_nothing(line: str) -> None:
    assert propose(f"{line}\n", None, Schema.from_dict(PLAIN)) == []
    result = run(f"{line}\n", PLAIN, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("first", ["Revenue: USD 7", "Revenue: N/A, Cost: 5"])
def test_a_refused_line_still_counts_as_a_second_match(first: str) -> None:
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "unit": "USD"}}}
    for text in (f"{first}\nRevenue: 5 USD\n", f"Revenue: 5 USD\n{first}\n"):
        assert propose(text, None, Schema.from_dict(schema)) == []
        result = run(text, schema, policy=ADMIT)
        assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("tabbed", ["Revenue:\t7", "\tRevenue: 7"])
def test_a_tabbed_line_still_counts_as_a_second_match(tabbed: str) -> None:
    for text in (f"Revenue: 5\n{tabbed}\n", f"{tabbed}\nRevenue: 5\n"):
        assert propose(text, None, Schema.from_dict(PLAIN)) == []
        result = run(text, PLAIN, policy=ADMIT)
        assert not any(c.get("proposer") == "structure" for c in result.candidates)
    assert propose(f"{tabbed}\n", None, Schema.from_dict(PLAIN)) == []


def test_a_line_value_with_a_unit_after_it_keeps_its_value() -> None:
    found = propose("Revenue: 5 million, net\n", None, Schema.from_dict(PLAIN))
    assert [c["value"] for c in found] == ["5"]


def test_a_line_candidate_needs_verification_under_corroborate() -> None:
    result = run("Revenue: 5\n", PLAIN)
    assert [(d.outcome, d.codes) for d in result.receipt.decisions] == [
        ("needs_verification", ("NOT_CORROBORATED",))
    ]


def test_an_admit_policy_admits_the_candidate(tmp_path: Path) -> None:
    result = run(document(tmp_path, TABLE), policy={"proposers": {"structure": "admit"}})
    assert [d.outcome for d in result.receipt.decisions] == ["admitted", "admitted"]


def test_a_model_that_cites_the_same_cell_corroborates_it(tmp_path: Path) -> None:
    doc = document(tmp_path, TWO_COLUMNS)

    def client(prompt: str) -> str:
        item = {"source": "document", "role": "value", "text": "5"}
        label = {"source": "document", "role": "field", "text": "Revenue"}
        candidate = {
            "field": "revenue",
            "value": "5",
            "unit": None,
            "key": None,
            "evidence": [item, label],
        }
        return json.dumps({"candidates": [candidate], "not_found": []})

    result = run(doc, PLAIN, client=client)
    assert {d.candidate_id: d.outcome for d in result.receipt.decisions} == {
        "s1": "admitted",
        "c1-1": "admitted",
    }


def test_a_candidate_does_not_stop_the_search_and_no_repair_changes_it(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    prompts: list[str] = []

    def client(prompt: str) -> str:
        prompts.append(prompt)
        return quiet(prompt)

    result = run(doc, client=client)
    phases = [json.loads(p.split("\n", 1)[1])["phase"] for p in prompts]
    assert phases == ["initial", "targeted"]
    assert not any(e["kind"] == "repair" for e in result.record)
    assert all("structure" not in json.loads(p.split("\n", 1)[1])["schema"] for p in prompts)
    assert all('"s1"' not in p for p in prompts)


def test_a_model_cannot_claim_to_be_structure(tmp_path: Path) -> None:
    doc = document(tmp_path, TWO_COLUMNS)
    claim = {
        "field": "revenue",
        "value": "5",
        "unit": None,
        "key": None,
        "proposer": "structure",
        "evidence": [{"source": "document", "role": "value", "text": "5"}],
    }
    replies = [json.dumps({"candidates": [claim], "not_found": []})]

    def client(prompt: str) -> str:
        return replies.pop(0) if replies else quiet(prompt)

    result = run(doc, PLAIN, client=client)
    assert [c["id"] for c in result.candidates] == ["s1"]
    assert result.receipt.decisions[0].codes == ("NOT_CORROBORATED",)
    call = next(e for e in result.record if e["kind"] == "call")
    assert call["status"] != "ok"


@pytest.mark.parametrize(
    "policy",
    [None, {}, {"proposers": {}}, {"proposers": {"other": "corroborate"}}],
)
def test_a_run_with_no_such_policy_does_not_start_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: Any
) -> None:
    doc = document(tmp_path, TABLE)

    def stop(*_: Any) -> list[Any]:
        raise AssertionError("the reader started")

    before = run(doc, policy=policy)
    monkeypatch.setattr("groundgate.extract.runner.propose", stop)
    after = run(doc, policy=policy)
    assert before.candidates == after.candidates == []
    assert jcs(before.record) == jcs(after.record)
    assert before.artifacts == after.artifacts
    assert before.receipt.to_dict() == after.receipt.to_dict()
    assert not any(e.get("phase") == "structure" for e in after.record)


def test_a_document_with_no_match_adds_no_line(tmp_path: Path) -> None:
    doc = document(tmp_path, "<p>Nothing here.</p>")
    result = run(doc)
    assert result.candidates == []
    assert not any(e.get("phase") == "structure" for e in result.record)


def test_the_candidates_count_against_the_candidate_limit(tmp_path: Path) -> None:
    doc = document(tmp_path, TABLE)
    result = extract(
        doc,
        KEYED,
        client=quiet,
        model_id="fixed-1",
        policy=CORROBORATE,
        run_policy=RunPolicy(max_total_candidates=1),
    )
    assert not result.complete and result.candidates == []
    assert any(e.get("status") == "aggregate_candidate_limit" for e in result.record)


ROW_HEADER = "<tr><th>Metric</th><th>Related metric</th><th>2024</th></tr>"


@pytest.mark.parametrize(
    "row",
    [
        "<tr><th>Cost</th><td>Revenue</td><td>5</td></tr>",
        "<tr><td>Cost</td><td>Revenue</td><td>5</td></tr>",
        "<tr><th>Note</th><td>Revenue</td><td>5</td></tr>",
    ],
)
def test_a_label_after_a_row_header_or_a_label_is_a_data_cell(tmp_path: Path, row: str) -> None:
    """A cell that names a field after a header or a label in its row is a value, not the row
    label, so the reader proposes nothing for that field. Keyed and keyless fields both."""
    keyed = {
        "fields": {
            "revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]},
            "cost": {"type": "integer", "aliases": ["Cost"], "keys": ["2024"]},
        }
    }
    plain = {
        "fields": {
            "revenue": PLAIN["fields"]["revenue"],
            "cost": {"type": "integer", "aliases": ["Cost"]},
        }
    }
    keyed_found = found(tmp_path, f"<table>{ROW_HEADER}{row}</table>", keyed)
    assert "revenue" not in [c["field"] for c in keyed_found]
    assert "revenue" not in [c["field"] for c in found(tmp_path, f"<table>{row}</table>", plain)]
    result = extract(
        document(tmp_path, f"<table>{ROW_HEADER}{row}</table>"),
        keyed,
        client=quiet,
        model_id="fixed-1",
        policy={"proposers": {"structure": "admit"}},
    )
    assert "revenue" not in [c["field"] for c in result.candidates]


def test_the_keys_keep_the_schema_order_across_tables(tmp_path: Path) -> None:
    """Two tables give the keys of one field in the other order: the candidates follow the
    schema keys, not the tables."""
    html = (
        "<table><tr><th>Item</th><th>2023</th></tr><tr><td>Revenue</td><td>4</td></tr></table>"
        "<table><tr><th>Item</th><th>2024</th></tr><tr><td>Revenue</td><td>5</td></tr></table>"
    )
    assert [c["key"] for c in found(tmp_path, html)] == ["2024", "2023"]


@pytest.mark.parametrize("first", ["Cost", "1", "", " "])
def test_a_label_after_any_cell_is_a_data_cell(tmp_path: Path, first: str) -> None:
    """The cell before the alias names no field or is empty, so only its place shows that the
    alias is not the row label. Keyed and keyless fields both."""
    row = f"<tr><td>{first}</td><td>Revenue</td><td>5</td></tr>"
    keyed = {"fields": {"revenue": {**KEYED["fields"]["revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, f"<table>{ROW_HEADER}{row}</table>", keyed) == []
    assert found(tmp_path, f"<table>{row}</table>", PLAIN) == []
    result = extract(
        document(tmp_path, f"<table>{ROW_HEADER}{row}</table>"),
        keyed,
        client=quiet,
        model_id="fixed-1",
        policy={"proposers": {"structure": "admit"}},
    )
    assert result.candidates == []


def test_the_reader_batch_is_bound_as_one_reply(tmp_path: Path) -> None:
    """A table with more matches than one reply may hold stops the run before admission."""
    doc = document(tmp_path, TABLE)
    result = extract(
        doc,
        KEYED,
        client=quiet,
        model_id="fixed-1",
        policy=CORROBORATE,
        run_policy=RunPolicy(max_candidates_per_reply=1),
    )
    assert not result.complete and result.candidates == []
    assert any(e.get("status") == "structure_candidate_limit" for e in result.record)
    assert not any(e.get("kind") == "admission" for e in result.record)


def test_many_keyed_rows_under_one_header_each_find_their_value(tmp_path: Path) -> None:
    """The column runs give each row its value with no walk up the header column."""
    count = 300
    rows = "".join(f"<tr><td>F{i}</td><td>{i}</td></tr>" for i in range(count))
    html = f"<table><tr><th>Item</th><th>2024</th></tr>{rows}</table>"
    schema = {
        "fields": {
            f"f{i}": {"type": "integer", "aliases": [f"F{i}"], "keys": ["2024", "2023"]}
            for i in range(count)
        }
    }
    got = {c["field"]: (c["key"], c["value"]) for c in found(tmp_path, html, schema)}
    assert got == {f"f{i}": ("2024", str(i)) for i in range(count)}
    gap = html.replace("<tr><td>F5</td><td>5</td></tr>", "<tr><td>F5</td></tr>", 1)
    # A gap in the header column cuts the path for its row and each row below it.
    assert {c["field"] for c in found(tmp_path, gap, schema)} == {f"f{i}" for i in range(5)}


ADMIT = {"proposers": {"structure": "admit"}}


def test_a_loaded_span_over_the_path_gives_nothing(tmp_path: Path) -> None:
    """A loaded object can put a spanned cell over a place of the grid. No path is clear."""
    html = (
        "<table><tr><th>Item</th><th>2024</th></tr><tr><td>Revenue</td><td>5</td></tr>"
        "<tr><td>Note</td><td>other</td></tr></table>"
    )
    doc = document(tmp_path, html)
    assert [c["value"] for c in propose(doc.text, doc, Schema.from_dict(KEYED))] == ["5"]
    obj = doc.to_dict()
    for node in obj["nodes"]:
        if node["kind"] == "cell" and node["row"] == 2 and node["column"] == 1:
            node.update(row=0, rows=3)
    loaded = Document.from_dict(obj, doc.text)
    assert propose(loaded.text, loaded, Schema.from_dict(KEYED)) == []
    result = run(loaded, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


def test_a_span_beside_the_path_keeps_the_value(tmp_path: Path) -> None:
    """A spanned title above the header and a spanned cell after the value stop no path."""
    html = (
        "<table><tr><th colspan='3'>Results</th></tr>"
        "<tr><th>Item</th><th>2024</th><th rowspan='2'>Note</th></tr>"
        "<tr><td>Revenue</td><td>5</td></tr></table>"
    )
    assert [(c["key"], c["value"]) for c in found(tmp_path, html)] == [("2024", "5")]


@pytest.mark.parametrize("cell", ["<th>2023</th>", "<th></th>", "<th>Restated</th>"])
def test_a_header_between_the_header_and_the_value_gives_nothing(tmp_path: Path, cell: str) -> None:
    """A later header row starts a new header, also when the schema does not name it."""
    html = (
        "<table><tr><th>Item</th><th>2024</th></tr><tr><td>Cost</td><td>5</td></tr>"
        f"<tr><th>Item</th>{cell}</tr><tr><td>Revenue</td><td>4</td></tr></table>"
    )
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert result.receipt.decisions == [] or all(
        d.outcome != "admitted" for d in result.receipt.decisions
    )


def test_a_header_between_the_label_and_the_value_gives_nothing(tmp_path: Path) -> None:
    html = (
        "<table><tr><th>Item</th><th>Part</th><th>2024</th></tr>"
        "<tr><td>Revenue</td><th>Restated</th><td>5</td></tr></table>"
    )
    assert found(tmp_path, html) == []
    row_header = html.replace("<td>Revenue</td><th>Restated</th>", "<th>Revenue</th><td>x</td>")
    assert [(c["key"], c["value"]) for c in found(tmp_path, row_header)] == [("2024", "5")]


def test_many_keys_of_one_field_sort_with_no_scan(tmp_path: Path) -> None:
    """The sort reads the rank of each key, so a long key list costs no scan per candidate."""
    count = 3000
    head = "".join(f"<th>K{i}</th>" for i in range(count))
    cells = "".join(f"<td>{i}</td>" for i in range(count))
    html = f"<table><tr><th>Item</th>{head}</tr><tr><td>Revenue</td>{cells}</tr></table>"
    keys = [f"K{i}" for i in reversed(range(count))]
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": keys}}}
    assert [c["key"] for c in found(tmp_path, html, schema)] == keys


def test_a_header_between_the_label_and_a_keyless_value_gives_nothing(tmp_path: Path) -> None:
    html = "<table><tr><td>Revenue</td><th></th><td>5</td></tr></table>"
    assert found(tmp_path, html, PLAIN) == []
    result = run(document(tmp_path, html), PLAIN, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)
    empty = html.replace("<th></th>", "<td></td>")
    assert [c["value"] for c in found(tmp_path, empty, PLAIN)] == ["5"]


def test_a_row_header_between_the_label_and_a_keyless_value_gives_nothing(tmp_path: Path) -> None:
    html = "<table><tr><td>Revenue</td><th scope='row'>Q1</th><td>5</td></tr></table>"
    assert found(tmp_path, html, PLAIN) == []
    result = run(document(tmp_path, html), PLAIN, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize(
    "label",
    ["<table><tr><td>Revenue</td></tr></table>", "Revenue<table><tr><td>x</td></tr></table>"],
)
def test_a_table_with_a_table_in_a_cell_gives_nothing(tmp_path: Path, label: str) -> None:
    """The text of a cell with a table is not one label, so the outer table gives nothing."""
    html = (
        f"<table><tr><th>Item</th><th>2024</th></tr><tr><td>{label}</td><td>999</td></tr></table>"
    )
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


def test_a_row_header_value_gives_nothing(tmp_path: Path) -> None:
    html = (
        "<table><tr><th>Item</th><th>2024</th></tr>"
        "<tr><td>Revenue</td><th scope='row'>999</th></tr></table>"
    )
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


def test_a_row_header_label_keeps_its_value(tmp_path: Path) -> None:
    """A row header is the usual label cell, so its scope does not stop the reader."""
    row = "<tr><th scope='row'>Revenue</th><td>5</td></tr>"
    assert [c["value"] for c in found(tmp_path, f"<table>{row}</table>", PLAIN)] == ["5"]
    keyed = f"<table><tr><th>Item</th><th scope='col'>2024</th></tr>{row}</table>"
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert [c["value"] for c in found(tmp_path, keyed, schema)] == ["5"]


@pytest.mark.parametrize("row_start", [False, True])
def test_a_loaded_table_with_text_outside_its_cells_gives_nothing(
    tmp_path: Path, row_start: bool
) -> None:
    """With no node for Cost, Revenue takes its place and 5 comes under 2024."""
    html = (
        "<table><tr><th>Item</th><th>2024</th></tr>"
        "<tr><td>Cost</td><td>Revenue</td><td>5</td></tr></table>"
    )
    obj = document(tmp_path, html).to_dict()
    cost = next(n for n in obj["nodes"] if n["kind"] == "cell" and n["row"] == 1)
    obj["nodes"] = [n for n in obj["nodes"] if n is not cost]
    for node in obj["nodes"]:
        if node["id"] > cost["id"]:
            node["id"] -= 1
        if node["kind"] == "cell" and node["row"] == 1:
            node["column"] -= 1
        if row_start and node["kind"] == "row" and node["start"] == cost["start"]:
            node["start"] = cost["end"] + 1
    loaded = Document.from_dict(obj, document(tmp_path, html).text)
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert propose(loaded.text, loaded, Schema.from_dict(schema)) == []
    result = run(loaded, schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("drop", [0, 2])
def test_a_loaded_row_that_leaves_out_text_of_the_table_gives_nothing(
    tmp_path: Path, drop: int
) -> None:
    """With no node for a cell at an edge, and a row that does not hold its text, the rest of
    the row reads as "Revenue | 5"."""
    cells = ["Cost", "Revenue", "5"] if drop == 0 else ["Revenue", "5", "7"]
    html = "<table><tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr></table>"
    obj = document(tmp_path, html).to_dict()
    gone = [n for n in obj["nodes"] if n["kind"] == "cell"][drop]
    obj["nodes"] = [n for n in obj["nodes"] if n is not gone]
    for node in obj["nodes"]:
        if node["id"] > gone["id"]:
            node["id"] -= 1
        if node["kind"] == "cell" and drop == 0:
            node["column"] -= 1
        if node["kind"] == "row":
            kept = [n for n in obj["nodes"] if n["kind"] == "cell"]
            node["start"], node["end"] = kept[0]["start"], kept[-1]["end"]
    loaded = Document.from_dict(obj, document(tmp_path, html).text)
    assert propose(loaded.text, loaded, Schema.from_dict(PLAIN)) == []
    result = run(loaded, PLAIN, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("value", ["N/A, Cost: 5", "N/A, Cost 5", "Cost: 5"])
def test_a_cell_with_a_second_label_gives_nothing(tmp_path: Path, value: str) -> None:
    html = (
        "<table><tr><th>Item</th><th>2024</th></tr>"
        f"<tr><td>Revenue</td><td>{value}</td></tr></table>"
    )
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("value", ["-$5", "\u2212$5", "- 5 USD", "$5-", "\u2013 5"])
def test_a_sign_outside_the_number_gives_nothing(tmp_path: Path, value: str) -> None:
    """The sign of "-$5" is not in the number. A positive 5 is the wrong value."""
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "unit": "USD"}}}
    assert propose(f"Revenue: {value}\n", None, Schema.from_dict(schema)) == []
    html = f"<table><tr><td>Revenue</td><td>{value}</td></tr></table>"
    assert found(tmp_path, html, schema) == []
    result = run(f"Revenue: {value}\n", schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("value", ["[5]", "{5}", "\u30105\u3011", "5 [1]", "<5", "\uff085\uff09"])
def test_a_bracket_gives_nothing(tmp_path: Path, value: str) -> None:
    """In "[5]" the 5 can be a footnote mark, and in "(5)" it can be a negative number."""
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"]}}}
    assert propose(f"Revenue: {value}\n", None, Schema.from_dict(schema)) == []
    html = f"<table><tr><td>Revenue</td><td>{value}</td></tr></table>"
    assert found(tmp_path, html, schema) == []
    result = run(f"Revenue: {value}\n", schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


def test_a_sign_inside_the_number_keeps_its_value(tmp_path: Path) -> None:
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "unit": "USD"}}}
    assert [c["value"] for c in propose("Revenue: $-5\n", None, Schema.from_dict(schema))] == ["-5"]
    html = "<table><tr><td>Revenue</td><td>\u22125</td></tr></table>"
    assert [c["value"] for c in found(tmp_path, html, schema)] == ["-5"]


@pytest.mark.parametrize("on", ["td", "th"])
def test_a_cell_with_a_headers_attribute_gives_nothing(tmp_path: Path, on: str) -> None:
    """The headers attribute puts 999 under 2023 and 5 under 2024, against the grid."""
    head = '<th id="y24">2024</th><th id="y23">2023</th>'
    if on == "th":
        head = '<th id="y24" headers="y23">2024</th><th id="y23">2023</th>'
        row = "<td>5</td><td>999</td>"
    else:
        row = '<td headers="y23">999</td><td headers="y24">5</td>'
    html = f"<table><tr><th>Item</th>{head}</tr><tr><td>Revenue</td>{row}</tr></table>"
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize(
    "html",
    [
        # rowspan="0" spans the rest of the group, so Revenue is under 2024 and 5 is under 2023.
        "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
        "<tr><td rowspan='0'>Group</td><td>7</td><td>8</td></tr>"
        "<tr><td>Revenue</td><td>5</td></tr></table>",
        # Year is over both columns of its group.
        "<table><colgroup span='2'></colgroup><tr><th>Item</th>"
        "<th scope='colgroup'>Year</th><th></th></tr>"
        "<tr><td>Revenue</td><td>999</td><td>5</td></tr></table>",
        # The parser gives both attributes. A dict keeps only the last one.
        "<table><tr><th>Item</th><th scope='row' scope='col'>Year</th></tr>"
        "<tr><td>Revenue</td><td>999</td></tr></table>",
        "<table><tr><th>Item</th><th id='y'>Year</th></tr>"
        "<tr><td>Revenue</td><td headers='z' headers=''>999</td></tr></table>",
        # A headers attribute with no value is still a headers attribute.
        "<table><tr><th>Item</th><th>Year</th></tr>"
        "<tr><td>Revenue</td><td headers>999</td></tr></table>",
        # rowspan="0" past the cap of the reader: Group still covers the row of Revenue.
        "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
        "<tr><td rowspan='0'>Group</td><td>7</td><td>8</td></tr>"
        + "<tr><td>1</td><td>2</td></tr>" * 999
        + "<tr><td>Revenue</td><td>5</td></tr></table>",
        # A legal rowspan past the cap of the reader.
        "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
        "<tr><td rowspan='1001'>Group</td><td>7</td><td>8</td></tr>"
        + "<tr><td>1</td><td>2</td></tr>" * 999
        + "<tr><td>Revenue</td><td>5</td></tr></table>",
        # HTML keeps the first rowspan, so Group covers the row of Revenue.
        "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
        "<tr><td rowspan='2' rowspan='1'>Group</td><td>7</td><td>8</td></tr>"
        "<tr><td>Revenue</td><td>5</td></tr></table>",
        # A hidden cell keeps its place, so 5 is under 2023.
        "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
        "<tr><td>Revenue</td><td style='visibility:hidden'>999</td><td>5</td></tr></table>",
        # A hidden row keeps its place, so its Group cell covers the row of Revenue.
        "<table><tr><th>Item</th><th>2024</th><th>2023</th></tr>"
        "<tr style='visibility:hidden'><td rowspan='2'>Group</td><td>7</td><td>8</td></tr>"
        "<tr><td>Revenue</td><td>5</td></tr></table>",
        # Revenue heads the first column, so it is not the label of 999.
        "<table><tr><th>Item</th><th>2024</th></tr>"
        "<tr><th scope='col'>Revenue</th><td>999</td></tr>"
        "<tr><td>Cost</td><td>5</td></tr></table>",
        # The hidden cell drops the inner table. The outer table must go too, else its first
        # cell no longer holds a table.
        "<table><tr><th>Item</th><th>2024</th></tr>"
        "<tr><td><table><tr><td>Revenue</td><td style='visibility:hidden'>x</td></tr></table>"
        "</td><td>999</td></tr></table>",
    ],
    ids=[
        "rowspan zero",
        "colgroup",
        "scope twice",
        "headers twice",
        "headers no value",
        "rowspan zero long",
        "rowspan 1001",
        "rowspan twice",
        "hidden cell",
        "hidden row",
        "column scope label",
        "hidden inner cell",
    ],
)
def test_a_cell_attribute_that_the_document_cannot_keep_gives_nothing(
    tmp_path: Path, html: str
) -> None:
    schema = {
        "fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["Year", "2024"]}}
    }
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize(
    "hidden",
    ["<tr style='visibility:hidden'><td>x</td></tr>", "<tr><td hidden>x</td></tr>"],
    ids=["row", "cell"],
)
def test_the_text_of_a_dropped_table_is_not_a_line(tmp_path: Path, hidden: str) -> None:
    """A hidden part drops the cells of its table, and the table text stays in the table."""
    html = f"<table><tr><th>Revenue: 999</th></tr>{hidden}</table>"
    assert found(tmp_path, html, PLAIN) == []
    result = run(document(tmp_path, html), PLAIN, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize("change", ["columns", "rows", "row in a node"])
def test_loaded_places_that_do_not_follow_the_text_give_nothing(
    tmp_path: Path, change: str
) -> None:
    """A swap of two places makes each value cite the header of the other. No cell is clear."""
    doc = document(tmp_path, TABLE.replace(">4<", ">999<"))
    obj = doc.to_dict()
    cells = [n for n in obj["nodes"] if n["kind"] == "cell"]
    by = {(n["row"], n["column"]): n for n in cells}
    if change == "columns":
        by[1, 1]["column"], by[1, 2]["column"] = 2, 1
    elif change == "rows":
        for column in range(3):
            by[1, column]["row"], by[2, column]["row"] = 2, 1
    else:
        by[1, 2]["row"] = 3
    loaded = Document.from_dict(obj, doc.text)
    assert propose(loaded.text, loaded, Schema.from_dict(KEYED)) == []
    result = run(loaded, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)


@pytest.mark.parametrize(
    "row",
    [
        "<tr><td>Cost</td><th scope='row'>2024</th><td>5</td></tr>",
        "<tr><td>Cost</td><th>2024</th><td>5</td></tr>",
        "<tr><th scope='row'>Cost</th><th scope='row'>2024</th></tr>",
        "<tr><td>Item</td><th>2024</th></tr>",
    ],
)
def test_a_header_in_a_row_with_data_cells_is_not_a_column_header(tmp_path: Path, row: str) -> None:
    """Only a row of column headers gives column headers. A header for its row only has a null
    header, and the document keeps no scope."""
    html = f"<table>{row}<tr><td>Revenue</td><td>999</td><td>7</td></tr></table>"
    schema = {"fields": {"revenue": {"type": "integer", "aliases": ["Revenue"], "keys": ["2024"]}}}
    assert found(tmp_path, html, schema) == []
    result = run(document(tmp_path, html), schema, policy=ADMIT)
    assert not any(c.get("proposer") == "structure" for c in result.candidates)
    if "Item" in row:  # an empty corner cell keeps a row of headers
        heads = html.replace("<td>Item</td>", "<td></td>")
        assert [c["value"] for c in found(tmp_path, heads, schema)] == ["999"]
