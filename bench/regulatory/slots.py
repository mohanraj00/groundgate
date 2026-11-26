"""Draw the label slots of the regulatory family from the structure of each part (#641).

The owner approved five fields on 2026-11-17. A seed draws the slots of each part from its
structure only: section numbers and headings, the defined terms of a definitions section, table
captions, row positions and column headers. A draw never reads a value, except for one layout
test: a ``table_value`` cell must hold a digit, so that a number field never asks for a text
cell. The seed is the split seed of ``manifest.json``:

    uv run python bench/regulatory/slots.py --sources DIR    # writes slots.json

The script makes no model call and reads no label.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MAX_ROWS = 30  # a table_rows slot asks for a table with 2 to MAX_ROWS body rows

# field: (value kind, the slots for each part)
FIELDS: dict[str, tuple[str, int]] = {
    "section_text": ("passage", 2),
    "definition": ("passage", 1),
    "table_value": ("number", 2),
    "table_rows": ("record", 1),
    "effective_date": ("date", 1),
}
SCHEMA = {
    "section_text": {
        "type": "passage",
        "description": "The full text of the named section, without its heading and without "
        "the source note in brackets at its end.",
    },
    "definition": {
        "type": "passage",
        "description": "The definition of the named term in the named definitions section: "
        "the text after the term, to the end of its paragraph and of the paragraphs that "
        "continue it.",
    },
    "table_value": {
        "type": "number",
        "description": "The number in the named cell of the named table, with the unit or the "
        "currency that the column header or the cell states. A cell with more than one "
        "number has no value.",
    },
    "table_rows": {
        "type": "record",
        "description": "The body rows of the named table, one record for each row, with one "
        "member for each column header. An empty cell is null.",
    },
    "effective_date": {
        "type": "date",
        "formats": ["YYYY-MM-DD"],
        "description": "The date from which the named section, or the rate or fee that it "
        "sets, applies, if the section text states one. A date of a source note in brackets "
        "is not an effective date.",
    },
}


def _texts(e: ET.Element) -> list[str]:
    out = [" "] if e.tag.lower() == "br" else []  # a line break in a header is a space
    out.append(e.text or "")
    for c in e:
        out += _texts(c)
        out.append(c.tail or "")
    return out


def text_of(e: ET.Element) -> str:
    return " ".join("".join(_texts(e)).split())


def rank(seed: str, *key: str) -> str:
    return hashlib.sha256("\n".join((seed, *key)).encode()).hexdigest()


def draw(seed: str, doc: str, field: str, items: list[dict[str, Any]], k: int) -> list[dict]:
    order = sorted(items, key=lambda it: rank(seed, doc, field, it["key"]))
    return order[:k]


def sections(root: ET.Element) -> list[ET.Element]:
    return [
        d
        for d in root.iter()
        if d.get("TYPE") == "SECTION"
        and d.find("HEAD") is not None
        and "[Reserved]" not in text_of(d.find("HEAD"))  # type: ignore[arg-type]
    ]


def head(sec: ET.Element) -> str:
    return text_of(sec.find("HEAD"))  # type: ignore[arg-type]


def table_name(table: ET.Element, number: int, section: str) -> str:
    caption = table.find("CAPTION")
    name = text_of(caption) if caption is not None else ""
    return name or f"table {number} of {section}"


def grid(rows: list[ET.Element], tag: str) -> list[list[str]]:
    """The text of each cell of ``rows`` on a grid, with rowspan and colspan filled in."""
    out: list[list[str]] = []
    carry: dict[int, tuple[int, str]] = {}  # column: (rows left, text)
    for tr in rows:
        line: list[str] = []
        cells = list(tr.findall(tag))
        col = 0
        while cells or any(c >= col for c in carry):
            if col in carry:
                left, txt = carry[col]
                line.append(txt)
                carry[col] = (left - 1, txt)
                if left - 1 == 0:
                    del carry[col]
                col += 1
                continue
            if not cells:
                break
            c = cells.pop(0)
            txt = text_of(c)
            span = int(c.get("colspan", "1") or 1)
            down = int(c.get("rowspan", "1") or 1)
            for _ in range(span):
                line.append(txt)
                if down > 1:
                    carry[col] = (down - 1, txt)
                col += 1
        out.append(line)
    return out


def tables(root: ET.Element) -> list[dict[str, Any]]:
    """Each table with a name, its column headers and its body grid. A table whose header
    and body widths differ is left out."""
    found = []
    for sec in sections(root):
        for n, t in enumerate(sec.iter("TABLE"), 1):
            name = table_name(t, n, head(sec))
            hrows = [tr for th in t.findall("THEAD") for tr in th.findall("TR")]
            brows = [tr for tb in t.findall("TBODY") for tr in tb.findall("TR")]
            hg, bg = grid(hrows, "TH"), grid(brows, "TD")
            if not hg or not bg:
                continue
            width = len(hg[-1])
            if any(len(r) != width for r in hg) or any(len(r) != width for r in bg):
                continue
            cols = []
            for c in range(width):
                parts: list[str] = []
                for r in hg:
                    if r[c] and (not parts or parts[-1] != r[c]):
                        parts.append(r[c])
                cols.append(" / ".join(parts) or f"column {c + 1}")
            found.append({"section": head(sec), "name": name, "columns": cols, "body": bg})
    return found


def definitions(root: ET.Element) -> list[dict[str, Any]]:
    out = []
    for sec in sections(root):
        if not re.search(r"definition|meaning of terms", head(sec), re.I):
            continue
        for p in sec.iter("P"):
            first = next(iter(p), None)
            if first is None or first.tag != "I" or (p.text or "").strip():
                continue
            term = text_of(first).rstrip(".,:; ")
            if term:
                out.append({"key": f"{head(sec)}\n{term}", "section": head(sec), "term": term})
    return out


def slots_of(doc: str, raw: bytes, seed: str) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    secs = [{"key": head(s), "section": head(s)} for s in sections(root)]
    tabs = tables(root)
    cells, whole = [], []
    for t in tabs:
        rows = t["body"]
        if 2 <= len(rows) <= MAX_ROWS:
            whole.append({"key": f"{t['section']}\n{t['name']}", **t})
        for i, row in enumerate(rows):
            label = next((c for c in row if c), "")
            for j in range(1, len(row)):
                if label and re.search(r"\d", row[j]) and row[j] != label:
                    cells.append({
                        "key": f"{t['section']}\n{t['name']}\n{i}\n{j}", "section": t["section"],
                        "table": t["name"], "row": i + 1, "row_label": label[:160],
                        "column": t["columns"][j],
                    })  # fmt: skip
    pools = {
        "section_text": secs,
        "definition": definitions(root),
        "table_value": cells,
        "table_rows": whole,
        "effective_date": secs,
    }
    out = []
    for field, (kind, k) in FIELDS.items():
        for it in draw(seed, doc, field, pools[field], k):
            req = {x: v for x, v in it.items() if x not in ("key", "body")}
            out.append({"id": doc, "field": field, "kind": kind, "request": req})
    return out


def request_text(s: dict[str, Any]) -> str:
    r = s["request"]
    if s["field"] in ("section_text", "effective_date"):
        what = "The text of" if s["field"] == "section_text" else "The effective date of"
        return f"{what} {r['section']}"
    if s["field"] == "definition":
        return f"The definition of the term “{r['term']}” in {r['section']}"
    if s["field"] == "table_value":
        where = r["table"] if r["section"] in r["table"] else f"{r['table']} ({r['section']})"
        return (
            f"The number in {where}, body row {r['row']} "
            f"(first cell: “{r['row_label']}”), column “{r['column']}”"
        )
    cols = "; ".join(f"“{c}”" for c in r["columns"])
    where = r["name"] if r["section"] in r["name"] else f"{r['name']} ({r['section']})"
    return f"The body rows of {where}, with the members {cols}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sources", type=Path, required=True, help="the XML of sources.py")
    args = ap.parse_args(argv)
    manifest = json.loads((HERE / "manifest.json").read_text())
    seed = manifest["split_rule"]["seed"]
    slots = []
    for d in manifest["documents"]:
        raw = (args.sources / f"{d['id']}.xml").read_bytes()
        if "sha256:" + hashlib.sha256(raw).hexdigest() != d["source_sha256"]:
            ap.error(f"{d['id']}: the XML is not the pinned source")
        for s in slots_of(d["id"], raw, seed):
            slots.append({"split": d["split"], **s, "request_text": request_text(s)})
    for n, s in enumerate(slots, 1):
        s["slot"] = f"r{n:03d}"
    out = {
        "format": "regulatory-slots/1",
        "seed": seed,
        "draw": "for each part and field, the candidates with the lowest sha256 of seed, id, "
        "field and the candidate key, one a line with LF",
        "schema": SCHEMA,
        "slots": [{"slot": s.pop("slot"), **s} for s in slots],
    }
    (HERE / "slots.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    by: dict[str, int] = {}
    for s in slots:
        by[f"{s['split']} {s['field']}"] = by.get(f"{s['split']} {s['field']}", 0) + 1
    print(len(slots), "slots", json.dumps(by, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
