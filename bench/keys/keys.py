"""The keys set for the label-line rule (#52, #83): doses in sections 2 and 3 of FDA labels that
no other set used, each labeled by a person with the keys it belongs to.

    uv run python bench/keys/keys.py pick --count     # how many doses the walk finds
    uv run python bench/keys/keys.py pick             # write sources.json, selection-log.json
    uv run python bench/fetch.py --set bench/keys     # download, verify, write docs/
    uv run python bench/keys/keys.py items            # write items.json from docs/
    uv run python bench/keys/keys.py label            # label them in the terminal
    uv run python bench/keys/keys.py score            # RESULTS.md: spec 0.2 and 0.3
    uv run python bench/keys/keys.py score --check    # fail if the committed files differ

The pick uses the set-2 label rules, looks only at counts, and prints no text. The label tool
never shows which keys a spec puts at a dose.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent / "patterns"), str(HERE.parent / "dots")]

import dots  # noqa: E402  (bench/dots/dots.py)
import pick as walk  # noqa: E402  (bench/pick.py)
from fetch import spl_sections  # noqa: E402  (bench/fetch.py)

PER_SET, PER_DOC, MAX_RANK = 100, 6, 600
# a dose: a number token followed by mg or mcg
UNIT_AFTER = re.compile(r"\s*(?:mg|mcg)(?![A-Za-z])")
SPEC02 = [
    *("uv", "run", "--isolated", "--no-project", "--quiet", "--python", "3.12"),
    *("--with", "groundgate[pdf]==0.2.0", "python", str(HERE / "keys.py"), "read"),
]


def doses_in(text: str) -> list[tuple[int, int]]:
    """(start, end) of each number token that a unit of mg or mcg follows."""
    from groundgate.text import tokens

    return [(t.start, t.end) for t in tokens(text) if UNIT_AFTER.match(text, t.end)]


def excluded() -> set[str]:
    """Drugs used by v0.1, set 2, the pattern set or the dots set."""
    drugs, _, _ = dots.excluded()
    used = json.loads((HERE.parent / "dots" / "sources.json").read_text())["sources"]
    return drugs | {s["id"].removeprefix("fda-") for s in used if s["id"].startswith("fda-")}


def pick(count_only: bool) -> None:
    walk.CACHE = HERE / ".cache"
    walk.CACHE.mkdir(parents=True, exist_ok=True)
    drugs = excluded()
    log: list[dict[str, Any]] = []
    chosen: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for rank, name in enumerate(walk.ranked_generics()[:MAX_RANK], 1):
        if total >= PER_SET:
            break
        base = walk.base_word(name)
        entry: dict[str, Any] = {"kind": "fda", "rank": rank, "name": name}
        log.append(entry)
        if "/" in name:
            entry["skip"] = "combination"
        elif base in drugs:
            entry["skip"] = "used in v0.1, set 2, the pattern set or the dots set"
        elif base in seen:
            entry["skip"] = "same drug ranked higher"
        if "skip" in entry:
            continue
        seen.add(base)
        label, why = walk.find_label(name)
        if label is None:
            entry["skip"] = why
            continue
        entry["setid"] = label["setid"]
        if not label["keyed"]:
            entry["skip"] = f"fewer than {walk.MIN_KEYS} subsections in section 1"
            continue
        data = walk.get(label["url"], f"spl-{label['setid']}.xml")
        found = len(doses_in(spl_sections(data, [walk.DOSAGE, walk.STRENGTHS])))
        entry["doses"] = found
        if not found:
            entry["skip"] = "no dose in sections 2 and 3"
            continue
        total += min(found, PER_DOC)
        print(f"fda: rank {rank}, {len(chosen) + 1} labels, {total} doses", file=sys.stderr)
        chosen.append(
            {
                "id": f"fda-{base}",
                "kind": "fda",
                "groups": ["keys"],
                "url": label["url"],
                "sha256": label["sha256"],
                "select": {"sections": [walk.DOSAGE, walk.STRENGTHS]},
                "keys": label["keys"],
                "source": f"{label['title']}; Part D 2024 claims rank {rank}",
            }
        )
    skips: dict[str, int] = {}
    for e in log:
        if "skip" in e:
            skips[e["skip"]] = skips.get(e["skip"], 0) + 1
    print(f"fda: {len(chosen)} labels, {total} doses")
    for why, c in sorted(skips.items()):
        print(f"  skipped, {why}: {c}")
    if count_only:
        return
    lock = {"retrieved": datetime.date.today().isoformat(), "sources": chosen}
    (HERE / "sources.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n")
    (HERE / "selection-log.json").write_text(json.dumps(log, indent=1, ensure_ascii=False) + "\n")
    print("wrote bench/keys/sources.json and selection-log.json")


def find_items() -> None:
    """items.json: the first PER_DOC doses of each label, as code point offsets in docs/<id>.txt,
    with the label's keys."""
    out = []
    for src in json.loads((HERE / "sources.json").read_text())["sources"]:
        text = (HERE / "docs" / f"{src['id']}.txt").read_text(encoding="utf-8")
        for a, b in doses_in(text)[:PER_DOC]:
            out.append({"id": f"{src['id']}:{a}", "doc": src["id"], "span": [a, b]})
    out = out[:PER_SET]  # the last label gives only the doses the set still needs
    (HERE / "items.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote items.json: {len(out)} doses in {len({it['doc'] for it in out})} labels")


