"""The label slots and the blind label passes of the 1.0 release set (#748).

The method is the method of ``bench/regulatory/passes.py``, which the owner approved on
2026-11-17, with one change of input: a member is one PDF, so a pass gets the reader text of the
whole PDF in place of the XML of a section.

- Each member gets one slot for each field of its kind: 4 slots for each member, 360 in all. No
  seed draws a slot, because each field rule names one value.
- Pass ``a`` is Claude Code and pass ``b`` is Codex, with the commands of ``passes.py``. Each
  pass gets, for each member, its slots, the field rules and the reader text of the PDF.
  Nothing else goes in.
- Each slot that a pass marks absent gets a second blind check by a new agent of the other
  harness.
- ``passes.py compare`` writes the agreements and the disagreements. The owner decides each
  disagreement on the page of ``decide``. ``passes.py seal`` writes ``labels.json``.

    uv run python bench/release1/labels.py slots
    uv run python bench/release1/labels.py run --pass a --sources DIR --work WORK
    uv run python bench/release1/labels.py run --pass b --sources DIR --work WORK
    uv run python bench/release1/labels.py run --pass absence --sources DIR --work WORK
    uv run python bench/regulatory/passes.py compare --work WORK --set bench/release1
    uv run python bench/release1/labels.py decide --sources DIR --work WORK
    uv run python bench/regulatory/passes.py seal --work WORK --set bench/release1

DIR is the ``--out`` folder of ``sources.py``. WORK is local work storage. The answers stay
there until the owner decides the disagreements. ``slots`` makes no model call and reads no
document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "regulatory"))
import passes  # noqa: E402  (bench/regulatory/passes.py)

SYSTEM = "You label values in public documents. Answer only from the text you are given."
NOUN = {
    "minerals": "a chapter of the USGS Mineral Commodity Summaries 2026",
    "opinions": "an opinion of a US court of appeals",
    "reports": "a committee report of Congress",
}
# kind: field: (value kind, field rule), as the owner approved them on 2026-11-27
FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "minerals": {
        "us_production": (
            "number",
            'The first production value of the latest year in the table "Salient Statistics, '
            'United States", with the unit of the table. Absent if the table withholds the '
            "value (W) or gives none.",
        ),
        "world_reserves": (
            "number",
            'The world total of the reserves column in the table "World Mine Production and '
            'Reserves", with its unit. Absent if the table states no world total.',
        ),
        "events_trends": (
            "passage",
            'The full text of the section "Events, Trends, and Issues".',
        ),
        "salient_statistics": (
            "record",
            'The rows of the table "Salient Statistics, United States", one record for each '
            "row, with the member `item` and one member for each year column.",
        ),
    },
    "opinions": {
        "decision_date": (
            "date",
            "The date on which the court filed or decided the opinion, as the opinion states it.",
        ),
        "disposition": (
            "passage",
            "The last paragraph of the opinion of the court that states its disposition (for "
            "example affirmed, reversed or remanded).",
        ),
        "award_amount": (
            "number",
            "The one sum of money that the judgment awards or affirms, with its currency. If the "
            "opinion states no such sum, or more than one, the field is absent.",
        ),
        "panel": (
            "record",
            "The judges of the panel that the caption or the first page names, one record for "
            "each, with the members `name` and `role` (author, concurring or dissenting; null "
            "if not stated).",
        ),
    },
    "reports": {
        "report_date": (
            "date",
            "The date on which the report was submitted or ordered printed, as its first page "
            "states it.",
        ),
        "purpose": (
            "passage",
            "The text of the section on the purpose and summary of the bill.",
        ),
        "cbo_total": (
            "number",
            "The total of the CBO cost estimate over its full period, in the unit that the table "
            "states. Absent if the report has no CBO estimate.",
        ),
        "cbo_table": (
            "record",
            "The rows of the CBO table of estimated budgetary effects, one record for each row, "
            "with one member for each column header. Absent if the report has no such table.",
        ),
    },
}
SCHEMA = {f: {"type": t, "description": d} for k in FIELDS.values() for f, (t, d) in k.items()}

ANSWER = """\
Answer with one JSON object and nothing else:

{"slots": [{"slot": "l001", "status": "value" or "absent", "value": ..., "unit": ...,
  "quote": "...", "note": "..."}]}

Give one entry for each slot, in the order of the slots.

- "absent": the document does not state the value that the field rule names. Then "value",
  "unit" and "quote" are null. Never guess and never calculate a value.
- A passage: "value" is the exact text from the reader text, with the same words and the same
  punctuation. "quote" is null.
- A number: "value" is a string of digits with an optional "-" and ".", with no thousands
  separators and no currency sign. "unit" is the unit or the currency that the table or the
  text states (for example "USD", "metric tons", "kilograms"), or null. "quote" is the exact
  text that states the number.
- A date: "value" is "YYYY-MM-DD". "quote" is the exact text that states the date.
- A record: "value" is a list with one object for each row or item that the field rule names,
  in document order. Each object has one member for each member that the field rule names,
  with the exact text, or null if the document gives none. "quote" is null.
