"""The runs of #256 on bench/acfr: the extractor schema without the role "key" on fields with no
keys, against the runs of #242, whose schema offered it. Every field of bench/acfr has no keys.

    uv run python bench/acfr/run.py ... --name <model>-256     # the new runs (run.py)
    uv run python bench/acfr/keyrole.py decide                 # keyrole/decisions.json
    uv run python bench/acfr/keyrole.py web                    # blind labels, http://127.0.0.1:8779
    uv run python bench/acfr/keyrole.py results [--check]      # keyrole/results.json, RESULTS.md

decide decides both pairs of runs again in process under the groundgate that runs it. web labels
each value of a new run that has no label in bench/acfr/labels.json yet, with the page of
measure.py, so a fact has one label.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "keyrole"
sys.path.insert(0, str(HERE))
import causes  # noqa: E402  (bench/acfr/causes.py)
import measure  # noqa: E402  (bench/acfr/measure.py)

PAIRS = tuple((run, f"{run}-256") for run in measure.RUNS)


def facts() -> dict[str, dict[str, Any]]:
    """Each value of a proposal of a new run that has no label yet, once."""
    given = measure.labels()
    out: dict[str, dict[str, Any]] = {}
    for _, doc, _, _, d in causes._proposals(tuple(new for _, new in PAIRS)):
        if d.value is None:
            continue
        fid = measure.item_id(doc, d.field, d.key, d.value)
        if fid in given or (fid in out and out[fid]["evidence"] is not None):
            continue
        evidence = None if d.evidence is None else list(d.evidence)
        out[fid] = {"field": d.field, "key": d.key, "value": d.value, "evidence": evidence}
        out[fid]["doc"] = doc
    return out


def _schema_sha(run: str) -> list[str]:
    """The output schema hashes that the records of a run name."""
    shas = set()
    for path in sorted((HERE / "runs" / run).glob("*.json")):
        shas.add(measure._read(path)["output_schema_sha256"])
    return sorted(shas)


def decide() -> None:
    """keyrole/decisions.json: the output schema of each run, and each proposal's outcome."""
    import groundgate as gg
    from groundgate.canonical import SPEC_VERSION

    schema = measure._read(HERE / "schema.json")
    out: dict[str, Any] = {"spec": SPEC_VERSION, "schemas": {}, "runs": {}}
    for label, keyed in (("with key", True), ("without key", False)):
        s = gg.extractor_schema(schema)
        if keyed:  # the schema of #242: the role "key" on every field
            s["$defs"]["document"]["properties"]["role"]["enum"].append("key")
            s["$defs"]["document"]["properties"]["role"]["description"] += gg.model._KEY_HELP
        out["schemas"][label] = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
    for run in (run for pair in PAIRS for run in pair):
        replies = sorted((HERE / "runs" / run).glob("*.json"))
        rows = []
        for _, doc, _, c, d in causes._proposals((run,)):
            fact = None if d.value is None else measure.item_id(doc, d.field, d.key, d.value)
            rows.append(
                {
                    "doc": doc,
                    "id": c["id"],
                    "fact": fact,
                    "key item": any(e.get("role") == "key" for e in c["evidence"]),
                    "outcome": d.outcome,
                    "codes": sorted(set(d.codes) | {f"missing {m}" for m in d.missing}),
                }
            )
        out["runs"][run] = {
            "output schema": _schema_sha(run),
            "no reply": sum(measure._read(path)["reply"] is None for path in replies),
            "proposals": rows,
        }
    OUT.mkdir(exist_ok=True)
    measure._dump(OUT / "decisions.json", out)
    print(f"wrote the decisions of {len(out['runs'])} runs under spec {SPEC_VERSION}")


def score() -> dict[str, Any]:
    given = measure.labels()
    found = measure._read(OUT / "decisions.json")
    res: dict[str, Any] = {"spec": found["spec"], "schemas": found["schemas"], "runs": {}}
    res["codes"] = {}
    for run, got in found["runs"].items():
        count: collections.Counter[str] = collections.Counter(dict.fromkeys(COLUMNS, 0))
        count["no reply"] = got["no reply"]
        admitted = set()
        codes: collections.Counter[str] = collections.Counter()
        for r in got["proposals"]:
            count["proposals"] += 1
            count["with a key item"] += r["key item"]
            if r["outcome"] == "admitted":
                count["admitted"] += 1
                admitted.add(r["fact"])
            else:
                count["not admitted"] += 1
                codes.update(r["codes"])
                count["not admitted, right"] += given.get(r["fact"], {}).get("verdict") == "right"
        verdicts = collections.Counter(
            given.get(f, {}).get("verdict", "unlabeled") for f in admitted
        )
        count["right admitted"] = verdicts["right"]
        count["escapes"] = verdicts["wrong"]
        count["admitted, not sure or unlabeled"] = verdicts["not sure"] + verdicts["unlabeled"]
        res["runs"][run] = {"output schema": got["output schema"], **dict(sorted(count.items()))}
        res["codes"][run] = dict(sorted(codes.items()))
    return res


COLUMNS = (
    "proposals", "with a key item", "admitted", "right admitted", "escapes",
    "admitted, not sure or unlabeled", "not admitted", "not admitted, right", "no reply",
)  # fmt: skip


def render(res: dict[str, Any]) -> str:
    names = {sha: label for label, sha in res["schemas"].items()}
    out = [
        "# The extractor schema without the role key on fields with no keys (#256)",
        "",
        "Generated by `bench/acfr/keyrole.py results` from `results.json`. Do not edit.",
        "",
        "Each pair is one model on bench/acfr: the runs of #242, whose output schema offered the "
        "role `key` on every field, and the runs of #256 with `gg.extractor_schema` as it is now, "
        "which offers it only on a field with keys. bench/acfr has no field with keys. Every "
        f"run is decided again under spec {res['spec']}. A value counts once per document, "
        "field, key and value. An escape is a wrong value that a decision admits.",
        "",
        "| Run | Output schema | " + " | ".join(c.capitalize() for c in COLUMNS) + " |",
        "|---|---|" + "---:|" * len(COLUMNS),
    ]
    for run, c in res["runs"].items():
        schema = ", ".join(names.get(s, "other") for s in c["output schema"])
        out.append(f"| {run} | {schema} | " + " | ".join(str(c[k]) for k in COLUMNS) + " |")
    runs = list(res["codes"])
    out += [
        "",
        "Codes and missing parts on the proposals that are not admitted (a proposal can have "
        "more than one). `CANDIDATE_INVALID` here is two items with the same role: the run "
        "quotes the column, such as Total, as a second field item.",
        "",
        "| Code | " + " | ".join(runs) + " |",
        "|---|" + "---:|" * len(runs),
    ]
    for code in sorted({c for run in runs for c in res["codes"][run]}):
        cells = [str(res["codes"][run].get(code, 0)) for run in runs]
        out.append(f"| `{code}` | " + " | ".join(cells) + " |")
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
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(body)
    (OUT / "RESULTS.md").write_text(md)
    print(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("decide")
    sub.add_parser("web")
    r = sub.add_parser("results")
    r.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "decide":
        decide()
    elif args.cmd == "web":
        measure.facts = facts  # the page of measure.py, with the values that have no label
        measure.serve(measure.PORT)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