def keys_of() -> dict[str, list[str]]:
    return {s["id"]: s["keys"] for s in json.loads((HERE / "sources.json").read_text())["sources"]}


def context(text: str, span: list[int], bold: str = "\033[1;7m{}\033[0m") -> str:
    """The dose with up to 400 code points before and 150 after, line breaks kept."""
    a, b = span
    return text[max(0, a - 400) : a] + bold.format(text[a:b]) + text[b : b + 150]


def label() -> None:
    items = json.loads((HERE / "items.json").read_text())
    keys = keys_of()
    path = HERE / "labels.json"
    labels: dict[str, list[str]] = json.loads(path.read_text()) if path.exists() else {}
    texts: dict[str, str] = {}
    print("For each marked dose: which of the label's conditions does it belong to?")
    print("Type a number, several numbers with commas (1,3), or 0 for none of them.\n")
    i = next((k for k, it in enumerate(items) if it["id"] not in labels), len(items))
    while i < len(items):
        it = items[i]
        if it["doc"] not in texts:
            texts[it["doc"]] = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        done = sum(x["id"] in labels for x in items)
        print(f"\n{'=' * 72}\n[{i + 1}/{len(items)}, {done} labeled] {it['doc']}\n")
        print(context(texts[it["doc"]], it["span"]))
        print()
        for n, k in enumerate(keys[it["doc"]], 1):
            print(f"  {n}  {k}")
        print("  0  none of them")
        was = f" (now: {labels[it['id']]})" if it["id"] in labels else ""
        ans = input(f"Condition{was}: numbers, 0, b back, q quit: ").strip().lower()
        if ans == "q":
            break
        if ans == "b":
            i = max(0, i - 1)
            continue
        try:
            picked = sorted({int(x) for x in ans.split(",") if x.strip()})
        except ValueError:
            continue
        if not picked or not all(0 <= n <= len(keys[it["doc"]]) for n in picked):
            continue
        if 0 in picked and len(picked) > 1:
            continue
        labels[it["id"]] = [keys[it["doc"]][n - 1] for n in picked if n]
        path.write_text(json.dumps(dict(sorted(labels.items())), indent=1) + "\n")
        i += 1
    done = sum(x["id"] in labels for x in items)
    print(f"\n{done} of {len(items)} labeled, saved in bench/keys/labels.json")


