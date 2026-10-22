"""The runs of #256: the extractor schema without the role "key" on fields with no keys, against
the schema of #242, which offered it on every field. Every field of bench/acfr has no keys.

    uv run python bench/acfr/run.py ...                     # the runs (run.py)
    uv run python bench/acfr/keyrole.py decide              # keyrole/decisions.json
    uv run python bench/acfr/keyrole.py web                 # blind labels, port 8780
    uv run python bench/acfr/keyrole.py results [--check]   # keyrole/results.json, RESULTS.md

Two sets, each with a pair of runs for each model:

- bench/acfr, the documents of the diagnosis (#244): the runs of #242 and new runs with the
  schema of #256.
- bench/acfr2, documents that #256 did not come from: the 10 texts of bench/acfr2 with the schema
  of bench/acfr, once with the schema of #242 and once with the schema of #256. bench/acfr2 has
  the same four fields with the fiscal year as the key, so a value here is the fact of
  bench/acfr2 with the key 2025, and it has that label in bench/acfr2/labels.json.

decide decides every run again in process under the groundgate that runs it. web labels each
value of a bench/acfr2 run that has no label yet, with the page of bench/acfr2/measure.py.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
OUT = HERE / "keyrole"
sys.path.insert(0, str(HERE))
import causes  # noqa: E402  (bench/acfr/causes.py)
import measure  # noqa: E402  (bench/acfr/measure.py)

ACFR2 = HERE.parent / "acfr2"
SETS = {
    "bench/acfr": (HERE / "docs", tuple((run, f"{run}-256") for run in measure.RUNS)),
    "bench/acfr2": (
        ACFR2 / "docs",
        tuple((f"{run}-acfr2-242", f"{run}-acfr2-256") for run in measure.RUNS),
    ),
}
YEAR = "2025"  # the key of bench/acfr2 for the fiscal year of bench/acfr


def _measure2() -> Any:
    """bench/acfr2/measure.py, under another name than bench/acfr/measure.py."""
    spec = importlib.util.spec_from_file_location("acfr2_measure", ACFR2 / "measure.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fact(name: str, doc: str, d: Any) -> str | None:
    """The label id of a decision's value in its set."""
    if d.value is None:
        return None
    if name == "bench/acfr":
        return measure.item_id(doc, d.field, d.key, d.value)  # type: ignore[no-any-return]
    return _measure2().item_id(doc, d.field, YEAR, d.value)  # type: ignore[no-any-return]


def _labels(name: str) -> dict[str, Any]:
    return measure.labels() if name == "bench/acfr" else _measure2().labels()  # type: ignore[no-any-return]


def schema_242(schema: dict[str, Any]) -> dict[str, Any]:
    """The output schema of #242 for a schema with no keys: the role "key" on every field."""
    import groundgate as gg

    out = gg.extractor_schema(schema)
    if (
        "evidence_no_key" in out["$defs"]
        or "key" in out["$defs"]["document"]["properties"]["role"]["enum"]
    ):
        raise SystemExit("schema_242 is for a schema whose fields have no keys")
    role = out["$defs"]["document"]["properties"]["role"]
    role["enum"].append("key")
    role["description"] += gg.model._KEY_HELP
    return out


def facts() -> dict[str, dict[str, Any]]:
    """Each value of a bench/acfr2 run that has no label yet, once, as a fact of bench/acfr2."""
    docs, pairs = SETS["bench/acfr2"]
    given = _labels("bench/acfr2")
    out: dict[str, dict[str, Any]] = {}
    for _, doc, _, _, d in causes._proposals(tuple(r for pair in pairs for r in pair), docs):
        fid = _fact("bench/acfr2", doc, d)
        if fid is None or fid in given or (fid in out and out[fid]["evidence"] is not None):
            continue
        evidence = None if d.evidence is None else list(d.evidence)
        out[fid] = {"field": d.field, "key": YEAR, "value": d.value, "evidence": evidence}
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
    out: dict[str, Any] = {"spec": SPEC_VERSION, "schemas": {}, "sets": {}}
    for label, s in (
        ("with key", schema_242(schema)),
        ("without key", gg.extractor_schema(schema)),
    ):
        out["schemas"][label] = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
    for name, (docs, pairs) in SETS.items():
        runs = out["sets"].setdefault(name, {})
        for run in (run for pair in pairs for run in pair):
            replies = sorted((HERE / "runs" / run).glob("*.json"))
            if len(replies) != len(list(docs.glob("*.txt"))):
                raise SystemExit(f"{run}: {len(replies)} replies; run run.py first")
            rows = []
            for _, doc, _, c, d in causes._proposals((run,), docs):
                rows.append(
                    {
                        "doc": doc,
                        "id": c["id"],
                        "fact": _fact(name, doc, d),
                        "key item": any(e.get("role") == "key" for e in c["evidence"]),
                        "outcome": d.outcome,
                        "codes": sorted(set(d.codes) | {f"missing {m}" for m in d.missing}),
                    }
                )
            runs[run] = {
                "output schema": _schema_sha(run),
                "no reply": sum(measure._read(path)["reply"] is None for path in replies),
                "proposals": rows,
            }
    OUT.mkdir(exist_ok=True)
    measure._dump(OUT / "decisions.json", out)
    print(f"wrote the decisions of {len(SETS)} sets under spec {SPEC_VERSION}")


