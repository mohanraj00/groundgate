"""The cause of each field and key failure on bench/afr (#239): for each proposal with
FIELD_CITATION_INVALID or KEY_NOT_AT_VALUE, the check that fails and why. The plan is on #239.

    uv run python bench/afr/causes.py causes             # causes/causes.json
    uv run python bench/afr/causes.py results [--check]  # causes/results.json, RESULTS.md

causes decides the replies again in process, under the groundgate that runs it, on two texts: the
0.7 text (docs/, a PDF table column by column) with the runs of #229, and the new text
(tabs/docs/, a PDF table as rows with tabs, #230) with the new runs of tabs.py. A script finds
each cause from the decision's parts, the candidate and the text, never a person. A proposal can
have both codes, so it can count once for each.

The causes of FIELD_CITATION_INVALID, in the order of the field check (SPEC 4.5):

- the quote is not in the text: the field item's quote does not occur in the document.
- the quote is not at the value: it occurs, but not where groundgate looks for it.
- no alias: the item holds none of the field's aliases.
- another occurrence: the number occurs again, on the row of the field item, but groundgate takes
  an occurrence where steps 10 and 11 pass without a missing part (SPEC 4.6), on another row.
  The row lists the missing parts at the field item's row, decided there with reanchor off.
- after the value: the item ends after the value starts.
- another line: a line break stands between the item and the value.
- words on the line: other words stand between the item and the value on its line.
- a number between: a number stands between the item and the value in its sentence.

The causes of KEY_NOT_AT_VALUE (SPEC 4.5): no heading reaches the value, or the heading at the
value is another key. Each is split by whether the candidate has a key item. causes.json records
the facts as measure.py keys them, so the counts in brackets read bench/afr/labels.json.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "causes"
sys.path.insert(0, str(HERE))
import measure  # noqa: E402  (bench/afr/measure.py)
import tabs  # noqa: E402  (bench/afr/tabs.py)

CODES = ("FIELD_CITATION_INVALID", "KEY_NOT_AT_VALUE")
TEXTS = {
    "0.7 text": (HERE / "docs", HERE / "runs", measure.RUNS),
    "new text": (tabs.TABS / "docs", tabs.TABS / "runs", (*measure.RUNS, *tabs.HIGH)),
}


def _str(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """A UTF-8 byte span as a code point span."""
    raw = text.encode("utf-8")
    return len(raw[: span[0]].decode()), len(raw[: span[1]].decode())


def field_cause(text: str, quote: str, part: Any, pos: int, aliases: tuple[str, ...]) -> str:
    from groundgate.text import key_mentions

    if part.span is None:
        return "the quote is not at the value" if quote in text else "the quote is not in the text"
    a, b = _str(text, part.span)
    if not any(a <= x and y <= b for x, y, _ in key_mentions(text, aliases)):
        return "no alias"
    if b > pos:
        return "after the value"
    between = text[b:pos]
    if "\n" in between:
        return "another line"
    if any(ch.isalpha() for ch in between):
        return "words on the line"
    return "a number between"


def key_cause(text: str, key: str | None, pos: int, keys: tuple[str, ...], item: bool) -> str:
    from groundgate.text import key_mentions, keys_at

    held = keys_at(text, key_mentions(text, keys), pos)
    cause = "no heading reaches the value" if not held else "the heading is another key"
    if key in held:
        cause = "other"
    return f"{cause}, {'with' if item else 'no'} key item"


def field_row(text: str, value: str, field: str) -> int | None:
    """The first occurrence of the value quote with the field quote before it on its line, and
    nothing but spaces, tabs and currency signs between, or None."""
    start = text.find(value)
    while start >= 0:
        line = text[text.rfind("\n", 0, start) + 1 : start]
        at = line.rfind(field)
        if at >= 0 and not any(ch.isalnum() for ch in line[at + len(field) :]):
            return start
        start = text.find(value, start + 1)
    return None


def missing_there(
    text: str, schema: Any, cand: dict[str, Any], start: int, value: str
) -> list[str]:
    """The missing parts of the candidate with its value item at this occurrence, reanchor off."""
    import groundgate as gg

    a = len(text[:start].encode("utf-8"))
    moved = json.loads(json.dumps(cand))
    for e in moved["evidence"]:
        if e.get("role", "value") == "value":
            e["start"], e["end"] = a, a + len(value.encode("utf-8"))
    d = gg.admit(text, schema, [moved], policy={"reanchor": False}).decisions[0]
    return sorted(d.missing) or [code for code in d.codes if code != "VALUE_DERIVED"]


def causes() -> None:
    import groundgate as gg

    schema = measure._read(HERE / "schema.json")
    out = []
    for name, (docs, runs, models) in TEXTS.items():
        for run in models:
            for doc_path in sorted(docs.glob("*.txt")):
                doc = doc_path.stem
                reply = measure._read(runs / run / f"{doc}.json")["reply"]
                cands = [] if reply is None else reply["candidates"]
                cands = [{"id": f"c{i}", **c} for i, c in enumerate(cands)]
                text = doc_path.read_text(encoding="utf-8")
                by_sha = {d.candidate_sha256: d for d in gg.admit(text, schema, cands).decisions}
                for c in cands:
                    d = by_sha[gg.digest("candidate", c)]
                    codes = [code for code in CODES if code in d.codes]
                    if not codes or d.evidence is None:
                        continue
                    f = schema["fields"][d.field]
                    pos = _str(text, d.evidence)[0]
                    roles = {e.get("role", "value"): e for e in c["evidence"]}
                    row = {"text": name, "run": run, "doc": doc, "id": c["id"], "field": d.field}
                    row["fact"] = measure.item_id(doc, d.field, d.key, d.value)
                    if "FIELD_CITATION_INVALID" in codes:
                        part = next(x for x in d.parts if x.role == "field")
                        quote = roles["field"]["text"]
                        aliases = tuple(f.get("aliases", ()))
                        row["field cause"] = field_cause(text, quote, part, pos, aliases)
                        value = roles["value"]["text"].strip()
                        if row["field cause"] != "no alias" and text.count(value) > 1:
                            there = field_row(text, value, quote.strip())
                            if there is not None and there != pos:
                                row["field cause"] = "another occurrence"
                                row["missing at the field row"] = missing_there(
                                    text, schema, c, there, value
                                )
                    if "KEY_NOT_AT_VALUE" in codes:
                        keys = tuple(f.get("keys", ()))
                        row["key cause"] = key_cause(text, d.key, pos, keys, "key" in roles)
                    out.append(row)
    OUT.mkdir(exist_ok=True)
    measure._dump(OUT / "causes.json", out)
    print(f"wrote {len(out)} proposals")


def score() -> dict[str, Any]:
    """For each text and run: the proposals by field cause and by key cause, and how many of
    them hold a value that a label calls right."""
    given = measure.labels()
    rows = measure._read(OUT / "causes.json")
    res: dict[str, Any] = {}
    for kind in ("field cause", "key cause"):
        by: dict[str, dict[str, collections.Counter[str]]] = {}
        for r in rows:
            if kind not in r:
                continue
            col = f"{r['text']}, {r['run']}"
            by.setdefault(r[kind], {}).setdefault(col, collections.Counter())
            by[r[kind]][col]["proposals"] += 1
            by[r[kind]][col]["right"] += given.get(r["fact"], {}).get("verdict") == "right"
            if kind == "field cause" and "missing at the field row" in r:
                for m in r["missing at the field row"]:
                    by[r[kind]][col][f"missing {m}"] += 1
        res[kind] = {
            cause: {col: dict(sorted(c.items())) for col, c in sorted(cols.items())}
            for cause, cols in sorted(by.items())
        }
    return res


def render(res: dict[str, Any]) -> str:
    cols = [f"{name}, {run}" for name, (_, _, models) in TEXTS.items() for run in models]
    out = [
        "# The causes of the field and key failures on bench/afr (#239)",
        "",
        "Generated by `bench/afr/causes.py results` from `results.json`. Do not edit.",
        "",
        "Each proposal with `FIELD_CITATION_INVALID` or `KEY_NOT_AT_VALUE`, decided again under "
        "the 0.8 draft on the 0.7 text (the runs of #229) and on the new text of #230 (the new "
        "runs of `tabs.py`). A script finds the cause from the decision's parts; the causes are "
        "defined in `causes.py`. Each cell is the proposals, and in brackets those whose value "
        "a label calls right. Most proposals that are not admitted have no label.",
    ]
    for kind, title in (
        ("field cause", "FIELD_CITATION_INVALID"),
        ("key cause", "KEY_NOT_AT_VALUE"),
    ):
        out += ["", f"## `{title}`", "", "| Cause | " + " | ".join(cols) + " |"]
        out.append("|---|" + "---:|" * len(cols))
        for cause, by in res[kind].items():
            cells = [f"{by[c]['proposals']} ({by[c]['right']})" if c in by else "0" for c in cols]
            out.append(f"| {cause} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def results(check: bool) -> None:
    res = score()
    body = json.dumps(res, indent=1) + "\n"
    md = render(res) + "\n"
    if check:
        old = (OUT / "results.json").read_text(), (OUT / "RESULTS.md").read_text()
        same = old == (body, md)
        print("results are up to date" if same else "out of date: run results")
        sys.exit(0 if same else 1)
    (OUT / "results.json").write_text(body)
    (OUT / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("causes")
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "causes":
        causes()
    else:
        results(args.check)


if __name__ == "__main__":
    main()
