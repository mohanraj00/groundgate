"""Count the search_limit fields of a set's cached runs into limits.json (#383).

Read-only: this script makes no model call, reads no label, changes no cache file and changes
no results.json. It reads the set's committed run projections and the local cache that they
came from, and writes one new file:

    PYTHONPATH=bench uv run python -m requested.limits --set bench/requested3 \\
        --cache PATH/cache --out bench/requested3/limits.json

Each cached projection must have the same bytes as the committed ``runs/<arm>.json``. Each
cached document result must have the run binding and the manifest source and text digests.
A runner arm counts the fields whose final state list holds ``search_limit``. The baseline arm
has no targeted search, so its count is zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .metrics import search_limit_fields

FORMAT = "requested-limits/1"
STATES = ("documents", "search_limit_documents", "search_limit_fields")


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _plain(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("missing or linked file: " + str(path))
    return path


def count(directory: Path, cache: Path) -> dict[str, Any]:
    """Count search_limit fields for each arm and kind from the cache of a set's runs."""
    manifest_raw = _plain(directory / "manifest.json").read_bytes()
    labels_raw = _plain(directory / "labels.json").read_bytes()
    manifest = json.loads(manifest_raw)
    documents = {d["id"]: d for d in manifest["documents"]}
    runs: dict[str, Any] = {}
    bindings, splits = set(), set()
    for path in sorted((directory / "runs").glob("*.json")):
        raw = _plain(path).read_bytes()
        run = json.loads(raw)
        if run.get("manifest_sha256") != _digest(manifest_raw):
            raise ValueError("run does not match the manifest: " + path.name)
        if run.get("labels_sha256") != _digest(labels_raw):
            raise ValueError("run does not match the labels: " + path.name)
        arm, binding, split = run["arm"], run["binding_sha256"], run["split"]
        if arm != path.stem or split not in {"development", "heldout"}:
            raise ValueError("run file must be named for its arm: " + path.name)
        bindings.add(binding)
        splits.add(split)
        folder = cache / binding.removeprefix("sha256:") / arm / split
        if _plain(folder / "projection.json").read_bytes() != raw:
            raise ValueError("cached projection differs from the committed run: " + path.name)
        states: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(STATES, 0))
        for output in run["documents"]:
            ident = output["id"]
            doc = documents[ident]
            result = json.loads(_plain(folder / ident / "result.json").read_bytes())
            if (
                result.get("binding_sha256") != binding
                or result.get("source_sha256") != doc["source_sha256"]
                or result.get("text_sha256") != doc["text_sha256"]
                or result.get("complete") != output["complete"]
            ):
                raise ValueError("cached result does not match its run: " + ident)
            fields = 0 if arm == "baseline" else search_limit_fields(result["record"])
            tally = states[doc["kind"]]
            tally["documents"] += 1
            tally["search_limit_documents"] += fields > 0
            tally["search_limit_fields"] += fields
        runs[arm] = {
            "run_sha256": _digest(raw),
            "document_states": {
                "total": {n: sum(v[n] for v in states.values()) for n in STATES},
                "by_kind": {k: states[k] for k in sorted(states)},
            },
        }
    if not runs:
        raise ValueError("the set has no runs")
    if len(bindings) != 1 or len(splits) != 1:
        raise ValueError("the runs do not share one binding and one split")
    return {
        "format": FORMAT,
        "method": (
            "bench/requested/limits.py: for each document of a run, the fields whose final "
            "runner state list holds search_limit, read from the local cache of that run"
        ),
        "manifest_sha256": _digest(manifest_raw),
        "labels_sha256": _digest(labels_raw),
        "binding_sha256": bindings.pop(),
        "split": splits.pop(),
        "runs": runs,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--set", type=Path, required=True, help="requested set folder")
    ap.add_argument("--cache", type=Path, required=True, help="local cache of the set's runs")
    ap.add_argument("--out", type=Path, required=True, help="new limits.json to write")
    args = ap.parse_args()
    if args.out.exists():
        ap.error("the output exists; this script writes a new file only")
    try:
        limits = count(args.set.resolve(), args.cache.resolve())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        ap.error(str(exc))
    args.out.write_text(json.dumps(limits, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for arm, run in sorted(limits["runs"].items()):
        states = run["document_states"]
        for kind, row in [("total", states["total"]), *sorted(states["by_kind"].items())]:
            print(
                f"{arm} {kind}: {row['search_limit_documents']} of {row['documents']} documents, "
                f"{row['search_limit_fields']} fields"
            )


if __name__ == "__main__":
    main()
