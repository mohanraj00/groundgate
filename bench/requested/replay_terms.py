"""Replay recorded runner candidates with approved schema terms (#547).

The replay reads the recorded runner results of one development run from its external cache.
It admits the recorded final candidates of each document again with the current core, and the
schema of the frozen manifest plus the approved terms. It makes no model call and runs no
search, so the ``not_found`` entries of the run stay as recorded. Only the development split
is read.

    PYTHONPATH=bench uv run python -m requested.replay_terms --set bench/requested4 \\
        --terms bench/requested4/terms-547.json --cache CACHE/runs/dev464/BINDING \\
        --sources bench/requested4/.cache/run_sources --runs bench/requested4/replay-547/terms/runs

``--no-terms`` writes the control: the same replay with the schemas of the manifest only. It
shows the changes that come from the current core and not from the terms. The output is one
projection, ``runner.json``, for ``bench/score.py --requested --split development``. Its
provenance is the provenance of the recorded run plus a ``replay`` member, so its binding is new.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import groundgate as gg

from .metrics import decision_key, key, signature
from .run_set import FrozenSet, _projection, digest, encoded

Json = dict[str, Any]
TERMS = ("aliases", "columns", "markers")
NEW_CODES = ("COLUMN_NOT_AT_VALUE", "MARKER_OTHER_FIELD")


def apply_terms(schema: Json, terms: Json) -> Json:
    """Return a schema with the approved terms of one kind added to its fields.

    Aliases add to the aliases of the field, in order and without repeats. ``columns`` and
    ``markers`` are new members (SPEC §2.3). A term for an unknown field or a field that already
    has columns or markers stops the replay.
    """
    out = json.loads(json.dumps(schema))
    for field, entry in terms.items():
        if field not in out["fields"]:
            raise ValueError("terms name an unknown field: " + field)
        spec = out["fields"][field]
        if "aliases" in entry:
            spec["aliases"] = list(dict.fromkeys([*spec.get("aliases", []), *entry["aliases"]]))
        for member in ("columns", "markers"):
            if member in entry:
                if spec.get(member) is not None:
                    raise ValueError(f"field already has {member}: {field}")
                spec[member] = list(entry[member])
    return gg.Schema.from_dict(out).to_dict()


def _without_new_members(schema: Json) -> Json:
    """Drop the null ``columns`` and ``markers`` of spec 0.12, which the recorded run predates."""
    fields = {
        name: {k: v for k, v in spec.items() if k not in {"columns", "markers"} or v is not None}
        for name, spec in schema["fields"].items()
    }
    return schema | {"fields": fields}


def replay(
    directory: Path, terms_path: Path | None, cache: Path, sources: Path
) -> tuple[Json, list[Json]]:
    """Return the projection of the replay and, for each document, the changed decisions."""
    manifest_raw = (directory / "manifest.json").read_bytes()
    manifest = json.loads(manifest_raw)
    header = json.loads((cache / "runner" / "development" / "header.json").read_bytes())
    if header.get("manifest_sha256") != digest(manifest_raw) or header.get("split") != (
        "development"
    ):
        raise ValueError("the recorded run is not a development run of this manifest")
    recorded = json.loads((cache / "runner" / "development" / "projection.json").read_bytes())
    terms_raw = terms_path.read_bytes() if terms_path is not None else None
    fields = json.loads(terms_raw)["fields"] if terms_raw is not None else {}
    for kind, entries in fields.items():
        for field, entry in entries.items():
            if set(entry) - {"prompt_sha256", *TERMS}:
                raise ValueError(f"unknown term member: {kind}.{field}")
    policy = gg.Policy.from_dict(header["configuration"]["policy"]).to_dict()
    stub = SimpleNamespace(
        manifest=manifest,
        settings={"max_prompt_chars": header["configuration"]["run_policy"]["max_prompt_chars"]},
    )
    outputs, changes = [], []
    for doc in manifest["documents"]:
        if doc["split"] != "development":
            continue
        ident = doc["id"]
        result = json.loads((cache / "runner" / "development" / ident / "result.json").read_bytes())
        text_raw = (sources / (ident + ".txt")).read_bytes()
        if digest(text_raw) != doc["text_sha256"] or result["text_sha256"] != doc["text_sha256"]:
            raise ValueError("reader text digest differs: " + ident)
        schema = FrozenSet.schema(stub, doc)  # type: ignore[arg-type]
        if digest(encoded(_without_new_members(schema))) != result["schema_sha256"]:
            raise ValueError("the manifest schema differs from the recorded schema: " + ident)
        schema = apply_terms(schema, fields.get(doc["kind"], {}))
        receipt = gg.admit(
            text_raw.decode("utf-8"),
            schema,
            result["candidates"],
            policy,
            ident,
            document_source=doc["source"],
        )
        decisions = [
            _projection(d.to_dict()) | {"origin": "core_receipt"} for d in receipt.decisions
        ]
        before = {d["candidate_id"]: d for d in result["output"]["decisions"]}
        for d in decisions:
            old = before[d["candidate_id"]]
            if (old["outcome"], old["codes"]) != (d["outcome"], d["codes"]):
                changes.append(
                    {
                        "document": ident,
                        "candidate_id": d["candidate_id"],
                        "field": d["field"],
                        "value": d["value"],
                        "unit": d["unit"],
                        "before": {"outcome": old["outcome"], "codes": old["codes"]},
                        "after": {"outcome": d["outcome"], "codes": d["codes"]},
                    }
                )
        row = next(r for r in recorded["documents"] if r["id"] == ident)
        outputs.append(row | {"decisions": decisions})
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    provenance = {k: v for k, v in header.items() if k not in {"arm", "split"}} | {
        "replay": {
            "issue": 547,
            "recorded_binding_sha256": recorded["binding_sha256"],
            "core_commit": commit,
            "groundgate": gg.__version__,
            "terms_sha256": digest(terms_raw) if terms_raw is not None else None,
            "model_calls": 0,
        }
    }
    binding = "sha256:" + hashlib.sha256(gg.jcs(provenance).encode("utf-8")).hexdigest()
    public = {
        "manifest_sha256": recorded["manifest_sha256"],
        "labels_sha256": recorded["labels_sha256"],
        "binding_sha256": binding,
        "arm": "runner",
        "split": "development",
        "documents": outputs,
        "provenance": provenance,
    }
    return public, changes


def cases(directory: Path, before: Json, after: Json) -> Json:
    """Return the slots of the development split whose result changes, by kind of change.

    ``gained`` and ``lost`` are right values that the replay admits and the run did not, and the
    reverse. ``escapes_added`` and ``escapes_removed`` are wrong admitted values. ``new_codes``
    are right values that the replay does not admit and that have a decision with a code of
    ``NEW_CODES``.
    """
    manifest = json.loads((directory / "manifest.json").read_bytes())
    labels = json.loads((directory / "labels.json").read_bytes())
    golds = {d["id"]: d for d in labels["documents"]}
    runs = [{d["id"]: d["decisions"] for d in run["documents"]} for run in (before, after)]
    out: Json = {k: [] for k in ("gained", "lost", "escapes_added", "escapes_removed", "new_codes")}
    for doc in manifest["documents"]:
        if doc["split"] != "development":
            continue
        fields = doc.get("schema", manifest["schemas"][doc["kind"]])["fields"]
        for slot in golds[doc["id"]]["fields"]:
            if slot["status"] == "unclear":
                continue
            name, skey = slot["field"], key(slot.get("key"))
            kind = fields[name].get("type", "number")
            wanted = {signature(v, kind) for v in slot.get("values", [])}
            seen = []
            for decisions in runs:
                rows = [
                    (signature(d, kind), d)
                    for d in decisions[doc["id"]]
                    if d["field"] == name
                    and (decision_key(d.get("key")) if fields[name].get("keys") else None) == skey
                ]
                seen.append(rows)
            admitted = [{sig for sig, d in rows if d["outcome"] == "admitted"} for rows in seen]
            base = {"document": doc["id"], "field": name, "label": slot["status"]}
            codes = {}
            for sig, d in seen[1]:
                codes.setdefault(sig, []).append(d["codes"])
            for group, values in (
                ("gained", (admitted[1] - admitted[0]) & wanted),
                ("lost", (admitted[0] - admitted[1]) & wanted),
                ("escapes_added", admitted[1] - admitted[0] - wanted),
                ("escapes_removed", admitted[0] - admitted[1] - wanted),
            ):
                for value, unit in sorted(values):
                    out[group].append(
                        base
                        | {"value": value, "unit": unit, "codes_after": codes.get((value, unit))}
                    )
            for value, unit in sorted(wanted - admitted[1]):
                hit = [c for c in codes.get((value, unit), []) if set(c) & set(NEW_CODES)]
                if hit:
                    out["new_codes"].append(
                        base | {"value": value, "unit": unit, "codes_after": hit}
                    )
    return {k: v for k, v in out.items()} | {"counts": {k: len(v) for k, v in out.items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", type=Path, required=True)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--terms", type=Path)
    group.add_argument("--no-terms", action="store_true")
    ap.add_argument("--cache", type=Path, required=True, help="the binding folder of the run")
    ap.add_argument("--sources", type=Path, required=True, help="the reader texts of the set")
    ap.add_argument("--runs", type=Path, required=True, help="output folder for runner.json")
    args = ap.parse_args(argv)
    public, changes = replay(args.set, args.terms, args.cache, args.sources)
    args.runs.mkdir(parents=True, exist_ok=True)
    (args.runs / "runner.json").write_text(json.dumps(public, separators=(",", ":")) + "\n")
    (args.runs.parent / "changes.json").write_text(json.dumps(changes, indent=1) + "\n")
    recorded = json.loads((args.cache / "runner" / "development" / "projection.json").read_bytes())
    found = cases(args.set, recorded, public)
    (args.runs.parent / "cases.json").write_text(json.dumps(found, indent=1) + "\n")
    print(
        f"{len(public['documents'])} documents, {len(changes)} changed decisions", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
