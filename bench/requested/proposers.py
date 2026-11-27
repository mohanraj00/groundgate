"""The admitted error rate for each proposer and for agreement, never mixed (#511).

No model calls, source reads or core decisions occur here. The input is a set's sealed labels and
its cached run projections. A projection keeps the `proposer` of each final decision from #511 on.
A decision with no `proposer` is the unnamed proposer: in the runner, that is the model.

Each distinct admitted value of a slot goes to one group. If the admitted decisions that carry it
all have one proposer, it goes to the group of that proposer. If they have two or more, it goes to
`agreement`. So no admitted value counts in two groups.

The script writes `proposers.json` and `PROPOSERS.md` beside the results of a split. It never
changes `results.json` or `RESULTS.md`.

    uv run python bench/requested/proposers.py --set bench/requested4 --split development \\
        --runs bench/requested4/development-646/runs --out bench/requested4/development-646
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from requested.metrics import (
    blank_row,
    decision_key,
    key,
    score_set,
    signature,
    summarize,
)

FORMAT = "requested-proposers/1"
UNNAMED = "unnamed"
AGREEMENT = "agreement"
OUTCOMES = ("admitted", "needs_verification", "rejected")
# The members of a summary that a proposer group keeps. The miss rate of a group has no meaning:
# a missed value has no proposer.
KEPT = ("admitted", "escapes", "admitted_error_rate", "bounds", "documents_with_admits")


def proposer(decision: dict[str, Any]) -> str | None:
    """The proposer of a final decision, or None for the unnamed proposer."""
    raw = decision.get("proposer")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("a decision proposer must be a nonblank string or null")
    return raw


def _sig(decision: dict[str, Any], field_type: str) -> tuple[str, Any]:
    try:
        return signature(decision, field_type)
    except ValueError:
        # A malformed admitted value is wrong, as in metrics.measure.
        return (
            "invalid:" + json.dumps(decision.get("value"), sort_keys=True),
            json.dumps(decision.get("unit"), sort_keys=True),
        )


def _group(names: set[str | None]) -> str:
    if len(names) > 1:
        return AGREEMENT
    (name,) = names
    return UNNAMED if name is None else "proposer:" + name


def rows_of(
    manifest: dict[str, Any], labels: dict[str, Any], run: dict[str, Any], split: str
) -> list[dict[str, Any]]:
    """One row for each document, slot and group with an admitted value or a value found by
    one proposer only. The caller validates the set with metrics.score_set first."""
    golds = {d["id"]: d for d in labels["documents"]}
    outputs = {d["id"]: d for d in run["documents"]}
    rows: dict[tuple[Any, ...], dict[str, Any]] = {}

    def row(doc: dict[str, Any], field: str, skey: Any, group: str) -> dict[str, Any]:
        ident = (doc["id"], field, json.dumps(skey), group)
        if ident not in rows:
            rows[ident] = (
                blank_row()
                | {
                    "doc": doc["id"],
                    "kind": doc["kind"],
                    "field": field,
                    "key": skey,
                    "group": group,
                }
                | {"only_" + o: 0 for o in OUTCOMES}
            )
        return rows[ident]

    for doc in manifest["documents"]:
        if doc["split"] != split:
            continue
        fields = doc.get("schema", manifest["schemas"][doc["kind"]])["fields"]
        decisions = outputs.get(doc["id"], {}).get("decisions", [])
        labeled = {(s["field"], key(s.get("key"))): s for s in golds[doc["id"]]["fields"]}
        # Each decision goes to its labeled slot, or to an unknown slot of its field.
        slots: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        for d in decisions:
            spec = fields[d["field"]]
            dkey = decision_key(d.get("key")) if spec.get("keys") else None
            known = (d["field"], dkey) in labeled
            slot = (d["field"], dkey if known else ("unknown", json.dumps(d.get("key"))))
            slots.setdefault(slot, []).append(d)
        for (field, skey), found in sorted(slots.items(), key=lambda s: json.dumps(s[0])):
            spec = fields[field]
            label = labeled.get((field, skey))
            if label is not None and label["status"] == "unclear":
                continue
            wanted = (
                set()
                if label is None
                else {signature(v, spec.get("type", "number")) for v in label.get("values", [])}
            )
            by_sig: dict[tuple[str, Any], dict[str, set[str | None]]] = {}
            for d in found:
                outcome = d["outcome"]
                by_sig.setdefault(_sig(d, spec.get("type", "number")), {}).setdefault(
                    outcome, set()
                ).add(proposer(d))
            for sig, outcomes in by_sig.items():
                admitted = outcomes.get("admitted", set())
                if admitted:
                    r = row(doc, field, skey, _group(admitted))
                    r["admitted"] += 1
                    r["escapes"] += sig not in wanted
                names = set().union(*outcomes.values())
                if sig in wanted and len(names) == 1:
                    # A right value that only one proposer proposed, by its best outcome.
                    best = next(o for o in OUTCOMES if o in outcomes)
                    row(doc, field, skey, _group(names))["only_" + best] += 1
    return list(rows.values())


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    whole = summarize(rows)
    return {k: whole[k] for k in KEPT} | {
        "only_" + o: sum(r["only_" + o] for r in rows) for o in OUTCOMES
    }


def measure_groups(
    manifest: dict[str, Any], labels: dict[str, Any], run: dict[str, Any], split: str
) -> dict[str, Any]:
    """For each group: the total, each kind, each field and each kind/field pair."""
    rows = rows_of(manifest, labels, run, split)
    out: dict[str, Any] = {}
    for group in sorted({r["group"] for r in rows}):
        mine = [r for r in rows if r["group"] == group]
        pairs = sorted({(r["kind"], r["field"]) for r in mine})
        out[group] = {
            "total": summary(mine),
            "by_kind": {
                k: summary([r for r in mine if r["kind"] == k])
                for k in sorted({r["kind"] for r in mine})
            },
            "by_field": {
                f: summary([r for r in mine if r["field"] == f])
                for f in sorted({r["field"] for r in mine})
            },
            "by_kind_field": {
                k: {
                    f: summary([r for r in mine if r["kind"] == k and r["field"] == f])
                    for kk, f in pairs
                    if kk == k
                }
                for k in sorted({k for k, _ in pairs})
            },
        }
    return out


def proposer_set(directory: Path, split: str, runs: Path | None = None) -> dict[str, Any]:
    """Validate the set as score_set does, then measure each arm by group."""
    scored = score_set(directory, split, runs=runs)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    labels = json.loads((directory / "labels.json").read_bytes())
    folder = runs if runs is not None else directory / "runs"
    arms = {}
    for arm, result in sorted(scored["runs"].items()):
        run = json.loads((folder / (arm + ".json")).read_bytes())
        arms[arm] = {
            "split": split,
            "cache_sha256": result["cache_sha256"],
            "groups": measure_groups(manifest, labels, run, split),
        }
    return {
        "format": FORMAT,
        "labels_sha256": scored["labels_sha256"],
        "manifest_sha256": scored["manifest_sha256"],
        "runs": arms,
    }


def render(results: dict[str, Any]) -> str:
    """Render the groups; all numbers come from proposers.json."""

    def percent(raw: float | None) -> str:
        return "n/a" if raw is None else f"{raw * 100:.2f}%"

    lines = [
        "# Results for each proposer",
        "",
        "Generated by `bench/requested/proposers.py`.",
        "",
        "Labels: `" + results["labels_sha256"] + "`.",
        "",
        "Each distinct admitted value goes to one group. `proposer:<id>` holds the values that "
        "only candidates of that proposer admitted. `unnamed` holds the values of candidates "
        "with no proposer; in the runner, that is the model. `agreement` holds the values that "
        "candidates of two or more proposers admitted. No value counts in two groups. "
        "Only found counts right values that only the proposers of the group proposed, by "
        "their best final outcome. Unclear slots are excluded. The bounds are those of "
        "`RESULTS.md`.",
        "",
    ]
    head = [
        "Group",
        "Slice",
        "Admits",
        "Escapes",
        "Admitted error",
        "Value upper",
        "Document upper",
        "Combined upper",
        "Docs with admits",
        "Only found: admitted",
        "Only found: review",
        "Only found: rejected",
    ]
    for arm, run in sorted(results["runs"].items()):
        lines += ["## " + arm, "", "Split: " + run["split"] + ".", ""]
        body = []
        for group, slices in sorted(run["groups"].items()):
            named = [("total", slices["total"])]
            named += [("kind: " + n, r) for n, r in slices["by_kind"].items()]
            named += [("field: " + n, r) for n, r in slices["by_field"].items()]
            named += [
                (k + "/" + f, r)
                for k, fields in slices["by_kind_field"].items()
                for f, r in fields.items()
            ]
            for label, r in named:
                b = r["bounds"]
                body.append(
                    [
                        group,
                        label,
                        r["admitted"],
                        r["escapes"],
                        percent(r["admitted_error_rate"]["rate"]),
                        percent(b["value_upper95"]),
                        percent(b["document_upper95"]),
                        percent(b["combined_upper95"]),
                        r["documents_with_admits"],
                        r["only_admitted"],
                        r["only_needs_verification"],
                        r["only_rejected"],
                    ]
                )
        if not body:
            lines += ["No admitted value and no right value that one proposer found.", ""]
            continue
        lines += ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * 2 + ["---:"] * 10) + "|"]
        lines += [
            "| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |" for cells in body
        ]
        lines += [""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--set", type=Path, required=True, help="requested-field set directory")
    ap.add_argument("--split", choices=("development", "heldout"), default="heldout")
    ap.add_argument("--runs", type=Path, help="run projections (default: SET/runs)")
    ap.add_argument("--out", type=Path, help="output folder (default: SET)")
    ap.add_argument("--check", action="store_true", help="fail if the outputs would change")
    args = ap.parse_args(argv)
    directory = args.set.resolve()
    out = (args.out or args.set).resolve()
    if args.split == "development" and out == directory:
        ap.error("development results need --out other than the set folder")
    if args.split == "heldout" and out != directory:
        ap.error("held-out results go only to the set folder")
    try:
        results = proposer_set(
            directory, args.split, runs=args.runs.resolve() if args.runs else None
        )
    except (OSError, ValueError, KeyError) as exc:
        ap.error(f"proposer results need sealed labels and a valid set: {exc}")
    outputs = {
        "proposers.json": json.dumps(results, indent=1, sort_keys=True) + "\n",
        "PROPOSERS.md": render(results),
    }
    if args.check:
        stale = [
            name
            for name, content in outputs.items()
            if not (out / name).exists() or (out / name).read_text(encoding="utf-8") != content
        ]
        if stale:
            raise SystemExit("out of date: " + ", ".join(stale))
        return
    out.mkdir(parents=True, exist_ok=True)
    for name, content in outputs.items():
        (out / name).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
