from __future__ import annotations

import json
import re
from html import escape
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


TABLE = (
    "Year Ended December 31, (in thousands)\n\n2025\n\n2024\n\n"
    "Revenue\n\n$\n\n46,016\n\n$\n\n434,433\n\nThe fee was $9,000."
)
TABLE_SCHEMA: dict[str, Any] = {
    "fields": {
        "rev": {"type": "integer", "unit": "USD", "keys": ["2025", "2024"],
                "aliases": ["revenue"], "multiple": True},
        "fee": {"type": "integer", "unit": "USD", "multiple": True},
    }
}  # fmt: skip
TABLE_CANDS: list[Any] = [
    {"id": "rev", "field": "rev", "key": "2025", "value": "46016000", "unit": "USD",
     "evidence": [{"text": "46,016"}, {"role": "scale", "text": "(in thousands"},
                  {"role": "field", "text": "Revenue"}, {"role": "key", "text": "2025"}]},
    {"id": "fee", "field": "fee", "value": "-9000", "unit": "USD",
     "evidence": [{"text": "$9,000"}, {"role": "sign", "text": "fee"}]},
    {"id": "known", "field": "fee", "value": "5", "unit": "USD",
     "evidence": {"source": "knowledge", "text": "The fee is $5."}},
]  # fmt: skip


def table_page() -> tuple[dict[str, Any], str]:
    receipt = gg.admit(TABLE, TABLE_SCHEMA, TABLE_CANDS).to_dict()
    html = render(receipt, TABLE, TABLE_CANDS, schema=TABLE_SCHEMA)
    return receipt, html


def n_of(receipt: dict[str, Any], cid: str) -> int:
    return next(n for n, d in enumerate(receipt["decisions"]) if d["candidate_id"] == cid)


def test_report_marks_the_parts_of_a_table_value() -> None:
    receipt, html = table_page()
    assert "✓ receipt verified" in html
    n = n_of(receipt, "rev")
    for j, (role, quote) in enumerate([("scale", "(in thousands"), ("field", "Revenue"),
                                       ("key", "2025")]):  # fmt: skip
        anchor = f'<span class="anchor" id="p{n}-{j}"></span></span>'
        assert re.search(
            re.escape(anchor) + f'<mark class="part part-admitted part-{role}" '
            f'title="{role} of rev = 46016000 USD for 2025: Admitted[^"]*">'
            + re.escape(escape(quote))
            + "</mark>",
            html,
        )
        assert f'<b>{role}</b> <span class="ok">passed</span>, cited “{escape(quote)}”' in html
        assert f'<a href="#p{n}-{j}">show</a>' in html
    assert '<p class="missing">' not in html


def test_report_marks_a_failed_part() -> None:
    receipt, html = table_page()
    n = n_of(receipt, "fee")
    assert re.search(
        f'<span class="anchor" id="p{n}-0"></span></span>'
        '<mark class="part part-failed part-needs_verification part-sign" '
        'title="sign of fee = -9000 USD: Needs verification [^"]*\\(failed\\)">fee</mark>',
        html,
    )
    assert '<b>sign</b> <span class="bad">failed</span>, cited “fee”' in html
    assert "SIGN_CITATION_INVALID" in html


def test_report_shows_an_outside_decision_and_a_missing_part() -> None:
    receipt, html = table_page()
    n = n_of(receipt, "known")
    assert receipt["decisions"][n]["evidence"] is None and receipt["decisions"][n]["parts"] == []
    assert "from the extractor's knowledge" in html
    assert "stated “The fee is $5.”" in html
    assert f'id="d{n}"' not in html and f'id="p{n}-' not in html
    cands = [{"field": "fee", "value": "-9000", "unit": "USD", "evidence": [{"text": "$9,000"}]}]
    receipt = gg.admit(TABLE, TABLE_SCHEMA, cands).to_dict()
    assert receipt["decisions"][0]["missing"] == ["sign"]
    html = render(receipt, TABLE, cands, schema=TABLE_SCHEMA)
    assert '<p class="missing">missing: sign</p>' in html
    assert '<ul class="parts">' not in html


def test_report_shows_a_reference_decision_and_verifies_its_packet() -> None:
    text = "Single filers may deduct the interest. The phase-out starts at $85,000."
    schema = {
        "fields": {
            "p": {
                "type": "integer",
                "unit": "USD",
                "keys": ["single", "married filing jointly"],
                "multiple": True,
            }
        }
    }
    ref_text = "For married filing jointly, the phase-out starts at $170,000."
    refs = [{"id": "irs <221>", "text": ref_text, "source": "https://www.irs.gov/p970"}]
    cands = [{"field": "p", "value": "170000", "unit": "USD", "key": "married filing jointly",
              "evidence": [{"source": "reference", "ref": "irs <221>", "text": "$170,000"},
                           {"source": "reference", "ref": "irs <221>", "role": "key",
                            "text": "married filing jointly"}]}]  # fmt: skip
    source = "https://www.irs.gov/p4491x"
    receipt = gg.admit(text, schema, cands, references=refs, document_source=source).to_dict()
    d = receipt["decisions"][0]
    assert d["source"] == "reference" and d["parts"][0]["passed"] is True
    html = render(receipt, text, cands, schema=schema, references=refs, document_source=source)
    assert "✓ receipt verified" in html
    assert "from reference <code>irs &lt;221&gt;</code>" in html
    assert "cited “$170,000”" in html
    assert '<b>key</b> <span class="ok">passed</span>, cited “married filing jointly”' in html
    assert "no location in the document" in html
    assert "<mark" not in html and 'id="d0"' not in html and 'href="#p0-0"' not in html
    assert "does not match" in render(receipt, text, cands, schema=schema)  # no references
    html = render(receipt, text, cands)  # no reference text: no cited text
    assert "cited" not in html and "quoted “$170,000”" in html