def read() -> dict[str, list[str]]:
    """The keys that the installed groundgate puts at each dose."""
    from groundgate.text import key_mentions, keys_at

    keys = keys_of()
    texts: dict[str, str] = {}
    out = {}
    for it in json.loads((HERE / "items.json").read_text()):
        if it["doc"] not in texts:
            texts[it["doc"]] = (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8")
        text = texts[it["doc"]]
        mentions = key_mentions(text, tuple(keys[it["doc"]]))
        out[it["id"]] = sorted(keys_at(text, mentions, it["span"][0]))
    return out


def outcome(label: list[str], read: list[str]) -> str:
    """How a reading serves the label: does every right key reach the dose, and does a wrong
    one? A candidate with a right key that does not reach goes to review, and one with a wrong key
    that reaches is admitted."""
    missing = bool(set(label) - set(read))
    wrong = bool(set(read) - set(label))
    if not label:
        return "a wrong key reaches it" if wrong else "no key reaches it"
    return {
        (False, False): "every right key, no wrong key",
        (False, True): "every right key and a wrong key",
        (True, False): "a right key missing, no wrong key",
        (True, True): "a right key missing and a wrong key",
    }[(missing, wrong)]


def score(check: bool) -> None:
    items = json.loads((HERE / "items.json").read_text())
    labels = json.loads((HERE / "labels.json").read_text())
    missing = [it["id"] for it in items if it["id"] not in labels]
    if missing:
        raise SystemExit(f"{len(missing)} of {len(items)} doses have no label; run keys.py label")
    run = subprocess.run(SPEC02, capture_output=True, text=True, check=True)
    v02, v03 = json.loads(run.stdout), read()
    rows = [
        {
            "id": it["id"],
            "label": labels[it["id"]],
            "spec_0.2": v02[it["id"]],
            "spec_0.3": v03[it["id"]],
        }
        for it in items
    ]
    with_key = [
        "every right key, no wrong key",
        "every right key and a wrong key",
        "a right key missing, no wrong key",
        "a right key missing and a wrong key",
    ]
    no_key = ["no key reaches it", "a wrong key reaches it"]
    specs = ("spec_0.2", "spec_0.3")

    def tally(rs: list[dict[str, Any]], spec: str, names: list[str]) -> dict[str, int]:
        return {n: sum(outcome(r["label"], r[spec]) == n for r in rs) for n in names}

    keyed = [r for r in rows if r["label"]]
    unkeyed = [r for r in rows if not r["label"]]
    results = {
        "doses": len(rows),
        "labels": len({it["doc"] for it in items}),
        "labeled_with_a_key": len(keyed),
        "labeled_with_no_key": len(unkeyed),
        "by_spec": {
            s: {"with a key": tally(keyed, s, with_key), "no key": tally(unkeyed, s, no_key)}
            for s in specs
        },
        "doses_read": rows,
    }
    what = {
        "every right key, no wrong key": "right",
        "every right key and a wrong key": "a swapped key is admitted",
        "a right key missing, no wrong key": "a right key goes to review",
        "a right key missing and a wrong key": "a swapped key is admitted, a right key goes to "
        "review",
        "no key reaches it": "right",
        "a wrong key reaches it": "a key is admitted where none applies",
    }
    md = [
        "# Keys set: the label-line rule",
        "",
        "Generated by `bench/keys/keys.py score` from `items.json` and `labels.json`. "
        "[README.md](README.md) explains the set. Spec 0.2 is the released 0.2.0 wheel and spec "
        "0.3 is the core in this repository.",
        "",
        f"{results['doses']} doses in {results['labels']} FDA labels, labeled by a person: "
        f"{results['labeled_with_a_key']} with one or more of the label's keys, "
        f"{results['labeled_with_no_key']} with none of them.",
        "",
        "| Label | Keys at the dose | What it means | Spec 0.2 | Spec 0.3 |",
        "|---|---|---|---:|---:|",
    ]
    for group, names in (("with a key", with_key), ("no key", no_key)):
        for n in names:
            a = results["by_spec"]["spec_0.2"][group][n]
            b = results["by_spec"]["spec_0.3"][group][n]
            md.append(f"| {group} | {n} | {what[n]} | {a} | {b} |")
    texts = {
        it["doc"]: (HERE / "docs" / f"{it['doc']}.txt").read_text(encoding="utf-8") for it in items
    }
    spans = {it["id"]: (it["doc"], it["span"]) for it in items}
    changed = [r for r in rows if r["spec_0.2"] != r["spec_0.3"]]
    md += ["", f"## Doses that spec 0.3 reads differently from 0.2 ({len(changed)})", ""]
    if not changed:
        md.append("None.")
    else:
        md += ["| Dose | Label | 0.2 | 0.3 | Text |", "|---|---|---|---|---|"]
        for r in changed:
            doc, span = spans[r["id"]]
            text = dots.context(texts[doc], {"abbreviation": span}, "**{}**").replace("|", "\\|")
            md.append(
                f"| `{r['id']}` | {'; '.join(r['label']) or 'none'} | "
                f"{'; '.join(r['spec_0.2']) or 'none'} | {'; '.join(r['spec_0.3']) or 'none'} "
                f"| {text} |"
            )
    out = {
        HERE / "results.json": json.dumps(results, indent=1) + "\n",
        HERE / "RESULTS.md": "\n".join(md) + "\n",
    }
    if check:
        stale = [p.name for p, body in out.items() if not p.exists() or p.read_text() != body]
        if stale:
            raise SystemExit(f"out of date: {', '.join(stale)}; run keys.py score")
        print("results are up to date")
        return
    for path, body in out.items():
        path.write_text(body)
    print("wrote results.json, RESULTS.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pick")
    p.add_argument("--count", action="store_true", help="report dose counts; write nothing")
    sub.add_parser("items")
    sub.add_parser("label")
    sub.add_parser("read")
    p = sub.add_parser("score")
    p.add_argument("--check", action="store_true", help="fail if the committed files differ")
    args = ap.parse_args()
    if args.cmd == "pick":
        pick(args.count)
    elif args.cmd == "items":
        find_items()
    elif args.cmd == "label":
        label()
    elif args.cmd == "read":
        print(json.dumps(read()))
    else:
        score(args.check)


if __name__ == "__main__":
    main()
