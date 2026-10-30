"""DOCX and XLSX with the standard library (#529). Each file is built here, never downloaded."""

from __future__ import annotations

import io
import struct
import zipfile
from pathlib import Path

import pytest

from groundgate.cli import main
from groundgate.read import ReadError, office, read
from groundgate.read.document import read_document

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"


def _rels(*rels: tuple[str, str, str]) -> str:
    items = "".join(
        f'<Relationship Id="{i}" Type="{R}/{t}" Target="{target}"/>' for i, t, target in rels
    )
    return f'<?xml version="1.0"?><Relationships xmlns="{PKG}">{items}</Relationships>'


def _zip(members: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def docx(
    body: str, styles: str | None = None, extra: dict[str, str | bytes] | None = None
) -> bytes:
    members: dict[str, str | bytes] = {
        "[Content_Types].xml": "<Types/>",
        "_rels/.rels": _rels(("rId1", "officeDocument", "word/document.xml")),
        "word/document.xml": (
            f'<w:document xmlns:w="{W}" xmlns:mc="{MC}"><w:body>{body}</w:body></w:document>'
        ),
    }
    if styles is not None:
        members["word/_rels/document.xml.rels"] = _rels(("rId1", "styles", "styles.xml"))
        members["word/styles.xml"] = f'<w:styles xmlns:w="{W}">{styles}</w:styles>'
    return _zip(members | (extra or {}))


def xlsx(sheets: list[tuple[str, str, str]], shared: list[str] | None = None) -> bytes:
    """``sheets`` holds the name, the state and the inner XML of each worksheet."""
    rels = [
        (f"rId{i + 1}", "worksheet", f"worksheets/sheet{i + 1}.xml") for i in range(len(sheets))
    ]
    members: dict[str, str | bytes] = {
        "[Content_Types].xml": "<Types/>",
        "_rels/.rels": _rels(("rId1", "officeDocument", "xl/workbook.xml")),
    }
    if shared is not None:
        rels.append(("rIdS", "sharedStrings", "sharedStrings.xml"))
        items = "".join(f"<si>{s if s.startswith('<r>') else f'<t>{s}</t>'}</si>" for s in shared)
        members["xl/sharedStrings.xml"] = f'<sst xmlns="{X}">{items}</sst>'
    members["xl/_rels/workbook.xml.rels"] = _rels(*rels)
    entries = "".join(
        f'<sheet name="{name}" sheetId="{i + 1}" state="{state}" r:id="rId{i + 1}"/>'
        for i, (name, state, _) in enumerate(sheets)
    )
    members["xl/workbook.xml"] = (
        f'<workbook xmlns="{X}" xmlns:r="{R}"><sheets>{entries}</sheets></workbook>'
    )
    for i, (_, _, inner) in enumerate(sheets):
        members[f"xl/worksheets/sheet{i + 1}.xml"] = f'<worksheet xmlns="{X}">{inner}</worksheet>'
    return _zip(members)


def _p(text: str, ppr: str = "", rpr: str = "") -> str:
    run = f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{run}</w:p>"


def _tc(text: str, tcpr: str = "") -> str:
    return f"<w:tc><w:tcPr>{tcpr}</w:tcPr>{_p(text)}</w:tc>"


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _nodes(path: Path) -> tuple[str, list[dict[str, object]]]:
    extracted, doc = read_document(path)
    assert read(path).text == extracted.text
    data = extracted.text.encode("utf-8")
    out = []
    for n in doc.nodes:
        d = n.to_dict()
        d["text"] = data[n.start : n.end].decode("utf-8")
        out.append(d)
    return extracted.text, out


STYLES = (
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Kop2"><w:name w:val="heading 2"/></w:style>'
    '<w:style w:type="character" w:styleId="Heading1Char">'
    '<w:name w:val="heading 1 Char"/></w:style>'
)


def test_docx(tmp_path: Path) -> None:
    num = '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="3"/></w:numPr>'
    body = (
        _p("Dosage", '<w:pStyle w:val="Heading1"/>')
        + _p("Adults", '<w:pStyle w:val="Kop2"/>')
        + _p("Start at 500 mg.")
        + _p("one", num)
        + _p("two", num)
        + _p("not numbered", '<w:numPr><w:numId w:val="0"/></w:numPr>')
        + _p("Outline", '<w:outlineLvl w:val="2"/>')
    )
    text, nodes = _nodes(_write(tmp_path, "a.docx", docx(body, STYLES)))
    assert text == "Dosage\n\nAdults\n\nStart at 500 mg.\n\none\n\ntwo\n\nnot numbered\n\nOutline"
    shape = [(n["kind"], n.get("level"), n["parent"], n["text"]) for n in nodes]
    assert shape == [
        ("heading", 1, None, "Dosage"),
        ("heading", 2, None, "Adults"),
        ("paragraph", None, None, "Start at 500 mg."),
        ("list", None, None, "one\n\ntwo"),
        ("item", None, 3, "one"),
        ("item", None, 3, "two"),
        ("paragraph", None, None, "not numbered"),
        ("heading", 3, None, "Outline"),
    ]
    assert {n["basis"] for n in nodes} == {"markup"}


def test_docx_runs(tmp_path: Path) -> None:
    runs = (
        '<w:p><w:r><w:t>10</w:t></w:r><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
        "<w:t>9</w:t></w:r><w:r><w:t>5 cells</w:t></w:r>"
        "<w:r><w:rPr><w:vanish/></w:rPr><w:t>hidden</w:t></w:r>"
        '<w:r><w:rPr><w:vanish w:val="0"/></w:rPr><w:t> shown</w:t></w:r>'
        "<w:r><w:instrText>PAGE \\* MERGEFORMAT</w:instrText></w:r>"
        "<w:r><w:delText>deleted</w:delText></w:r>"
        "<w:r><w:tab/><w:t>after tab</w:t><w:br/><w:t>next line</w:t></w:r>"
        "<mc:AlternateContent><mc:Choice><w:r><w:t> choice</w:t></w:r></mc:Choice>"
        "<mc:Fallback><w:r><w:t> fallback</w:t></w:r></mc:Fallback></mc:AlternateContent>"
        "</w:p>"
    )
    text, _ = _nodes(_write(tmp_path, "r.docx", docx(runs)))
    assert text == "10^9 5 cells shown after tab\nnext line choice"


def test_docx_text_box_gives_text_and_no_inner_node(tmp_path: Path) -> None:
    box = (
        "<w:p><w:r><w:t>Before</w:t></w:r><w:r><w:pict><w:txbxContent>"
        + _p("In the box", '<w:pStyle w:val="Heading1"/>')
        + "</w:txbxContent></w:pict></w:r><w:r><w:t>after</w:t></w:r></w:p>"
    )
    text, nodes = _nodes(_write(tmp_path, "b.docx", docx(box, STYLES)))
    assert text == "Before\nIn the box\nafter"
    assert [n["kind"] for n in nodes] == ["paragraph"]


def test_docx_table(tmp_path: Path) -> None:
    header = "<w:trPr><w:tblHeader/></w:trPr>"
    span, restart = '<w:gridSpan w:val="2"/>', '<w:vMerge w:val="restart"/>'
    table = (
        "<w:tbl>"
        f"<w:tr>{header}{_tc('Dose', span)}{_tc('Note')}</w:tr>"
        f"<w:tr>{_tc('500', restart)}{_tc('mg')}{_tc('a')}</w:tr>"
        f"<w:tr>{_tc('', '<w:vMerge/>')}{_tc('g')}{_tc('b')}</w:tr>"
        f'<w:tr><w:trPr><w:gridBefore w:val="1"/></w:trPr>{_tc("x")}{_tc("y")}</w:tr>'
        "</w:tbl>"
    )
    text, nodes = _nodes(_write(tmp_path, "t.docx", docx(_p("Table 1") + table + _p("End"))))
    assert text == "Table 1\n\nDose\tNote\n500\tmg\ta\ng\tb\nx\ty\n\nEnd"
    cells = [
        (n["text"], n["row"], n["column"], n["rows"], n["columns"], n["header"])
        for n in nodes
        if n["kind"] == "cell"
    ]
    assert cells == [
        ("Dose", 0, 0, 1, 2, True),
        ("Note", 0, 2, 1, 1, True),
        ("500", 1, 0, 2, 1, None),
        ("mg", 1, 1, 1, 1, None),
        ("a", 1, 2, 1, 1, None),
        ("g", 2, 1, 1, 1, None),
        ("b", 2, 2, 1, 1, None),
        ("x", 3, 1, 1, 1, None),
        ("y", 3, 2, 1, 1, None),
    ]
    kinds = [n["kind"] for n in nodes]
    assert kinds[:3] == ["paragraph", "table", "row"] and kinds[-1] == "paragraph"
    assert sum(k == "row" for k in kinds) == 4


def test_docx_nested_table_and_list_in_cell(tmp_path: Path) -> None:
    num = '<w:numPr><w:numId w:val="1"/></w:numPr>'
    inner = f"<w:tbl><w:tr>{_tc('in')}</w:tr></w:tbl>"
    table = f"<w:tbl><w:tr><w:tc>{_p('one', num)}{_p('two', num)}{inner}</w:tc></w:tr></w:tbl>"
    _, nodes = _nodes(_write(tmp_path, "n.docx", docx(table)))
    shape = [(n["kind"], n["parent"]) for n in nodes]
    assert shape == [
        ("table", None),
        ("row", 0),
        ("cell", 1),
        ("list", 2),
        ("item", 3),
        ("item", 3),
        ("table", 2),
        ("row", 6),
        ("cell", 7),
        ("paragraph", 8),
    ]


def test_xlsx(tmp_path: Path) -> None:
    sheet1 = (
        '<cols><col min="4" max="5" hidden="1"/></cols><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
        '<c r="D1"><v>9</v></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Café</t><rPh><t>kana</t></rPh></is></c>'
        '<c r="B2"><v>1234.5</v></c><c r="C2" t="b"><v>1</v></c></row>'
        '<row r="3" hidden="1"><c r="A3"><v>hidden row</v></c></row>'
        '<row r="5"><c r="A5" t="str"><f>A1</f><v>Total</v></c><c r="C5" t="e"><v>#DIV/0!</v></c>'
        '<c r="F5"><v></v></c></row>'
        '</sheetData><mergeCells><mergeCell ref="A5:B6"/></mergeCells>'
    )
    hidden = '<sheetData><row r="1"><c r="A1"><v>secret</v></c></row></sheetData>'
    empty = "<sheetData/>"
    path = _write(
        tmp_path,
        "s.xlsx",
        xlsx(
            [("Doses", "visible", sheet1), ("Old", "hidden", hidden), ("Blank", "visible", empty)],
            shared=["Drug", "Dose"],
        ),
    )
    text, nodes = _nodes(path)
    assert text == "Doses\n\nDrug\tDose\nCafé\t1234.5\tTRUE\nTotal\t#DIV/0!"
    assert [(n["kind"], n["parent"]) for n in nodes[:3]] == [
        ("heading", None),
        ("table", None),
        ("row", 1),
    ]
    assert nodes[0]["level"] == 1 and nodes[0]["text"] == "Doses"
    cells = [
        (n["text"], n["row"], n["column"], n["rows"], n["columns"])
        for n in nodes
        if n["kind"] == "cell"
    ]
    assert cells == [
        ("Drug", 0, 0, 1, 1),
        ("Dose", 0, 1, 1, 1),
        ("Café", 1, 0, 1, 1),
        ("1234.5", 1, 1, 1, 1),
        ("TRUE", 1, 2, 1, 1),
        ("Total", 4, 0, 2, 2),
        ("#DIV/0!", 4, 2, 1, 1),
    ]


def test_cli_reads_docx(tmp_path: Path) -> None:
    path = _write(tmp_path, "c.docx", docx(_p("Start at 500 mg.")))
    out = tmp_path / "c.txt"
    assert main(["read", str(path), "-o", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "Start at 500 mg."


def test_empty_docx_warns(tmp_path: Path) -> None:
    extracted = read(_write(tmp_path, "e.docx", docx("")))
    assert extracted.text == "" and extracted.warnings == ("e.docx: no text was extracted",)


# Untrusted input


def test_zip_bomb_is_refused_before_it_expands(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("_rels/.rels", _rels(("rId1", "officeDocument", "word/document.xml")))
        with z.open("word/document.xml", "w", force_zip64=True) as f:
            chunk = b"\0" * 2**20
            for _ in range(office.MAX_EXPANDED // len(chunk) + 1):
                f.write(chunk)
    data = buf.getvalue()
    assert len(data) < 2**20  # a small file that expands past the limit
    with pytest.raises(ReadError, match="expanded size is larger"):
        read(_write(tmp_path, "bomb.docx", data))


def test_a_member_never_reads_past_the_limit(tmp_path: Path) -> None:
    z = office._Zip(docx(_p("x" * 100)), tmp_path / "x.docx")
    z.left = 50
    with pytest.raises(ReadError, match="expanded size is larger"):
        z.read("word/document.xml")


def _set_size(data: bytearray, name: bytes, size: int) -> None:
    """Write ``size`` as the expanded size of ``name`` in its local and its central header."""
    for sig, at, length, start in ((b"PK\x03\x04", 22, 26, 30), (b"PK\x01\x02", 24, 28, 46)):
        i = data.find(sig)
        while i >= 0:
            n = struct.unpack_from("<H", data, i + length)[0]
            if data[i + start : i + start + n] == name:
                struct.pack_into("<I", data, i + at, size)
            i = data.find(sig, i + 4)


def test_a_size_header_that_lies_is_refused(tmp_path: Path) -> None:
    data = bytearray(docx(_p("Start at 500 mg." * 50)))
    _set_size(data, b"word/document.xml", 10)
    with pytest.raises(ReadError, match="cannot read the member"):
        read(_write(tmp_path, "lie.docx", bytes(data)))


def test_too_many_members(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office, "MAX_MEMBERS", 3)
    data = docx(_p("x"), extra={"a.xml": "<a/>", "b.xml": "<b/>"})
    with pytest.raises(ReadError, match="more than 3 members"):
        read(_write(tmp_path, "m.docx", data))


def test_too_large_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(office, "MAX_FILE", 100)
    with pytest.raises(ReadError, match="larger than 100 bytes"):
        read(_write(tmp_path, "big.docx", docx(_p("x"))))


@pytest.mark.parametrize(
    "name", ["../evil.xml", "/abs.xml", "word/../../evil.xml", "C:/evil.xml", "a\\..\\b.xml"]
)
def test_a_member_outside_the_archive_is_refused(tmp_path: Path, name: str) -> None:
    data = docx(_p("x"), extra={name: "<a/>"})
    with pytest.raises(ReadError, match="outside the archive"):
        read(_write(tmp_path, "o.docx", data))


def test_a_duplicate_member_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO(docx(_p("x")))
    with pytest.warns(UserWarning), zipfile.ZipFile(buf, "a") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"/>')
    with pytest.raises(ReadError, match="two times"):
        read(_write(tmp_path, "d.docx", buf.getvalue()))


ENTITY_CASES = [
    # an internal entity, and the billion laughs
    f'<!DOCTYPE d [<!ENTITY a "500 mg">]><w:document xmlns:w="{W}"><w:body>&a;</w:body>'
    "</w:document>",
    '<!DOCTYPE d [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;">]>'
    f'<w:document xmlns:w="{W}"><w:body>&c;</w:body></w:document>',
    # an external entity and an external DTD
    '<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
    f'<w:document xmlns:w="{W}">&x;</w:document>',
    f'<!DOCTYPE d SYSTEM "http://example.invalid/d.dtd"><w:document xmlns:w="{W}"/>',
    '<!DOCTYPE d [<!ENTITY % p SYSTEM "http://example.invalid/p.dtd"> %p;]><d/>',
]


@pytest.mark.parametrize("xml", ENTITY_CASES)
def test_doctype_and_entities_are_refused(tmp_path: Path, xml: str) -> None:
    data = docx("", extra={"word/document.xml": xml})
    with pytest.raises(ReadError, match="DOCTYPE or an entity"):
        read(_write(tmp_path, "x.docx", data))


def test_entity_in_a_relationship_part_is_refused(tmp_path: Path) -> None:
    rels = '<!DOCTYPE r [<!ENTITY t "word/document.xml">]>' + _rels(
        ("rId1", "officeDocument", "&t;")
    )
    data = docx(_p("x"), extra={"_rels/.rels": rels})
    with pytest.raises(ReadError, match="DOCTYPE or an entity"):
        read(_write(tmp_path, "x.docx", data))


def test_deep_xml_is_refused(tmp_path: Path) -> None:
    deep = "<w:p>" * (office.MAX_XML_DEPTH + 1) + "</w:p>" * (office.MAX_XML_DEPTH + 1)
    with pytest.raises(ReadError, match="deeper than"):
        read(_write(tmp_path, "deep.docx", docx(deep)))


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not a zip file",
        docx(_p("x"))[:-30],  # the central directory is cut
        _zip({"[Content_Types].xml": "<Types/>"}),  # no main part
        _zip({"_rels/.rels": _rels(("rId1", "officeDocument", "word/document.xml"))}),
        docx("", extra={"word/document.xml": "<w:document><unclosed>"}),
        docx("", extra={"_rels/.rels": "<Relationships"}),
    ],
)
def test_a_malformed_file_is_refused(tmp_path: Path, data: bytes) -> None:
    with pytest.raises(ReadError):
        read(_write(tmp_path, "bad.docx", data))
    with pytest.raises(ReadError):
        read(_write(tmp_path, "bad.xlsx", data))


def test_a_corrupt_member_is_refused(tmp_path: Path) -> None:
    data = bytearray(docx(_p("Start at 500 mg." * 20)))
    i = data.index(b"word/document.xml") + len("word/document.xml")
    data[i + 5 : i + 25] = b"\xff" * 20  # the deflated bytes of the first member after its name
    with pytest.raises(ReadError):
        read(_write(tmp_path, "corrupt.docx", bytes(data)))


def test_an_unknown_compression_is_refused(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_BZIP2) as z:
        z.writestr("_rels/.rels", _rels(("rId1", "officeDocument", "word/document.xml")))
        z.writestr("word/document.xml", f'<w:document xmlns:w="{W}"/>')
    with pytest.raises(ReadError, match="unknown compression"):
        read(_write(tmp_path, "bz.docx", buf.getvalue()))


def test_xlsx_bad_shared_string_index_gives_no_text(tmp_path: Path) -> None:
    sheet = (
        '<sheetData><row r="1"><c r="A1" t="s"><v>7</v></c><c r="B1" t="s"><v>x</v></c>'
        '<c r="C1"><v>3</v></c></row></sheetData>'
    )
    text, _ = _nodes(_write(tmp_path, "i.xlsx", xlsx([("S", "visible", sheet)], shared=["a"])))
    assert text == "S\n\n3"


def test_docx_hidden_and_script_runs_from_styles(tmp_path: Path) -> None:
    styles = (
        '<w:docDefaults><w:rPrDefault><w:rPr><w:vanish w:val="0"/></w:rPr></w:rPrDefault>'
        "</w:docDefaults>"
        '<w:style w:type="character" w:styleId="Hidden"><w:rPr><w:vanish/></w:rPr></w:style>'
        '<w:style w:type="character" w:styleId="Secret"><w:basedOn w:val="Hidden"/></w:style>'
        '<w:style w:type="character" w:styleId="Sup">'
        '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Draft"><w:rPr><w:vanish/></w:rPr></w:style>'
        '<w:style w:type="character" w:styleId="Loop"><w:basedOn w:val="Loop"/></w:style>'
    )

    def run(text: str, rpr: str = "") -> str:
        return f'<w:r><w:rPr>{rpr}</w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'

    body = (
        "<w:p>"
        + run("500 mg")
        + run(" hidden", '<w:rStyle w:val="Hidden"/>')
        + run(" based", '<w:rStyle w:val="Secret"/>')
        + run(" shown", '<w:rStyle w:val="Hidden"/><w:vanish w:val="0"/>')
        + run(" loop", '<w:rStyle w:val="Loop"/>')
        + run(" 10")
        + run("9", '<w:rStyle w:val="Sup"/>')
        + run("5", '<w:rStyle w:val="Sup"/><w:vertAlign w:val="baseline"/>')
        + "</w:p>"
        + '<w:p><w:pPr><w:pStyle w:val="Draft"/></w:pPr>'
        + run("draft")
        + run(" kept", '<w:vanish w:val="false"/>')
        + "</w:p>"
    )
    text, _ = _nodes(_write(tmp_path, "h.docx", docx(body, styles)))
    assert text == "500 mg shown loop 10^9 5\n\nkept"


def test_docx_document_default_hides_runs(tmp_path: Path) -> None:
    styles = (
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault></w:docDefaults>"
    )
    text, _ = _nodes(
        _write(
            tmp_path, "d.docx", docx(_p("gone") + _p("seen", rpr='<w:vanish w:val="0"/>'), styles)
        )
    )
    assert text == "seen"


def test_xlsx_rich_text_marks_scripts(tmp_path: Path) -> None:
    sup = '<r><rPr><vertAlign val="superscript"/></rPr><t>9</t></r>'
    sub = '<r><rPr><vertAlign val="subscript"/></rPr><t>2</t></r>'
    inline = f"<is><r><t>10</t></r>{sup}<r><t>5 cells</t></r></is>"
    sheet = (
        f'<sheetData><row r="1"><c r="A1" t="inlineStr">{inline}</c>'
        '<c r="B1" t="s"><v>0</v></c></row></sheetData>'
    )
    shared = [f"<r><t>CO</t></r>{sub}"]
    text, _ = _nodes(_write(tmp_path, "r.xlsx", xlsx([("S", "visible", sheet)], shared=shared)))
    assert text == "S\n\n10^9 5 cells\tCO_2"
