"""Learning-loop records on the development split of a requested set (#383).

A loop iteration learns on development documents only. Each iteration writes one record,
``bench/<set>/loop/NN.json``, with six steps:

1. run: the arms, the development split, the code, configuration and cache binding digests;
2. score: ``bench/score.py --requested --split development --runs loop/NN/runs --out loop/NN``,
   then the miss rate, escapes, incomplete documents and search_limit count for each kind;
3. diagnose: the digest of a diagnostics export, and for each review code the review
   decisions with a right value and with a wrong value;
4. calibrate (optional): the recorded answers to judge questions, by digest;
5. propose: one change (feedback text, runner prompt, pack or spec issue) and its PR or issue;
6. decide: keep or drop the change of the previous iteration, from this iteration's numbers.

    PYTHONPATH=bench uv run python -m requested.loop record --set bench/requested4 \\
        --iteration 1 --change feedback --reference '#400' --summary 'one line'
    PYTHONPATH=bench uv run python -m requested.loop check --set bench/requested4

``check`` refuses a record that names a held-out document (in its runs, its documents or its
proposal text) or a run of another split, and a record whose files no longer match their
digests. It keeps the calibration answers and a diagnostics export by digest only: it does not
read their contents for held-out documents. When the manifest freezes the code for the
held-out split, the freeze must name the last record, and that record must have the frozen
code digest. No model runs here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from groundgate import jcs

from .metrics import decision_key, key, score_set, signature

FORMAT = "requested-loop/1"
CHANGES = ("feedback", "prompt", "pack", "spec")
_RECORD = re.compile(r"(?P<n>[0-9]{2,})\.json\Z")
_REFERENCE = re.compile(r"#[1-9][0-9]*\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
Json = dict[str, Any]


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked file: " + path.name)
    return path.read_bytes()


def name(iteration: int) -> str:
    return f"loop/{iteration:02}.json"


def _splits(directory: Path) -> tuple[Json, set[str]]:
    manifest = json.loads(_read(directory / "manifest.json"))
    heldout = {d["id"] for d in manifest["documents"] if d["split"] == "heldout"}
    return manifest, heldout


def _development(directory: Path) -> set[str]:
    manifest = json.loads(_read(directory / "manifest.json"))
    return {d["id"] for d in manifest["documents"] if d["split"] == "development"}


def review_codes(directory: Path, runs: dict[str, Json]) -> Json:
    """For each arm and review code: review decisions with a right value and with a wrong one.

    A right value matches a present label of its field and key. A value on an unclear slot
    counts as unclear. One decision can have more than one code.
    """
    manifest = json.loads(_read(directory / "manifest.json"))
    labels = json.loads(_read(directory / "labels.json"))
    docs = {d["id"]: d for d in manifest["documents"]}
    golds = {d["id"]: d for d in labels["documents"]}
    table: Json = {}
    for arm, run in sorted(runs.items()):
        counts: dict[str, dict[str, int]] = defaultdict(
            lambda: {"right": 0, "wrong": 0, "unclear": 0}
        )
        for output in run["documents"]:
            doc = docs[output["id"]]
            fields = doc.get("schema", manifest["schemas"][doc["kind"]])["fields"]
            slots = {(s["field"], key(s.get("key"))): s for s in golds[doc["id"]]["fields"]}
            for d in output.get("decisions", []):
                if d.get("outcome") != "needs_verification":
                    continue
                spec = fields[d["field"]]
                slot = slots.get(
                    (d["field"], decision_key(d.get("key")) if spec.get("keys") else None)
                )
                kind = spec.get("type", "number")
                if slot is not None and slot["status"] == "unclear":
                    verdict = "unclear"
                else:
                    try:
                        sig = signature(d, kind)
                    except ValueError:
                        sig = None
                    wanted = {signature(v, kind) for v in slot.get("values", [])} if slot else set()
                    verdict = "right" if sig in wanted else "wrong"
                for code in d.get("codes") or []:
                    counts[str(code)][verdict] += 1
        table[arm] = {code: counts[code] for code in sorted(counts)}
    return table


def _summary(results: Json) -> Json:
    """Miss rate, escapes, incomplete documents and search_limit count, from results.json."""
    out: Json = {}
    for arm, run in sorted(results["runs"].items()):
        states = run["document_states"]
        rows = {"total": (run["total"], states["total"])}
        rows |= {k: (run["by_kind"][k], states["by_kind"][k]) for k in sorted(run["by_kind"])}
        out[arm] = {
            label: {
                "miss_rate": r["miss_rate"],
                "escapes": r["escapes"],
                "documents": s["documents"],
                "incomplete": s["incomplete"],
                "search_limit_documents": s.get("search_limit_documents"),
                "search_limit_fields": s.get("search_limit_fields"),
            }
            for label, (r, s) in rows.items()
        }
    return out


def unfrozen(directory: Path) -> str:
    """The manifest digest without its code_freeze. The freeze PR changes only that member."""
    manifest = json.loads(_read(directory / "manifest.json"))
    manifest.pop("code_freeze", None)
    return _digest(jcs(manifest).encode("utf-8"))


def _runs(folder: Path) -> dict[str, tuple[bytes, Json]]:
    runs = {}
    for path in sorted(folder.glob("*.json")):
        raw = _read(path)
        runs[path.stem] = (raw, json.loads(raw))
    if not runs:
        raise ValueError("no development runs in " + folder.name)
    return runs


def build(
    directory: Path,
    iteration: int,
    *,
    change: str | None,
    reference: str | None,
    summary: str | None,
    decide: str | None = None,
    calibration: Path | None = None,
    diagnostics: Path | None = None,
) -> Json:
    """Build the record of one iteration from its scored development runs."""
    folder = directory / "loop" / f"{iteration:02}"
    runs = _runs(folder / "runs")
    results_raw = _read(folder / "results.json")
    bindings = {run["binding_sha256"] for _, run in runs.values()}
    if len(bindings) != 1:
        raise ValueError("the development runs do not share one binding")
    header = next(iter(runs.values()))[1]["provenance"]
    record: Json = {
        "format": FORMAT,
        "iteration": iteration,
        "run": {
            "split": "development",
            "arms": sorted(runs),
            "binding_sha256": bindings.pop(),
            "manifest_sha256": header["manifest_sha256"],
            "manifest_unfrozen_sha256": unfrozen(directory),
            "code_sha256": header["code_sha256"],
            "configuration_sha256": header["configuration_sha256"],
            "documents": sorted(d["id"] for d in next(iter(runs.values()))[1]["documents"]),
        },
        "score": {
            "results": f"loop/{iteration:02}/results.json",
            "results_sha256": _digest(results_raw),
            "runs_sha256": {arm: _digest(raw) for arm, (raw, _) in runs.items()},
            "by_arm": _summary(json.loads(results_raw)),
        },
        "diagnose": {
            "export_sha256": None if diagnostics is None else _digest(_read(diagnostics)),
            "review_codes": review_codes(directory, {a: r for a, (_, r) in runs.items()}),
        },
        "calibrate": None,
        "propose": None,
        "decide": None,
    }
    if calibration is not None:
        relative = calibration.resolve().relative_to(directory.resolve()).as_posix()
        record["calibrate"] = {"answers": relative, "answers_sha256": _digest(_read(calibration))}
    if change is not None or reference is not None or summary is not None:
        record["propose"] = {"change": change, "reference": reference, "summary": summary}
    if decide is not None:
        record["decide"] = {"previous": name(iteration - 1), "outcome": decide}
    return record


def check_record(directory: Path, record: Json, iteration: int, heldout: set[str]) -> None:
    """Refuse a record that names a held-out document or no longer matches its files."""
    if record.get("format") != FORMAT or record.get("iteration") != iteration:
        raise ValueError(f"{name(iteration)}: unknown format or iteration")
    if set(record) != {
        "format",
        "iteration",
        "run",
        "score",
        "diagnose",
        "calibrate",
        "propose",
        "decide",
    }:
        raise ValueError(f"{name(iteration)}: unknown or missing step")
    run = record["run"]
    if run.get("split") != "development":
        raise ValueError(f"{name(iteration)}: a loop runs only on the development split")
    for member in (
        "binding_sha256",
        "manifest_sha256",
        "manifest_unfrozen_sha256",
        "code_sha256",
        "configuration_sha256",
    ):
        if not isinstance(run.get(member), str) or not _DIGEST.fullmatch(run[member]):
            raise ValueError(f"{name(iteration)}: run needs its {member}")
    folder = directory / "loop" / f"{iteration:02}"
    runs = _runs(folder / "runs")
    named = set(run["documents"])
    for arm, (_, projection) in runs.items():
        named |= {d.get("id") for d in projection.get("documents", [])}
        if projection.get("split") != "development":
            raise ValueError(f"{name(iteration)}: run {arm} is not a development run")
    if leaked := sorted(str(i) for i in named & heldout):
        raise ValueError(f"{name(iteration)}: names held-out documents: " + ", ".join(leaked))
    # Also after the freeze, when results.json is not rescored: each run holds exactly the
    # development documents of the manifest.
    development = _development(directory)
    for arm, (_, projection) in runs.items():
        ids = [d.get("id") for d in projection.get("documents", [])]
        if len(ids) != len(set(ids)) or set(ids) != development:
            raise ValueError(f"{name(iteration)}: run {arm} is not the development documents")
    if sorted(run["documents"]) != sorted(development):
        raise ValueError(f"{name(iteration)}: the run documents are not the development split")
    for arm, (raw, projection) in runs.items():
        if (
            projection.get("binding_sha256") != run["binding_sha256"]
            or projection.get("manifest_sha256") != run["manifest_sha256"]
        ):
            raise ValueError(f"{name(iteration)}: run {arm} has another binding or manifest")
        if record["score"]["runs_sha256"].get(arm) != _digest(raw):
            raise ValueError(f"{name(iteration)}: run {arm} differs from its digest")
    if set(record["score"]["runs_sha256"]) != set(runs) or sorted(runs) != run["arms"]:
        raise ValueError(f"{name(iteration)}: the arms differ from the runs folder")
    score = record["score"]
    if score.get("results") != f"loop/{iteration:02}/results.json":
        raise ValueError(f"{name(iteration)}: the results path differs")
    results_raw = _read(folder / "results.json")
    if score.get("results_sha256") != _digest(results_raw):
        raise ValueError(f"{name(iteration)}: results.json differs from its digest")
    if _digest(_read(directory / "manifest.json")) == run["manifest_sha256"]:
        rescored = score_set(directory, "development", runs=folder / "runs")
        if json.loads(results_raw) != json.loads(json.dumps(rescored)):
            raise ValueError(f"{name(iteration)}: results.json is not the score of its runs")
    elif unfrozen(directory) != run["manifest_unfrozen_sha256"]:
        # After the freeze the runs no longer bind to the manifest bytes. Only code_freeze may
        # differ; results.json is then checked by its digest, as record() rescored it.
        raise ValueError(f"{name(iteration)}: the manifest changed in more than its code_freeze")
    if score.get("by_arm") != _summary(json.loads(results_raw)):
        raise ValueError(f"{name(iteration)}: the score summary is not from results.json")
    diagnose = record["diagnose"]
    export = diagnose.get("export_sha256")
    if export is not None and (not isinstance(export, str) or not _DIGEST.fullmatch(export)):
        raise ValueError(f"{name(iteration)}: invalid diagnostics export digest")
    if diagnose.get("review_codes") != review_codes(
        directory, {a: r for a, (_, r) in runs.items()}
    ):
        raise ValueError(f"{name(iteration)}: the review-code table is not from its runs")
    calibrate = record["calibrate"]
    if calibrate is not None:
        path = (directory / str(calibrate.get("answers"))).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError(f"{name(iteration)}: calibration answers must be in the set folder")
        if calibrate.get("answers_sha256") != _digest(_read(path)):
            raise ValueError(f"{name(iteration)}: calibration answers differ from their digest")
    propose = record["propose"]
    if propose is not None and (
        propose.get("change") not in CHANGES
        or not isinstance(propose.get("reference"), str)
        or not _REFERENCE.fullmatch(propose["reference"])
        or not isinstance(propose.get("summary"), str)
        or not propose["summary"].strip()
    ):
        raise ValueError(f"{name(iteration)}: a proposal needs a change, an issue or PR, a line")
    if propose is not None and (
        leaked := sorted(
            i
            for i in heldout
            for text in (propose["summary"], propose["reference"])
            if re.search(r"(?<![A-Za-z0-9_-])" + re.escape(i) + r"(?![A-Za-z0-9_-])", text)
        )
    ):
        raise ValueError(f"{name(iteration)}: names held-out documents: " + ", ".join(leaked))
    decide = record["decide"]
    if iteration == 1:
        if decide is not None:
            raise ValueError(f"{name(iteration)}: the first iteration has nothing to decide")
    elif not isinstance(decide, dict) or decide != {
        "previous": name(iteration - 1),
        "outcome": decide.get("outcome"),
    }:
        raise ValueError(f"{name(iteration)}: decide must name the previous iteration")
    elif decide["outcome"] not in {"keep", "drop"}:
        raise ValueError(f"{name(iteration)}: decide is keep or drop")


def check(directory: Path) -> list[Json]:
    """Check every loop record of a set, and the held-out freeze against the last one."""
    manifest, heldout = _splits(directory)
    folder = directory / "loop"
    paths = sorted(folder.glob("*.json")) if folder.is_dir() else []
    records = []
    for expected, path in enumerate(paths, 1):
        match = _RECORD.fullmatch(path.name)
        if match is None or int(match["n"]) != expected or path.name != f"{expected:02}.json":
            raise ValueError("loop records must be 01.json, 02.json, ... with no gap")
        record = json.loads(_read(path))
        check_record(directory, record, expected, heldout)
        records.append(record)
    check_freeze(manifest, records)
    return records


def check_freeze(manifest: Json, records: list[Json]) -> None:
    """A held-out freeze names the last loop record, and that record has the frozen code."""
    freeze = manifest.get("code_freeze")
    if not (isinstance(freeze, dict) and freeze.get("applies_to") == "heldout"):
        return
    if not records:
        raise ValueError("the held-out freeze names a loop record, but the set has none")
    if freeze.get("last_loop") != name(len(records)):
        raise ValueError("the held-out freeze must name the last loop record")
    if records[-1]["run"]["code_sha256"] != freeze.get("code_sha256"):
        raise ValueError("the last loop record does not have the frozen code digest")


def record(directory: Path, iteration: int, **step: Any) -> Path:
    """Write the next loop record after it passes the same check as ``check``."""
    manifest = json.loads(_read(directory / "manifest.json"))
    freeze = manifest.get("code_freeze")
    if isinstance(freeze, dict) and freeze.get("applies_to") == "heldout":
        raise ValueError("the held-out freeze is done; a new loop record would void it")
    existing = check(directory)
    if iteration != len(existing) + 1:
        raise ValueError(f"the next loop record is {name(len(existing) + 1)}")
    value = build(directory, iteration, **step)
    check_record(directory, value, iteration, _splits(directory)[1])
    path = directory / name(iteration)
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(value, indent=1, sort_keys=True) + "\n")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="command", required=True)
    write = sub.add_parser("record", help="write the next loop record")
    verify = sub.add_parser("check", help="check every loop record and the held-out freeze")
    for parser in (write, verify):
        parser.add_argument("--set", type=Path, required=True, help="requested set folder")
    write.add_argument("--iteration", type=int, required=True)
    write.add_argument("--change", choices=CHANGES, help="propose: the kind of change")
    write.add_argument("--reference", help="propose: the PR or issue, such as #400")
    write.add_argument("--summary", help="propose: one line about the change")
    write.add_argument("--decide", choices=("keep", "drop"), help="the previous change")
    write.add_argument("--calibration", type=Path, help="recorded calibration answers")
    write.add_argument("--diagnostics", type=Path, help="diagnostics export, kept by digest")
    args = ap.parse_args()
    directory = args.set.resolve()
    try:
        if args.command == "check":
            records = check(directory)
            print(f"{len(records)} loop records are valid")
        else:
            path = record(
                directory,
                args.iteration,
                change=args.change,
                reference=args.reference,
                summary=args.summary,
                decide=args.decide,
                calibration=args.calibration,
                diagnostics=args.diagnostics,
            )
            print("wrote " + str(path))
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
