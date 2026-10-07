from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.cli import main
from groundgate.extract import extract
from groundgate.report import render

from pdfgen import make_pdf

DOC = 'Limit: $7,000 ($8,000 at 50). <script>alert("x")</script>\fPage two: $500.'
SCHEMA: dict[str, Any] = {
    "fields": {
        "limit": {"type": "integer", "unit": "USD", "required": True},
        "limit_50": {"type": "integer", "unit": "USD"},
        "fee": {"type": "integer", "unit": "USD"},
        "other": {"type": "integer", "required": True},
    }
}


def ev(quote: str, text: str = DOC) -> dict[str, Any]:
    start = text.encode().index(quote.encode())
    return {"start": start, "end": start + len(quote.encode()), "text": quote}


CANDS: list[Any] = [
    {"id": "a", "field": "limit", "value": "7000", "unit": "USD", "evidence": ev("$7,000")},
    {"id": "b", "field": "limit_50", "value": "8000", "unit": "USD",
     "evidence": ev("$7,000 ($8,000")},
    {"id": "c", "field": "fee", "value": "5000", "unit": "USD", "evidence": ev("$500")},
    {"id": "<i>", "field": "fee", "value": "500", "unit": "USD", "evidence": {"start": 0, "end": 1,
     "text": "<b>quoted</b>"}},
    "not a candidate",
]  # fmt: skip


def page() -> str:
    receipt = gg.admit(DOC, SCHEMA, CANDS, document_id="doc <1>").to_dict()
    return render(receipt, DOC, CANDS, schema=SCHEMA)


def test_report_escapes_everything_and_runs_no_scripts() -> None:
    html = page()
    assert "<script" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    assert "<i>" not in html and "<b>quoted" not in html
    assert "default-src &#x27;none&#x27;" not in html  # the CSP itself is not escaped
    assert "default-src 'none'" in html
    assert "<title>doc &lt;1&gt;</title>" in html


def test_report_content() -> None:
    html = page()
    assert "✓ receipt verified" in html
    for code in ("VALUE_NOT_IN_EVIDENCE", "REQUIRED_FIELD_MISSING", "CANDIDATE_INVALID"):
        assert code in html
    assert "The value cannot be read from the cited text." in html
    assert html.count('class="card ') == 5
    # overlapping spans: the shared "$7,000" is split into its own segment covered by both
    assert re.search(r'<mark class="admitted" [^>]*>\$7,000</mark>', html)
    assert re.search(r'<mark class="admitted" [^>]*> \(\$8,000</mark>', html)
    assert '<span class="page" data-page=""></span>Page two' in html  # no layout, no number
    anchors = re.findall(r'<span class="anchor" id="(d\d+)">', html)
    links = re.findall(r'href="#(d\d+)"', html)
    assert sorted(anchors) == sorted(set(links)) and len(links) == 4


def test_report_shows_the_key() -> None:
    schema = {"fields": {"limit": {"type": "integer", "unit": "USD", "keys": ["<at 50>"]}}}
    cands = [{"field": "limit", "value": "8000", "unit": "USD", "key": "<at 50>",
              "evidence": ev("$8,000")}]  # fmt: skip
    html = render(gg.admit(DOC, schema, cands).to_dict(), DOC, cands, schema=schema)
    assert '<span class="unit">for &lt;at 50&gt;</span>' in html
    assert "limit = 8000 USD for &lt;at 50&gt;: " in html


def test_report_with_layout_shows_page_numbers(tmp_path: Path) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(make_pdf([[(72, 700, "Intro")], [(72, 700, "Fee: $500 per year.")]]))
    doc = extract(pdf)
    cands = [{"field": "fee", "value": "500", "unit": "USD", "evidence": ev("$500", doc.text)}]
    receipt = gg.admit(doc.text, SCHEMA, cands).to_dict()
    html = render(receipt, doc.text, cands, layout=doc.layout)
    assert "page 2 · <a" in html and "cited “$500”" in html
    assert 'data-page="page 1"' in html and 'data-page="page 2"' in html
    assert "receipt not verified" in html
    other = {"fields": {**SCHEMA["fields"], "fee": {"type": "integer", "unit": "EUR"}}}
    assert "does not match" in render(receipt, doc.text, cands, schema=other)
    assert 'data-page="page 2"' not in render(receipt, doc.text, cands)  # no layout: no numbers


