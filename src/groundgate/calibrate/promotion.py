"""groundgate calibrate promotion (#747): one measure as the evidence of an outside decision.

    groundgate calibrate promotion --report DIR/report.json --profile DIR/profile.json \
        --collection C [--base REF] --out OUT

The step reads one report of ``calibrate measure`` and the draft profile of that report. It
writes two texts in the formats of entelos v0.7.0: OUT/manifest.json, the content manifest of
a profile promotion with the items ``measure`` and ``profile``, and OUT/summary.json, the
measure summary. An approver outside groundgate compares each bound of the summary with its
limit. The step decides nothing, and it calls no model.

A route is in the summary when the report gives it an admitted value. The step refuses a
report with a route that is not measured: a route with the status ``draft``, or a route with
an admitted value that no label covers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from groundgate.model import PacketError
from groundgate.pack import _no_twice
from groundgate.profile import MAX_FILE as MAX_PROFILE
from groundgate.profile import ROUTES, check_profile

from .measure import REPORT_FORMAT, MeasureError, _read_bytes

MANIFEST_FORMAT = "entelos.content/1"
SUMMARY_FORMAT = "entelos.measure/1"
MEDIA_TYPE = "application/json"
_NAME = re.compile(r"[A-Za-z0-9._-]{1,128}\Z")  # a collection name of a content manifest
_BOUND = re.compile(r"[01](?:\.[0-9]+)?\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


class PromotionError(MeasureError):
    """The report or the profile cannot be the evidence of a promotion."""


def bound_bp(bound: object) -> int:
    """The bound in basis points, rounded up: the smallest integer that is not less than the
    bound times 10000. ``bound`` is a decimal string from 0 to 1."""
    if type(bound) is not str or _BOUND.match(bound) is None:
        raise PromotionError(f"the bound {bound!r} is not a decimal string from 0 to 1")
    whole, _, places = bound.partition(".")
    bp = int(whole) * 10000 + int(places[:4].ljust(4, "0")) + bool(places[4:].strip("0"))
    if bp > 10000:
        raise PromotionError(f"the bound {bound!r} is more than 1")
    return bp


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _json(data: bytes, what: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_twice)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise PromotionError(f"the {what} is not JSON: {e}") from None


def _count(x: object) -> bool:
    return type(x) is int and x >= 0


def _digest(obj: Any, name: str, what: str) -> str:
    value = obj.get(name) if isinstance(obj, dict) else None
    if type(value) is not str or _DIGEST.match(value) is None:
        raise PromotionError(f"the {what} has no digest {name}")
    return value


def _routes(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The route rows of the report with an admitted value, by field and then by route. Refuse
    a route that is not measured."""
    fields = report.get("fields")
    if not isinstance(fields, dict):
        raise PromotionError("the report has no fields")
    rows = []
    for name in sorted(fields):
        routes = fields[name].get("routes") if isinstance(fields[name], dict) else None
        if not isinstance(routes, dict) or set(routes) != set(ROUTES):
            raise PromotionError(f"the field {name!r} of the report has no route table")
        for route in sorted(routes):
            row, where = routes[route], f"the route {route} of the field {name!r}"
            if not isinstance(row, dict) or not (
                _count(row.get("admitted")) and _count(row.get("unscored"))
            ):
                raise PromotionError(f"{where} has no counts in the report")
            if row["unscored"] > 0:
                raise PromotionError(
                    f"{where} is not measured: no label covers "
                    f"{row['unscored']} of its admitted values"
                )
            if row["admitted"] == 0:
                continue  # the profile has no row for this route, and the summary has none
            if row.get("status") != "measured":
                raise PromotionError(
                    f"{where} is not measured: its status is "
                    f"{row.get('status')!r} with the bound {row.get('bound')!r} and the "
                    f"target {report.get('target')!r}"
                )
            rows.append({"field": name, "route": route, "bound": row.get("bound")})
    if not rows:
        raise PromotionError("the report has no route with an admitted value")
    return rows