- "note" is a short reason when the request is not clear, or null.
"""


def sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def make_slots(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """One slot for each field of each member, in manifest order and field order."""
    out: list[dict[str, Any]] = []
    for d in manifest["documents"]:
        for field, (kind, _) in FIELDS[d["kind"]].items():
            out.append({
                "slot": f"l{len(out) + 1:03d}", "id": d["id"], "split": d["split"],
                "doc_kind": d["kind"], "field": field, "kind": kind,
                "request_text": f"The value of {field} in {d['id']}, {NOUN[d['kind']]}",
            })  # fmt: skip
    return out


def reader_text(sources: Path, doc: dict[str, Any]) -> str:
    """The reader text of a member, after a check of the PDF and the text against the pins."""
    base = sources / doc["kind"] / doc["id"]
    if sha(base.with_suffix(".pdf").read_bytes()) != doc["source_sha256"]:
        raise passes.NotPinned("the PDF is not the pinned source")
    raw = base.with_suffix(".txt").read_bytes()
    if sha(raw) != doc["text_sha256"]:
        raise passes.NotPinned("the reader text is not the pinned text")
    return raw.decode()


def pdf_prompt(
    sources: Path, slots: list[dict[str, Any]], schema: dict[str, Any], doc: dict[str, Any]
) -> str:
    text = reader_text(sources, doc)
    return "\n\n".join([
        f"The slots below ask for values in {doc['id']}, {NOUN[doc['kind']]}. Read the reader "
        "text of the whole document below.",
        "Slots:\n" + "\n".join(passes.slot_line(s, schema) for s in slots),
        ANSWER,
        f"=== Document: {doc['id']}\n\nReader text:\n<<<\n{text}\n>>>",
    ])  # fmt: skip


def write_slots(args: argparse.Namespace) -> int:
    mpath = HERE / "manifest.json"
    manifest = json.loads(mpath.read_text())
    if not manifest.get("selection_complete"):
        print(f"{HERE}: the selection is not complete")
        return 1
    if "labels" in manifest:
        print(f"{HERE}: the labels are sealed, so the slots are frozen")
        return 1
    if not json.loads((HERE / "members.json").read_text()).get("notice_review"):
        print(f"{HERE}: read the notice matches and write notice_review first")
        return 1
    slots = make_slots(manifest)
    body = {
        "format": "release1-slots/1",
        "draw": "no draw: one slot for each field of each member, in manifest order",
        "schema": SCHEMA,
        "slots": slots,
    }
    raw = (json.dumps(body, indent=1, ensure_ascii=False) + "\n").encode()
    (HERE / "slots.json").write_bytes(raw)
    manifest["slots"] = {
        "file": "slots.json",
        "count": len(slots),
        "calibration": sum(s["split"] == "calibration" for s in slots),
        "heldout": sum(s["split"] == "heldout" for s in slots),
        "sha256": sha(raw),
    }
    mpath.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    print(json.dumps(manifest["slots"]))
    return 0


def items(sources: Path, work: Path) -> list[dict[str, Any]]:
    """The disagreements for the page of ``bench/label/decide.py``, each with the reader text of
    its member."""
    data = json.loads((HERE / "slots.json").read_text())
    docs = {d["id"]: d for d in json.loads((HERE / "manifest.json").read_text())["documents"]}
    slots = {s["slot"]: s for s in data["slots"]}
    texts: dict[str, str] = {}
    out = []
    for row in json.loads((work / "compare.json").read_text()):
        if row["state"] == "agree":
            continue
        s = slots[row["slot"]]
        if s["id"] not in texts:
            texts[s["id"]] = reader_text(sources, docs[s["id"]])
        out.append({
            "slot": s["slot"], "id": s["id"], "split": s["split"], "kind": s["kind"],
            "request": s["request_text"], "rule": data["schema"][s["field"]]["description"],
            "text": texts[s["id"]], "a": row["a"], "b": row["b"], "checks": row["absence_checks"],
        })  # fmt: skip
    return out


def decide(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(BENCH / "label"))
    import decide as page  # bench/label/decide.py

    page.WORK = args.work
    page.ITEMS = items(args.sources, args.work)
    page.localweb.serve(page.Handler, args.port, f"{len(page.ITEMS)} disagreements")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("slots")
    r = sub.add_parser("run")
    r.add_argument("--pass", dest="pass_", choices=["a", "b", "absence"], required=True)
    r.add_argument("--sources", type=Path, required=True)
    r.add_argument("--work", type=Path, required=True)
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--ids", nargs="*")
    d = sub.add_parser("decide")
    d.add_argument("--sources", type=Path, required=True)
    d.add_argument("--work", type=Path, required=True)
    d.add_argument("--port", type=int, default=8774)
    args = ap.parse_args(argv)
    if args.cmd == "slots":
        return write_slots(args)
    if args.cmd == "decide":
        return decide(args)
    args.set = HERE
    return passes.run(args, prompt_of=pdf_prompt, system=SYSTEM)


if __name__ == "__main__":
    sys.exit(main())
