"""Approved terms from calibration events, for the replay of #547.

`groundgate calibrate events suggest` reads the calibration events of one profile version and
writes drafts (`groundgate_profile_drafts`, format 1, #642). A `term` draft proposes an alias for
a field from a correction. The drafts are suggestions only: a person approves each term.

This script makes no model call and reads no document. It takes the drafts, the person's
approval file and, if given, an approved terms file such as `terms-547.json`. It writes a terms
file for `requested.replay_terms`: the approved aliases of the drafts are added to the aliases of
their fields, after the aliases that the terms file already has. Each added alias records its
draft: the packet, the line and the origin of the event. Each run appends one batch to `events`,
so a terms file made by earlier runs keeps their records. A draft that the approval file does not
name is listed as not approved and adds nothing.

    PYTHONPATH=bench uv run python -m requested.event_terms --set bench/requested4 --kind sbc \\
        --drafts drafts.json --approval approval.json --terms bench/requested4/terms-547.json \\
        --out terms-547-events.json

The approval file is `{"approved_on": "YYYY-MM-DD", "approver": NAME, "terms": [{"field": F,
"alias": A}, ...]}`. Each approved term must be a `term` draft of the drafts file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from .run_set import TERMS, digest

Json = dict[str, Any]
DRAFTS_FORMAT = 1
MAX_ALIAS = 64  # characters, as in groundgate.calibrate.events
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _term_drafts(drafts: Any) -> list[Json]:
    if (
        not isinstance(drafts, dict)
        or drafts.get("groundgate_profile_drafts") != DRAFTS_FORMAT
        or not isinstance(drafts.get("drafts"), list)
        or not isinstance(drafts.get("profile"), dict)
    ):
        raise ValueError("the drafts must be groundgate_profile_drafts of format 1")
    found = []
    for d in drafts["drafts"]:
        if not isinstance(d, dict) or d.get("draft") != "term":
            continue
        alias = d.get("alias")
        if (
            not isinstance(d.get("field"), str)
            or not isinstance(alias, str)
            or not alias.strip()
            or len(alias) > MAX_ALIAS
            or not isinstance(d.get("packet"), str)
            or type(d.get("line")) is not int
            or not isinstance(d.get("origin"), dict)
        ):
            raise ValueError("a term draft needs a field, an alias, a packet, a line and an origin")
        found.append(d)
    return found


def _approval(raw: Any) -> tuple[Json, set[tuple[str, str]]]:
    if (
        not isinstance(raw, dict)
        or set(raw) != {"approved_on", "approver", "terms"}
        or not isinstance(raw["approved_on"], str)
        or not _DAY.fullmatch(raw["approved_on"])
        or not isinstance(raw["approver"], str)
        or not raw["approver"].strip()
        or not isinstance(raw["terms"], list)
    ):
        raise ValueError("the approval needs approved_on (YYYY-MM-DD), approver and terms")
    approved = set()
    for t in raw["terms"]:
        if (
            not isinstance(t, dict)
            or set(t) != {"field", "alias"}
            or not all(isinstance(t[k], str) for k in t)
        ):
            raise ValueError("an approved term is an object with a field and an alias")
        if (t["field"], t["alias"]) in approved:
            raise ValueError(f"an approved term is listed two times: {t['field']} {t['alias']!r}")
        approved.add((t["field"], t["alias"]))
    return {"approved_on": raw["approved_on"], "approver": raw["approver"]}, approved


def event_terms(
    manifest: Json, kind: str, drafts_raw: bytes, approval_raw: bytes, terms: Json | None
) -> Json:
    """The terms file with the approved aliases of the term drafts of one kind."""
    if kind not in manifest["schemas"]:
        raise ValueError("unknown kind: " + kind)
    fields = manifest["schemas"][kind]["fields"]
    drafts = json.loads(drafts_raw)
    found = _term_drafts(drafts)
    who, approved = _approval(json.loads(approval_raw))
    by_term = {(d["field"], d["alias"]): d for d in found}
    if unknown := sorted(approved - set(by_term)):
        raise ValueError(f"an approved term is not a term draft: {unknown[0]}")
    out = json.loads(json.dumps(terms)) if terms is not None else {"fields": {}}
    if not isinstance(out.get("fields"), dict):
        raise ValueError("the terms file needs fields")
    batches = out.get("events", [])
    if not isinstance(batches, list):
        raise ValueError("the events of a terms file must be a list of batches")
    entries = out["fields"].setdefault(kind, {})
    added, refused = [], []
    for d in found:
        term = {k: d[k] for k in ("field", "alias", "packet", "line", "origin")}
        if (d["field"], d["alias"]) not in approved:
            refused.append(term)
            continue
        if d["field"] not in fields:
            raise ValueError(
                f"a term draft names a field that {kind} does not request: {d['field']}"
            )
        entry = entries.get(d["field"], {})
        if set(entry) - {"prompt_sha256", *TERMS}:
            raise ValueError(f"unknown term member: {kind}.{d['field']}")
        known = [*(fields[d["field"]].get("aliases") or []), *entry.get("aliases", [])]
        if d["alias"].casefold() in {a.casefold() for a in [d["field"], *known]}:
            # The field already has this alias, so the draft adds nothing.
            refused.append(term | {"reason": "the field already has this alias"})
            continue
        entries[d["field"]] = entry | {"aliases": [*entry.get("aliases", []), d["alias"]]}
        added.append(term)
    # Each run adds one batch, so the provenance of earlier batches stays.
    batch = {
        "drafts_sha256": digest(drafts_raw),
        "profile": drafts["profile"],
        "kind": kind,
        **who,
        "added": added,
        "not_added": refused,
    }
    out["events"] = [*batches, batch]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--set", type=Path, required=True)
    ap.add_argument("--kind", required=True, help="the kind of the profile of the events")
    ap.add_argument("--drafts", type=Path, required=True, help="output of events suggest")
    ap.add_argument("--approval", type=Path, required=True, help="the approved terms")
    ap.add_argument("--terms", type=Path, help="an approved terms file to add to")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    manifest = json.loads((args.set / "manifest.json").read_bytes())
    terms = json.loads(args.terms.read_bytes()) if args.terms is not None else None
    try:
        out = event_terms(
            manifest, args.kind, args.drafts.read_bytes(), args.approval.read_bytes(), terms
        )
    except (ValueError, KeyError) as exc:
        ap.error(str(exc))
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    events = out["events"][-1]
    print(f"{len(events['added'])} added, {len(events['not_added'])} not added", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