COLUMNS = (
    "proposals", "with a key item", "admitted", "right admitted", "escapes",
    "admitted, not sure or unlabeled", "not admitted", "not admitted, right", "no reply",
)  # fmt: skip


def score() -> dict[str, Any]:
    found = measure._read(OUT / "decisions.json")
    res: dict[str, Any] = {"spec": found["spec"], "schemas": found["schemas"], "sets": {}}
    for name, runs in found["sets"].items():
        given = _labels(name)
        mine: dict[str, Any] = {"runs": {}, "codes": {}}
        for run, got in runs.items():
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
                    count["not admitted, right"] += (
                        given.get(r["fact"], {}).get("verdict") == "right"
                    )
            verdicts = collections.Counter(
                given.get(f, {}).get("verdict", "unlabeled") for f in admitted
            )
            count["right admitted"] = verdicts["right"]
            count["escapes"] = verdicts["wrong"]
            count["admitted, not sure or unlabeled"] = verdicts["not sure"] + verdicts["unlabeled"]
            mine["runs"][run] = {"output schema": got["output schema"], **dict(count)}
            mine["codes"][run] = dict(sorted(codes.items()))
        res["sets"][name] = mine
    return res


def render(res: dict[str, Any]) -> str:
    names = {sha: label for label, sha in res["schemas"].items()}
    out = [
        "# The extractor schema without the role key on fields with no keys (#256)",
        "",
        "Generated by `bench/acfr/keyrole.py results` from `results.json`. Do not edit.",
        "",
        "Each pair is one model with the schema of bench/acfr, whose fields have no keys: once "
        "with the output schema of #242, which offered the role `key` on every field, and once "
        "with `gg.extractor_schema` as it is now, which offers it only on a field with keys. "
        "The hash of each run's output schema is in its records. Every run is decided again "
        f"under spec {res['spec']}. A value counts once per document, field, key and value. An "
        "escape is a wrong value that a decision admits.",
    ]
    about = {
        "bench/acfr": "The documents of the diagnosis (#244). The runs with the role key are the "
        "runs of #242.",
        "bench/acfr2": "The 10 documents of bench/acfr2, which #256 did not come from. A value "
        "has the label of the bench/acfr2 fact with the key 2025.",
    }
    for name, mine in res["sets"].items():
        out += [
            "",
            f"## {name}",
            "",
            about[name],
            "",
            "| Run | Output schema | " + " | ".join(c.capitalize() for c in COLUMNS) + " |",
            "|---|---|" + "---:|" * len(COLUMNS),
        ]
        for run, c in mine["runs"].items():
            schema = ", ".join(names.get(s, "other") for s in c["output schema"])
            out.append(f"| {run} | {schema} | " + " | ".join(str(c[k]) for k in COLUMNS) + " |")
        runs = list(mine["codes"])
        out += [
            "",
            "Codes and missing parts on the proposals that are not admitted (a proposal can have "
            "more than one).",
            "",
            "| Code | " + " | ".join(runs) + " |",
            "|---|" + "---:|" * len(runs),
        ]
        for code in sorted({c for run in runs for c in mine["codes"][run]}):
            cells = [str(mine["codes"][run].get(code, 0)) for run in runs]
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
        m2 = _measure2()
        m2.facts = facts  # the page of bench/acfr2/measure.py, with the values that have no label
        m2.serve(m2.PORT)
    else:
        results(args.check)


if __name__ == "__main__":
    main()