def test_cli_extract_admit_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(make_pdf([[(72, 700, "Fee: $500 per year.")], []]))
    text, layout = tmp_path / "x.txt", tmp_path / "layout.json"
    assert main(["extract", str(pdf), "-o", str(text), "--layout", str(layout)]) == 0
    assert "no text layer" in capsys.readouterr().err
    doc = text.read_text(encoding="utf-8")
    schema, cands = tmp_path / "s.json", tmp_path / "c.json"
    schema.write_text(json.dumps(SCHEMA))
    cands.write_text(
        json.dumps([{"field": "fee", "value": "500", "unit": "USD", "evidence": ev("$500", doc)}])
    )
    receipt, report = tmp_path / "r.json", tmp_path / "r.html"

    class Stdin:
        buffer = __import__("io").BytesIO(doc.encode())

    monkeypatch.setattr("sys.stdin", Stdin)
    assert main(["admit", "-", str(schema), str(cands), "-o", str(receipt)]) == 0
    args = [str(receipt), str(text), str(schema), str(cands)]
    assert main(["report", *args, "--layout", str(layout), "-o", str(report)]) == 0
    html = report.read_text(encoding="utf-8")
    assert "<title>x.txt</title>" in html and "page 1 · " in html

    tampered = json.loads(receipt.read_text())
    tampered["decisions"][0]["outcome"] = "rejected"
    receipt.write_text(json.dumps(tampered))
    assert main(["report", *args]) == 1
    assert "not rendering" in capsys.readouterr().err

    other = tmp_path / "other.txt"
    other.write_text("Fee: $500 per year!")
    assert main(["extract", str(other), "--layout", str(layout)]) == 2
    receipt2 = tmp_path / "r2.json"
    assert main(["admit", str(other), str(schema), "[]", "-o", str(receipt2)]) == 2  # no file "[]"
    Path(tmp_path / "empty.json").write_text("[]")
    empty = str(tmp_path / "empty.json")
    assert main(["admit", str(other), str(schema), empty, "-o", str(receipt2)]) == 0
    assert (
        main(["report", str(receipt2), str(other), str(schema), empty, "--layout", str(layout)])
        == 2
    )
    assert "different document" in capsys.readouterr().err


def test_cli_extract_to_stdout_and_bad_pages(
    tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    (tmp_path / "a.html").write_text("<p>Café</p>", encoding="utf-8")
    assert main(["extract", str(tmp_path / "a.html")]) == 0
    assert capsysbinary.readouterr().out == "Café".encode()
    for bad in ("0", "3-1", "x"):
        with pytest.raises(SystemExit):
            main(["extract", str(tmp_path / "a.html"), "--pages", bad])


def test_report_survives_surrogates_and_unknown_outcomes() -> None:
    cands = [
        {
            "field": "fee",
            "value": "500",
            "unit": "USD",
            "evidence": {**ev("$500"), "text": "$500\ud83d"},
        }
    ]
    receipt = gg.admit(DOC, SCHEMA, cands).to_dict()
    html = render(receipt, DOC, cands)
    html.encode("utf-8")
    assert "�" in html
    receipt["decisions"][0]["outcome"] = '<b onmouseover="x">'
    html = render(receipt, DOC, cands)
    assert "Unrecognised outcome" in html and "<b onmouseover" not in html


def test_cli_rejects_ambiguous_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc, schema = tmp_path / "d.txt", tmp_path / "s.json"
    doc.write_text("Fee: $500.")
    schema.write_text(json.dumps(SCHEMA))
    for name, body in [("dup.json", '[{"field": "fee", "field": "x"}]'), ("nan.json", "[NaN]")]:
        (tmp_path / name).write_text(body)
        assert main(["admit", str(doc), str(schema), str(tmp_path / name)]) == 2
    assert "duplicate JSON key 'field'" in capsys.readouterr().err
    (tmp_path / "list.json").write_text("[1]")
    (tmp_path / "c.json").write_text("[]")
    assert (
        main(
            ["verify", str(tmp_path / "list.json"), str(doc), str(schema), str(tmp_path / "c.json")]
        )
        == 2
    )
    assert "receipt must be a JSON object" in capsys.readouterr().err
    surrogate = tmp_path / "sur.json"
    surrogate.write_text('[{"id": "\\ud83d", "field": "fee", "value": "500", "unit": "USD"}]')
    out = tmp_path / "r.json"
    assert main(["admit", str(doc), str(schema), str(surrogate), "-o", str(out)]) == 0
    assert "\\ud83d" in out.read_text()
    with pytest.raises(SystemExit):
        main(["extract", str(doc), "--pages", "3-"])


def test_report_shows_the_cited_key_span() -> None:
    text = "Single\n\nNotes:\n\nThe deduction is $15,000."
    schema = {"fields": {"d": {"type": "integer", "unit": "USD", "keys": ["single"]}}}
    cands = [{"field": "d", "value": "15000", "unit": "USD", "key": "single",
              "evidence": ev("$15,000", text), "key_evidence": ev("Single", text)}]  # fmt: skip
    html = render(gg.admit(text, schema, cands).to_dict(), text, cands, schema=schema)
    assert "key cited “Single”" in html
    assert '<a href="#k0">show key</a>' in html
    assert '<span class="anchor" id="k0"></span><mark class="key"' in html