def promotion(
    report_bytes: bytes, profile_bytes: bytes, collection: str, base: str = ""
) -> tuple[str, dict[str, Any]]:
    """The promotion of the draft profile ``profile_bytes`` with the measure ``report_bytes``:
    the exact text of the content manifest, and the measure summary. The partition of the
    manifest is the profile id. ``base`` is the empty string for the first proposal of a
    profile, or the candidate reference of the proposal that this one changes. The digest of
    an item is the SHA-256 of the bytes that this function gets. Raises ``PromotionError``."""
    if type(collection) is not str or _NAME.match(collection) is None:
        raise PromotionError(
            "the collection must be 1 to 128 characters from A-Z, a-z, 0-9, '.', '_' and '-'"
        )
    if type(base) is not str or (base and _DIGEST.match(base) is None):
        raise PromotionError("the base must be empty, or sha256: and 64 lowercase hex digits")
    report = _json(report_bytes, "report")
    version = report.get("groundgate_calibration_report") if isinstance(report, dict) else None
    if type(version) is not int or version != REPORT_FORMAT:
        raise PromotionError(f"the report is not a calibration report of format {REPORT_FORMAT}")
    if len(profile_bytes) > MAX_PROFILE:
        raise PromotionError(f"the profile is more than {MAX_PROFILE} bytes")
    try:
        profile = check_profile(_json(profile_bytes, "profile"))
    except PacketError as e:
        raise PromotionError(f"the profile is not valid: {e}") from None
    if profile.entry() != report.get("draft_profile"):
        raise PromotionError(
            "the profile is not the draft profile of the report: promote the profile.json "
            "that calibrate measure wrote with this report"
        )
    gold = _digest(report, "gold_sha256", "report")
    # the gold set digest covers the gold labels; with an audit, its digest covers the others
    audit = report.get("audit")
    labels = gold if audit is None else _digest(audit, "audit_sha256", "audit of the report")
    rows = _routes(report)
    # the route table of the profile states the same measure as the report
    table = {(r["field"], r["route"]): r for r in profile.body.get("routes", [])}
    if profile.body.get("gold_sha256") != gold or set(table) != {
        (r["field"], r["route"]) for r in rows
    }:
        raise PromotionError("the route table of the profile does not agree with the report")
    for r in rows:
        row = table[r["field"], r["route"]]
        if row.get("status") != "measured" or row.get("bound") != r["bound"]:
            raise PromotionError(
                f"the route {r['route']} of the field {r['field']!r} of the profile does not "
                "agree with the report"
            )
    measure_digest, profile_digest = _sha(report_bytes), _sha(profile_bytes)
    manifest = {
        "format": MANIFEST_FORMAT,
        "collection": collection,
        "partition": profile.id,
        "base": base,
        "items": [
            {"item_id": "measure", "digest": measure_digest, "size": len(report_bytes),
             "media_type": MEDIA_TYPE},
            {"item_id": "profile", "digest": profile_digest, "size": len(profile_bytes),
             "media_type": MEDIA_TYPE},
        ],
        "metadata": {"profile_id": profile.id, "profile_version": profile.version},
    }  # fmt: skip
    summary = {
        "format": SUMMARY_FORMAT,
        "profile_digest": profile_digest,
        "measure_digest": measure_digest,
        "gold_digest": gold,
        "labels_digest": labels,
        "routes": [
            {"field": r["field"], "route": r["route"], "bound_bp": bound_bp(r["bound"])}
            for r in rows
        ],
    }
    return json.dumps(manifest, separators=(",", ":")), summary


def run(
    report_path: Path, profile_path: Path, collection: str, base: str, out: Path
) -> dict[str, Any]:
    """Read the two files one time each. Write OUT/manifest.json, the exact manifest text with
    no line break at its end, and OUT/summary.json. Give the summary."""
    names = ("manifest.json", "summary.json")
    if out.exists() and (out.is_symlink() or not out.is_dir()):
        raise PromotionError(f"{out} is not a directory")
    if any((out / n).exists() or (out / n).is_symlink() for n in names):
        raise PromotionError(f"{out} has a manifest or a summary already; use a new directory")
    manifest, summary = promotion(
        _read_bytes(report_path), _read_bytes(profile_path), collection, base
    )
    out.mkdir(parents=True, exist_ok=True)
    bodies = (manifest, json.dumps(summary, indent=1) + "\n")
    for n, body in zip(names, bodies, strict=True):
        with open(out / n, "x", encoding="utf-8") as f:  # "x": never write over a file
            f.write(body)
    return summary


def add_parser(sub: Any) -> None:
    p = sub.add_parser("promotion", help="a measure as the evidence of an outside decision")
    p.add_argument("--report", type=Path, required=True, help="report.json of calibrate measure")
    p.add_argument("--profile", type=Path, required=True, help="profile.json of that measure")
    p.add_argument("--collection", required=True, help="the collection of the manifest")
    p.add_argument("--base", default="", help="the candidate reference of the proposal before")
    p.add_argument("--out", type=Path, required=True, help="a directory for the two files")


def main(args: argparse.Namespace) -> None:
    try:
        summary = run(args.report, args.profile, args.collection, args.base, args.out)
    except (MeasureError, OSError) as e:
        raise SystemExit(f"calibrate promotion: {e}") from None
    largest = max(r["bound_bp"] for r in summary["routes"])
    print(
        f"wrote {args.out}/manifest.json and summary.json: {len(summary['routes'])} routes, "
        f"the largest bound is {largest} basis points"
    )
