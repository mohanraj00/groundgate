"""Measure #230 on the held-out set of agency financial reports (bench/afr): the same 20 reports,
as the text that groundgate writes since #230, with a PDF table as rows with tabs. #230 changes no
decision. It changes the text that groundgate and the extractor read, so this measures the text.
The plan is on #230. No rule of #230 came from these reports.

    uv run python bench/afr/tabs.py docs              # tabs/docs/, from the pinned PDFs
    uv run python bench/afr/run.py --tabs --provider claude-cli --model claude-haiku-5-5
    uv run python bench/afr/run.py --tabs --provider codex --model gpt-6-luna
    uv run python bench/afr/run.py --tabs [--old-text] --provider claude-cli \
        --model claude-sonnet-5-5 --effort high
    uv run python bench/afr/run.py --tabs [--old-text] --provider codex --model gpt-6.1-sol \
        --effort high
    uv run python bench/afr/tabs.py decide            # the replay and the new runs
    uv run python bench/afr/tabs.py web               # blind labels, http://127.0.0.1:8778
    uv run python bench/afr/tabs.py results [--check]

The replay decides the replies of #229, which the models wrote from the 0.7 text, against the
new text. The new runs read the new text. decide runs on the 0.8 draft. Its only rule that a
decision on this set can see is #242: with a scale item, the number as written does not match.
The 0.7 text is decided under spec 0.7, as measure.py decides it. Two more runs, with stronger
models at high effort, have no run of #229: they read both texts, and both are decided under the
0.8 draft, so only the text differs. The page shows each admitted
value that has no label yet, as measure.py web shows its values, and writes bench/afr/labels.json.
Labels are keyed by fact, so the labels of #229 stay valid.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
TABS = HERE / "tabs"
sys.path.insert(0, str(HERE))
import measure  # noqa: E402  (bench/afr/measure.py)

# a row label, then the first number with a comma group, as "Total assets  $ 1,234"
LABEL_ROW = re.compile(r"[^\W\d_][^\n\d]*?(\s+)\$?\s?\(?\d{1,3}(?:,\d{3})+")
READS = ("replay", "new runs")  # the replies of #229, and the runs on the new text
HIGH = ("claude-sonnet-5-5-high", "gpt-6.1-sol-high")  # stronger models, high effort
HIGH_READS = ("0.7 text", "new runs")  # their runs on the 0.7 text and on the new text
PAIRS = [(run, read) for run in measure.RUNS for read in READS] + [
    (run, read) for run in HIGH for read in HIGH_READS
]
PORT = 8778


def _replies(run: str, read: str) -> Path:
    if read == "0.7 text":
        return TABS / "runs-0.7-text" / run
    return (HERE if read == "replay" else TABS) / "runs" / run


def _docs(read: str) -> Path:
    return HERE / "docs" if read == "0.7 text" else TABS / "docs"


def _name(run: str, read: str) -> Path:
    return TABS / f"decisions-{run}-{read.replace(' ', '-')}.json"


def docs() -> None:
    """tabs/docs/<id>.txt: the cut pages of each pinned report, as this groundgate writes them."""
    from groundgate.extract import extract

    out = TABS / "docs"
    out.mkdir(parents=True, exist_ok=True)
    srcs = measure._read(HERE / "sources.json")["sources"]
    for src in srcs:
        text = extract(measure._pdf(src), pages=src["select"]["pages"]).text
        (out / f"{src['id']}.txt").write_text(text, encoding="utf-8")
    print(f"wrote {len(srcs)} documents")


def decide() -> None:
    from groundgate.canonical import SPEC_VERSION

    if SPEC_VERSION != "0.8":
        raise SystemExit(f"this measure decides with the 0.8 draft, not {SPEC_VERSION}")
    for run, read in PAIRS:
        measure._dump(_name(run, read), measure.decide_docs(_docs(read), _replies(run, read)))
    print(f"wrote decisions for {len(PAIRS)} runs and texts")


def _found() -> dict[tuple[str, str], dict[str, Any]]:
    return {(run, read): measure._read(_name(run, read)) for run, read in PAIRS}


def facts() -> dict[str, dict[str, Any]]:
    """Each admitted value with no label yet, once per fact."""
    given = measure.labels()
    out: dict[str, dict[str, Any]] = {}
    for docs in _found().values():
        for doc, got in docs.items():
            for r in got["decisions"]:
                if r["outcome"] != "admitted" or r["value"] is None:
                    continue
                fid = measure.item_id(doc, r["field"], r["key"], r["value"])
                if fid not in given and fid not in out:
                    out[fid] = {k: r[k] for k in ("field", "key", "value", "evidence")}
                    out[fid]["doc"] = doc
    return out


def score() -> dict[str, Any]:
    """For each run: the counts of measure.count on the 0.7 text (for the runs of #229, spec 0.7
    with #164), on the replay and on the new runs, and the codes on the proposals that are not
    admitted."""
    given = measure.labels()
    found = _found()
    res: dict[str, Any] = {"runs": {}, "codes": {}}
    for run in (*measure.RUNS, *HIGH):
        if run in measure.RUNS:
            old = measure._read(measure._name(run, measure.SPECS[1]))
            reads = {"0.7 text": old} | {read: found[run, read] for read in READS}
        else:
            reads = {read: found[run, read] for read in HIGH_READS}
        res["runs"][run] = {name: measure.count(docs, given) for name, docs in reads.items()}
        codes: dict[str, collections.Counter[str]] = {}
        for name, docs in reads.items():
            codes[name] = collections.Counter(
                code
                for got in docs.values()
                for r in got["decisions"]
                if r["outcome"] != "admitted"
                for code in r["codes"]
            )
        names = sorted({c for got in codes.values() for c in got})
        res["codes"][run] = {c: {name: codes[name][c] for name in reads} for c in names}
    res["escapes"] = escapes(given)
    res["label rows"] = {
        "0.7 text": label_rows(HERE / "docs"),
        "new text": label_rows(TABS / "docs"),
    }
    return res


def escapes(given: dict[str, Any]) -> list[dict[str, Any]]:
    """Each escape on the new text, with whether its candidate has a scale item. An admitted
    candidate passes each item it has."""
    out = []
    for (run, read), docs in _found().items():
        if read == "0.7 text":
            continue
        for doc, got in docs.items():
            reply = measure._read(_replies(run, read) / f"{doc}.json")["reply"]
            for r in got["decisions"]:
                fid = measure.item_id(doc, r["field"], r["key"], r["value"])
                if r["outcome"] != "admitted" or given.get(fid, {}).get("verdict") != "wrong":
                    continue
                cand = reply["candidates"][int(r["id"][1:])]
                roles = {e.get("role", "value") for e in cand["evidence"]}
                out.append(
                    {"run": run, "read": read, "doc": doc}
                    | {k: r[k] for k in ("field", "key", "value")}
                    | {"scale item": "scale" in roles}
                )
    return out


def label_rows(docs: Path) -> dict[str, int]:
    """The lines with a row label that holds no digit, then a number with a comma group, by what
    stands between the two: a tab, or only spaces (#152)."""
    out = {"a tab": 0, "only spaces": 0}
    for path in sorted(docs.glob("*.txt")):
        for line in path.read_text(encoding="utf-8").split("\n"):
            m = LABEL_ROW.search(line)
            if m:
                out["a tab" if "\t" in m.group(1) else "only spaces"] += 1
    return out


def render(res: dict[str, Any]) -> str:
    out = [
        "# #230 on the held-out set of agency financial reports",
        "",
        "Generated by `bench/afr/tabs.py results` from `results.json`. Do not edit.",
        "",
        "The principal statements of the 20 FY2025 agency financial reports of `bench/afr`, which "
        "no rule of #230 came from. The 0.7 text is the text of `bench/afr/docs`, where a table "
        "comes out column by column. The new text (`tabs/docs`) has a table as rows with tabs. The "
        "replay decides the replies of `bench/afr/runs` against the new text. The new runs read "
        "the new text, with the same prompt, CLI flags and default effort (`bench/afr/run.py "
        "--tabs`). The 0.7 text rows of these two runs are decided under spec 0.7, and the "
        "replay and the new runs under the 0.8 draft, with the #242 rule. `claude-sonnet-5-5-high` "
        "and `gpt-6.1-sol-high` are stronger models at high effort, with the same prompt and "
        "flags. They have no run of #229, so they read both texts, and both are decided under "
        "the 0.8 draft. A value counts once per document, field, key and value. An escape is a "
        "wrong value that a decision admits.",
    ]
    for run, rows in res["runs"].items():
        out += [
            "",
            f"## {run}",
            "",
            "| Text and replies | Right admitted | Escapes | Not sure | Not labeled | Proposals | "
            "No reply |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for name, c in rows.items():
            out.append(
                f"| {name} | {c['right']} | {c['escapes']} | {c['not sure']} | {c['unlabeled']} "
                f"| {c['proposals']} | {c['no reply']} |"
            )
        names = list(rows)
        out += [
            "",
            "Codes on the proposals that are not admitted (a proposal can have more than one):",
            "",
            "| Code | " + " | ".join(names) + " |",
            "|---|" + "---:|" * len(names),
        ]
        for code, by in res["codes"][run].items():
            out.append(f"| `{code}` | " + " | ".join(str(by[n]) for n in names) + " |")
    out += [
        "",
        "## Escapes on the new text",
        "",
        "Each wrong value that a decision on the new text admits. Under spec 0.7, a value with a "
        "scale item could match the number as written, so a value with no scale got through. The "
        "0.8 draft has the #242 rule, which takes that match away.",
        "",
    ]
    if not res["escapes"]:
        out.append("None.")
    else:
        out += [
            "| Run | Replies | Document | Field | Key | Value | Scale item |",
            "|---|---|---|---|---|---:|---|",
        ]
        out += [
            f"| {e['run']} | {e['read']} | {e['doc']} | {e['field']} | {e['key']} | {e['value']} | "
            f"{'yes' if e['scale item'] else 'no'} |"
            for e in res["escapes"]
        ]
    rows = res["label rows"]
    out += [
        "",
        "## Row labels and their first number (#152)",
        "",
        "Lines with a row label that holds no digit, then a number with a comma group, by what "
        "stands between the two. With only spaces, the column rule stops after the first column "
        "(#152). In the 0.7 text, the row labels and the numbers are on different lines.",
        "",
        "| Text | A tab | Only spaces |",
        "|---|---:|---:|",
    ]
    out += [f"| {name} | {c['a tab']} | {c['only spaces']} |" for name, c in rows.items()]
    return "\n".join(out)


def results(check: bool) -> None:
    res = score()
    body = json.dumps(res, indent=1) + "\n"
    md = render(res) + "\n"
    if check:
        old = (TABS / "results.json").read_text(), (TABS / "RESULTS.md").read_text()
        same = old == (body, md)
        print("results are up to date" if same else "out of date: run results")
        sys.exit(0 if same else 1)
    (TABS / "results.json").write_text(body)
    (TABS / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("docs")
    sub.add_parser("decide")
    w = sub.add_parser("web")
    w.add_argument("--port", type=int, default=PORT)
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "docs":
        docs()
    elif args.cmd == "decide":
        decide()
    elif args.cmd == "web":
        measure.serve(args.port, measure.cards(facts(), TABS / "docs"))
    else:
        results(args.check)


if __name__ == "__main__":
    main()
