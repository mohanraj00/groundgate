"""Requested-field measures on sealed labels and final cached decisions (#269).

No model calls, source reads or core decisions occur here. This module does not rescore old sets.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from groundgate import Schema
from groundgate.text import canonical, parse_value


def upper95(errors: int, trials: int) -> float | None:
    """One-sided exact Clopper-Pearson upper bound; no trials means no bound."""
    if not 0 <= errors <= trials:
        raise ValueError("errors must be between zero and trials")
    if trials == 0:
        return None
    if errors == trials:
        return 1.0
    if errors == 0:
        return -math.expm1(math.log(0.05) / trials)
    # P(X <= errors | p=upper) = .05. Sum in log space to avoid underflow.
    coeff = [
        math.lgamma(trials + 1) - math.lgamma(i + 1) - math.lgamma(trials - i + 1)
        for i in range(errors + 1)
    ]
    lo, hi = errors / trials, 1.0
    for _ in range(70):
        p = (lo + hi) / 2
        if p == 1:
            break
        terms = [c + i * math.log(p) + (trials - i) * math.log1p(-p) for i, c in enumerate(coeff)]
        peak = max(terms)
        log_cdf = peak + math.log(math.fsum(math.exp(x - peak) for x in terms))
        if log_cdf > math.log(0.05):
            lo = p
        else:
            hi = p
    return hi


def ratio(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": k / n if n else None}


def key(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a key must be a nonblank string or null")
    return value


def value(raw: Any, field_type: str) -> str:
    if field_type == "string":
        if not isinstance(raw, str):
            raise ValueError("a string value must be a string")
        normalized = " ".join(raw.split())
        if not normalized:
            raise ValueError("a labeled string cannot be blank")
        return normalized
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise ValueError("a numeric value must be an integer or decimal string")
    parsed = Decimal(raw) if isinstance(raw, int) else parse_value(raw)
    if parsed is None or not parsed.is_finite():
        raise ValueError("a numeric value must be parseable")
    if field_type == "integer" and parsed != parsed.to_integral_value():
        raise ValueError("an integer field needs an integer value")
    return canonical(parsed)


def signature(item: dict[str, Any], field_type: str) -> tuple[str, Any]:
    unit = item.get("unit")
    if unit is not None and not isinstance(unit, str):
        raise ValueError("a unit must be a string or null")
    return value(item.get("value"), field_type), unit


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    docs: dict[str, dict[str, int]] = defaultdict(lambda: {"admitted": 0, "wrong": 0})
    for row in rows:
        if not row["excluded"]:
            docs[row["doc"]]["admitted"] += row["admitted"]
            docs[row["doc"]]["wrong"] += row["escapes"]
    counts = {
        name: sum(r[name] for r in rows)
        for name in (
            "present",
            "hits",
            "value_hits",
            "absence_hits",
            "reviews",
            "silent_misses",
            "escapes",
            "admitted",
            "catches",
            "excluded",
            "unreported_absences",
        )
    }
    n, e = counts["admitted"], counts["escapes"]
    effect = max(1, max((d["admitted"] for d in docs.values()), default=0))
    trials = n // effect
    errors = min(trials, math.ceil(e / effect))
    vb = upper95(errors, trials)
    db = upper95(sum(d["wrong"] > 0 for d in docs.values()), len(docs))
    return counts | {
        "documents": len(docs),
        "kinds": len({r["kind"] for r in rows if not r["excluded"]}),
        "documents_with_admits": sum(d["admitted"] > 0 for d in docs.values()),
        "admitted_error_rate": ratio(e, n),
        "miss_rate": ratio(counts["reviews"] + counts["silent_misses"], counts["present"]),
        "right_value_review_share": ratio(counts["reviews"], counts["present"]),
        "silent_miss_share": ratio(counts["silent_misses"], counts["present"]),
        "bounds": {
            "confidence": 0.95,
            "design_effect": effect,
            "design_effect_method": "maximum admitted cluster size; default, not estimated",
            "effective_trials": trials,
            "effective_errors": errors,
            "value_upper95": vb,
            "document_errors": sum(d["wrong"] > 0 for d in docs.values()),
            "document_upper95": db,
            "combined_upper95": max(vb, db) if vb is not None and db is not None else None,
        },
    }


def measure(
    manifest: dict[str, Any], labels: dict[str, Any], run: dict[str, Any], split: str
) -> dict[str, Any]:
    """Count each final distinct admitted value and each labeled value without a match.

    Labels must cover every requested field/key. `unclear` is an explicit excluded slot.
    The caller binds cached runs to the exact label file by digest before calling this function.
    """
    if labels.get("status") != "sealed":
        raise ValueError("blind labels must be sealed before scoring")
    documents = manifest["documents"]
    doc_ids = [d["id"] for d in documents]
    if len(doc_ids) != len(set(doc_ids)):
        raise ValueError("duplicate manifest document")
    label_docs = labels["documents"]
    if len({d["id"] for d in label_docs}) != len(label_docs):
        raise ValueError("duplicate label document")
    golds = {d["id"]: d for d in label_docs}
    if set(golds) != set(doc_ids):
        raise ValueError("labels must cover exactly the manifest documents")
    run_docs = run["documents"]
    if len({d["id"] for d in run_docs}) != len(run_docs):
        raise ValueError("duplicate run document")
    outputs = {d["id"]: d for d in run_docs}
    if set(outputs) - set(doc_ids):
        raise ValueError("run contains unknown documents")
    rows = []
    for doc in documents:
        template = manifest["schemas"][doc["kind"]]
        schema = doc.get("schema", template)
        Schema.from_dict(schema)
        fields = schema["fields"]
        if set(fields) != set(template["fields"]) or any(
            fields[name].get("type", "number") != template["fields"][name].get("type", "number")
            or fields[name].get("multiple", False)
            != template["fields"][name].get("multiple", False)
            for name in fields
        ):
            raise ValueError(
                "document schemas must keep the kind's fixed requested fields and types"
            )
        expected = {(name, key(k)) for name, f in fields.items() for k in f.get("keys") or [None]}
        slots = golds[doc["id"]]["fields"]
        labeled = [(s["field"], key(s.get("key"))) for s in slots]
        if len(set(labeled)) != len(labeled) or set(labeled) != expected:
            raise ValueError("labels must cover each requested field/key exactly once")
        if doc["split"] not in {"development", "heldout"}:
            raise ValueError("unknown document split")
        for slot in slots:
            spec = fields[slot["field"]]
            state = slot["status"]
            if state not in {"present", "absent", "unclear"}:
                raise ValueError("unknown label state")
            wanted = {signature(v, spec.get("type", "number")) for v in slot.get("values", [])}
            if (state == "present") != bool(wanted):
                raise ValueError("only a present label must have values")
            if any(unit != spec.get("unit") for _, unit in wanted):
                raise ValueError("a label unit must match its requested field")
            if len(wanted) > 1 and not spec.get("multiple", False):
                raise ValueError("a single-value field has multiple labels")
        if doc["split"] != split:
            continue
        output = outputs.get(doc["id"], {})
        decisions = output.get("decisions", [])
        if any(d.get("field") not in fields for d in decisions):
            raise ValueError("a final decision names an unrequested field")
        for d in decisions:
            if d.get("outcome") not in {"admitted", "needs_verification", "rejected"}:
                raise ValueError("unknown final decision outcome")
        nf = {(s["field"], key(s.get("key"))) for s in output.get("not_found", [])}
        if nf - expected:
            raise ValueError("not-found names an unrequested field/key")
        for slot in slots:
            name, skey = slot["field"], key(slot.get("key"))
            spec = fields[name]
            state = slot["status"]
            if state not in {"present", "absent", "unclear"}:
                raise ValueError("unknown label state")
            wanted = {signature(v, spec.get("type", "number")) for v in slot.get("values", [])}
            if state == "present" and not wanted:
                raise ValueError("a present label needs at least one value")
            if state != "present" and wanted:
                raise ValueError("only a present label can have values")
            if len(wanted) > 1 and not spec.get("multiple", False):
                raise ValueError("a single-value field has multiple labels")
            row = {
                n: 0
                for n in (
                    "present",
                    "hits",
                    "value_hits",
                    "absence_hits",
                    "reviews",
                    "silent_misses",
                    "escapes",
                    "admitted",
                    "catches",
                    "excluded",
                    "unreported_absences",
                )
            }
            row |= {"doc": doc["id"], "kind": doc["kind"], "field": name, "key": skey}
            if state == "unclear":
                row["excluded"] = 1
                rows.append(row)
                continue
            admitted, reviewed = set(), set()
            for d in decisions:
                dkey = key(d.get("key")) if spec.get("keys") else None
                if d["field"] != name or dkey != skey:
                    continue
                try:
                    sig = signature(d, spec.get("type", "number"))
                except ValueError:
                    # A malformed admitted value is wrong, not an excluded label.
                    sig = (
                        "invalid:" + json.dumps(d.get("value"), sort_keys=True),
                        json.dumps(d.get("unit"), sort_keys=True),
                    )
                if d["outcome"] == "admitted":
                    admitted.add(sig)
                elif d["outcome"] == "needs_verification":
                    reviewed.add(sig)
            row["present"] = len(wanted)
            row["hits"] = row["value_hits"] = len(wanted & admitted)
            row["reviews"] = len((wanted - admitted) & reviewed)
            row["silent_misses"] = len(wanted - admitted - reviewed)
            row["admitted"] = len(admitted)
            row["escapes"] = len(admitted - wanted)
            row["catches"] = len(reviewed - wanted - admitted)
            if state == "absent" and not admitted:
                row["absence_hits"] = int((name, skey) in nf)
                row["hits"] += row["absence_hits"]
                row["unreported_absences"] = int((name, skey) not in nf)
            rows.append(row)
        # Unknown keys cannot evade scoring by having no matching labeled slot.
        for name, spec in fields.items():
            keys = {key(k) for k in spec.get("keys") or [None]}
            unknown = [
                d
                for d in decisions
                if d["field"] == name
                and (key(d.get("key")) if spec.get("keys") else None) not in keys
            ]
            seen = set()
            for d in unknown:
                if d["outcome"] != "admitted":
                    continue
                try:
                    parsed = signature(d, spec.get("type", "number"))
                except ValueError:
                    parsed = (
                        "invalid:" + json.dumps(d.get("value"), sort_keys=True),
                        json.dumps(d.get("unit"), sort_keys=True),
                    )
                sig = json.dumps([d.get("key"), *parsed], sort_keys=True)
                if sig in seen:
                    continue
                seen.add(sig)
                row = {
                    n: 0
                    for n in (
                        "present",
                        "hits",
                        "value_hits",
                        "absence_hits",
                        "reviews",
                        "silent_misses",
                        "escapes",
                        "admitted",
                        "catches",
                        "excluded",
                        "unreported_absences",
                    )
                }
                row |= {"doc": doc["id"], "kind": doc["kind"], "field": name, "key": d.get("key")}
                row["escapes"] = row["admitted"] = 1
                rows.append(row)
    if not rows:
        raise ValueError("the selected split has no labeled fields")
    by_kind = {
        k: summarize([r for r in rows if r["kind"] == k]) for k in sorted({r["kind"] for r in rows})
    }
    by_field = {
        f: summarize([r for r in rows if r["field"] == f])
        for f in sorted({r["field"] for r in rows})
    }
    pairs = sorted({(r["kind"], r["field"]) for r in rows})
    return {
        "split": split,
        "total": summarize(rows),
        "by_kind": by_kind,
        "by_field": by_field,
        "by_kind_field": {
            k: {
                f: summarize([r for r in rows if r["kind"] == k and r["field"] == f])
                for kk, f in pairs
                if kk == k
            }
            for k in by_kind
        },
    }


def score_set(directory: Path, split: str) -> dict[str, Any]:
    """Load a requested set, bind all runs to sealed label bytes, and score its final decisions."""
    manifest_raw = (directory / "manifest.json").read_bytes()
    labels_raw = (directory / "labels.json").read_bytes()
    manifest, labels = json.loads(manifest_raw), json.loads(labels_raw)
    seal = "sha256:" + hashlib.sha256(labels_raw).hexdigest()
    manifest_seal = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
    runs = {}
    for path in sorted((directory / "runs").glob("*.json")):
        raw = path.read_bytes()
        run = json.loads(raw)
        if run.get("manifest_sha256") != manifest_seal:
            raise ValueError("cached run does not match the frozen manifest: " + path.name)
        if run.get("labels_sha256") != seal:
            raise ValueError("cached run does not match the sealed labels: " + path.name)
        runs[path.stem] = measure(manifest, labels, run, split) | {
            "cache_sha256": "sha256:" + hashlib.sha256(raw).hexdigest()
        }
    if not runs:
        raise ValueError("no cached requested-field runs")
    return {
        "format": "requested-fields/1",
        "labels_sha256": seal,
        "manifest_sha256": "sha256:" + hashlib.sha256(manifest_raw).hexdigest(),
        "runs": runs,
    }
