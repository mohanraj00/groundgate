"""Requested-field measures on sealed labels and final cached decisions (#269).

No model calls, source reads or core decisions occur here. This module does not rescore old sets.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any

from groundgate import Schema, jcs
from groundgate.text import canonical, parse_value

COUNTERS = (
    "present",
    "hits",
    "value_hits",
    "absence_hits",
    "reviews",
    "silent_misses",
    "rejected_right_values",
    "no_right_candidate",
    "escapes",
    "admitted",
    "catches",
    "excluded",
    "unreported_absences",
)

# runner_drop_rounded replays the recorded calls of runner with drop_rounded on (#376).
ARMS = ("baseline", "runner", "runner_drop_rounded")
# Run state for each document of a split: a harness stop, a failed call and archived retries.
DOCUMENT_STATES = ("documents", "incomplete", "transport_error", "transport_retries")
# A projection from #383 on also counts the fields that stopped at search_limit. A run without
# this member keeps its published document_states.
LIMIT_STATES = ("search_limit_documents", "search_limit_fields")
SPLIT_METHOD = "family-hash/1"


RUN_RECORD = "groundgate-run/3"


def final_search_limits(record: Any, runner: str) -> int:
    """Count the fields of a runner record of one version whose final states hold search_limit."""
    if not isinstance(record, list) or not record:
        raise ValueError("a runner record must be a nonempty list")
    header = record[0]
    if not isinstance(header, dict) or header.get("kind") != "header":
        raise ValueError("a runner record must start with its header")
    if header.get("runner") != runner:
        raise ValueError(f"the runner record is {header.get('runner')!r}, not {runner!r}")
    final = record[-1]
    if not isinstance(final, dict) or final.get("kind") != "final":
        raise ValueError("a runner record must end with its final entry")
    fields = final.get("fields")
    if not isinstance(fields, dict) or any(not isinstance(s, list) for s in fields.values()):
        raise ValueError("the final entry needs a state list for each field")
    return sum("search_limit" in states for states in fields.values())


def search_limit_fields(record: Any) -> int:
    """Count the fields of a groundgate-run/3 record that end at search_limit.

    In run/3 (#382) a field records search_limit only when no region fit the first sweep and
    the second sweep sent no call. A field that the second sweep searched does not count.
    """
    return final_search_limits(record, RUN_RECORD)


def split_of(rule: dict[str, Any], family: str) -> str:
    """The split of a source family: development if the first sha256 byte is below the share."""
    first = hashlib.sha256((rule["salt"] + family).encode("utf-8")).digest()[0]
    return "development" if first < rule["development_share"] * 256 else "heldout"


def check_split_rule(manifest: dict[str, Any]) -> None:
    """Recompute the split of each document from the manifest split_rule, if it has one.

    One source family is always in one split. A family with a pilot document is development.
    Every other family takes the split of its salted hash. A manifest without a split_rule
    (bench/requested to bench/requested3) is not checked here.
    """
    rule = manifest.get("split_rule")
    if rule is None:
        return
    share = rule.get("development_share") if isinstance(rule, dict) else None
    if (
        not isinstance(rule, dict)
        or set(rule) != {"method", "salt", "development_share", "fixed_on"}
        or rule["method"] != SPLIT_METHOD
        or not isinstance(rule["salt"], str)
        or not rule["salt"].strip()
        or not isinstance(rule["fixed_on"], str)
        or not rule["fixed_on"].strip()
        or isinstance(share, bool)
        or not isinstance(share, (int, float))
        or not 0 < share < 1
    ):
        raise ValueError("split_rule needs method family-hash/1, a salt, a share and a date")
    families: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in manifest["documents"]:
        family = doc.get("source_family_group")
        if not isinstance(family, str) or not family.strip():
            raise ValueError("a split_rule needs a source_family_group on each document")
        if doc.get("pilot", False) not in {True, False}:
            raise ValueError("pilot must be true or false")
        families[family].append(doc)
    for family, docs in families.items():
        pilot = any(d.get("pilot") is True for d in docs)
        expected = "development" if pilot else split_of(rule, family)
        wrong = sorted(str(d.get("id")) for d in docs if d.get("split") != expected)
        if wrong:
            raise ValueError(f"split differs from the split_rule ({expected}): " + ", ".join(wrong))


def blank_row() -> dict[str, Any]:
    return dict.fromkeys(COUNTERS, 0)


def decision_key(raw: Any) -> Any:
    """Malformed admitted keys are unknown keys, and therefore escapes."""
    try:
        return key(raw)
    except ValueError:
        return ("invalid-key", json.dumps(raw, sort_keys=True))


BOUND_DIGITS = 10


def _round_up(bound: float) -> float:
    step = Decimal(1).scaleb(-BOUND_DIGITS)
    return float(Decimal(bound).quantize(step, rounding=ROUND_CEILING))


def upper95(errors: int, trials: int) -> float | None:
    """One-sided exact Clopper-Pearson upper bound; no trials means no bound.

    The bound is rounded up to BOUND_DIGITS decimals: the last bit of math.log and
    math.exp can change with the Python version, and results.json must not. Rounding
    up keeps it an upper bound.
    """
    if not 0 <= errors <= trials:
        raise ValueError("errors must be between zero and trials")
    if trials == 0:
        return None
    if errors == trials:
        return 1.0
    if errors == 0:
        return _round_up(-math.expm1(math.log(0.05) / trials))
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
    return _round_up(hi)


def ratio(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": k / n if n else None}


def key(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a key must be a nonblank string or null")
    return value


_CURRENCY = re.compile(r"[A-Z]{3}")
_DOCUMENT_MEMBERS = {"aliases", "keys", "unit"}


def same_request(template: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Allow a document schema only its currency, aliases, keys and unit table."""
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), dict):
        return False
    tops = (set(template) | set(schema)) - {"fields", "units"}
    if any(template.get(k) != schema.get(k) for k in tops):
        return False
    if set(schema["fields"]) != set(template["fields"]):
        return False
    for name, field in schema["fields"].items():
        fixed = template["fields"][name]
        if not isinstance(field, dict):
            return False

        def rest(f: dict[str, Any]) -> dict[str, Any]:
            kept = {k: v for k, v in f.items() if k not in _DOCUMENT_MEMBERS}
            return {"type": "number", "multiple": False} | kept

        if rest(field) != rest(fixed):
            return False
        unit, base = field.get("unit"), fixed.get("unit")
        # Only a currency unit changes, to the document's reporting currency.
        if unit != base and not (
            isinstance(unit, str)
            and isinstance(base, str)
            and _CURRENCY.fullmatch(unit)
            and _CURRENCY.fullmatch(base)
        ):
            return False
    return True


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
    # A document with only unclear slots still counts in the sample, but adds no trial.
    present = {row["doc"] for row in rows}
    for row in rows:
        if not row["excluded"]:
            docs[row["doc"]]["admitted"] += row["admitted"]
            docs[row["doc"]]["wrong"] += row["escapes"]
    counts = {name: sum(r[name] for r in rows) for name in COUNTERS}
    n, e = counts["admitted"], counts["escapes"]
    effect = max(1, max((d["admitted"] for d in docs.values()), default=0))
    trials = n // effect
    errors = min(trials, math.ceil(e / effect))
    vb = upper95(errors, trials)
    # The document bound is a bound on admitted values, so its trials are the documents with
    # at least one admitted value. A slice with no admitted value has no document bound.
    admit_docs = sum(d["admitted"] > 0 for d in docs.values())
    wrong_docs = sum(d["wrong"] > 0 for d in docs.values())
    db = upper95(wrong_docs, admit_docs)
    return counts | {
        "documents": len(present),
        "kinds": len({r["kind"] for r in rows if not r["excluded"]}),
        "documents_with_admits": admit_docs,
        "admitted_error_rate": ratio(e, n),
        "miss_rate": ratio(counts["reviews"] + counts["silent_misses"], counts["present"]),
        "right_value_review_share": ratio(counts["reviews"], counts["present"]),
        "silent_miss_share": ratio(counts["silent_misses"], counts["present"]),
        "rejected_right_value_share": ratio(counts["rejected_right_values"], counts["present"]),
        "no_right_candidate_share": ratio(counts["no_right_candidate"], counts["present"]),
        "bounds": {
            "confidence": 0.95,
            "design_effect": effect,
            "design_effect_method": "maximum admitted cluster size; default, not estimated",
            "effective_trials": trials,
            "effective_errors": errors,
            "value_upper95": vb,
            "document_trials": admit_docs,
            "document_errors": wrong_docs,
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
    check_split_rule(manifest)
    limited = {"search_limit" in d for d in run_docs}
    if len(limited) > 1:
        raise ValueError("either every run document has a search_limit count or none has")
    names = DOCUMENT_STATES + (LIMIT_STATES if limited == {True} else ())
    rows = []
    states: dict[str, dict[str, int]] = {}
    for doc in documents:
        template = manifest["schemas"][doc["kind"]]
        schema = doc.get("schema", template)
        Schema.from_dict(schema)
        fields = schema["fields"]
        if not same_request(template, schema):
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
        values_by_slot = {}
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
            values_by_slot[(slot["field"], key(slot.get("key")))] = wanted
        if doc["split"] != split:
            continue
        output = outputs.get(doc["id"], {})
        tally = states.setdefault(doc["kind"], dict.fromkeys(names, 0))
        tally["documents"] += 1
        tally["incomplete"] += output.get("complete") is False
        tally["transport_error"] += output.get("transport_error") is True
        tally["transport_retries"] += output.get("transport_retries", 0)
        if "search_limit_fields" in tally:
            limit = output.get("search_limit", 0)
            if type(limit) is not int or limit < 0:
                raise ValueError("a search_limit count must be a nonnegative integer")
            tally["search_limit_documents"] += limit > 0
            tally["search_limit_fields"] += limit
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
            wanted = values_by_slot[(name, skey)]
            row = blank_row()
            row |= {"doc": doc["id"], "kind": doc["kind"], "field": name, "key": skey}
            if state == "unclear":
                row["excluded"] = 1
                rows.append(row)
                continue
            admitted, reviewed, rejected = set(), set(), set()
            for d in decisions:
                dkey = decision_key(d.get("key")) if spec.get("keys") else None
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
                else:
                    rejected.add(sig)
            row["present"] = len(wanted)
            row["hits"] = row["value_hits"] = len(wanted & admitted)
            row["reviews"] = len((wanted - admitted) & reviewed)
            # A silent miss is a rejected right value or a right value with no candidate.
            missed = wanted - admitted - reviewed
            row["silent_misses"] = len(missed)
            row["rejected_right_values"] = len(missed & rejected)
            row["no_right_candidate"] = len(missed - rejected)
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
                and (decision_key(d.get("key")) if spec.get("keys") else None) not in keys
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
                row = blank_row()
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
        "document_states": {
            "total": {n: sum(v[n] for v in states.values()) for n in names},
            "by_kind": {k: states[k] for k in sorted(states)},
        },
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


def check_coverage(manifest: dict[str, Any], run: dict[str, Any], split: str, name: str) -> None:
    """Refuse a run of another split, or a run that does not hold each document of the split."""
    if run.get("split") != split:
        raise ValueError(f"cached run split is not {split}: {name}")
    if run.get("partial"):
        raise ValueError("cached run is partial: " + name)
    expected = sorted(d["id"] for d in manifest["documents"] if d["split"] == split)
    documents = run.get("documents")
    if not isinstance(documents, list) or any(not isinstance(d, dict) for d in documents):
        raise ValueError("cached run documents must be a list of objects: " + name)
    for d in documents:
        retries = d.get("transport_retries")
        if (
            type(d.get("complete")) is not bool
            or type(d.get("transport_error")) is not bool
            or type(retries) is not int
            or retries < 0
        ):
            raise ValueError(
                "cached run documents need their complete and transport state: " + name
            )
    ids = [d.get("id") for d in documents]
    if any(not isinstance(i, str) for i in ids) or sorted(ids) != expected:
        raise ValueError(f"cached run documents are not exactly the {split} documents: {name}")


def check_provenance(run: dict[str, Any], name: str, manifest_seal: str, seal: str) -> str:
    """Refuse a run whose arm or binding does not match its file name and recorded header."""
    arm, binding, header = run.get("arm"), run.get("binding_sha256"), run.get("provenance")
    if arm not in ARMS or name != arm:
        raise ValueError(f"cached run file must be named for its arm: {name}.json")
    if (
        not isinstance(header, dict)
        or header.get("manifest_sha256") != manifest_seal
        or header.get("labels_sha256") != seal
        or binding != "sha256:" + hashlib.sha256(jcs(header).encode("utf-8")).hexdigest()
    ):
        raise ValueError(f"cached run binding does not match its provenance: {name}.json")
    return str(binding)


def score_set(
    directory: Path,
    split: str,
    *,
    runs: Path | None = None,
    diagnostics: Path | None = None,
    diagnostics_sha256: str | None = None,
) -> dict[str, Any]:
    """Load a requested set, bind all runs to sealed label bytes, and score its final decisions.

    ``runs`` is the folder of cached run projections. It is the set's ``runs`` folder if not
    given. A learning-loop iteration keeps its development runs in ``loop/NN/runs``.
    """
    manifest_raw = (directory / "manifest.json").read_bytes()
    labels_raw = (directory / "labels.json").read_bytes()
    manifest, labels = json.loads(manifest_raw), json.loads(labels_raw)
    seal = "sha256:" + hashlib.sha256(labels_raw).hexdigest()
    manifest_seal = "sha256:" + hashlib.sha256(manifest_raw).hexdigest()
    folder = runs if runs is not None else directory / "runs"
    scored = {}
    bindings = set()
    for path in sorted(folder.glob("*.json")):
        raw = path.read_bytes()
        run = json.loads(raw)
        if run.get("manifest_sha256") != manifest_seal:
            raise ValueError("cached run does not match the frozen manifest: " + path.name)
        if run.get("labels_sha256") != seal:
            raise ValueError("cached run does not match the sealed labels: " + path.name)
        check_coverage(manifest, run, split, path.name)
        bindings.add(check_provenance(run, path.stem, manifest_seal, seal))
        scored[path.stem] = measure(manifest, labels, run, split) | {
            "cache_sha256": "sha256:" + hashlib.sha256(raw).hexdigest()
        }
    if not scored:
        raise ValueError("no cached requested-field runs")
    if len(bindings) != 1:
        raise ValueError("cached runs do not share one configuration and code binding")
    result = {
        "format": "requested-fields/1",
        "labels_sha256": seal,
        "manifest_sha256": "sha256:" + hashlib.sha256(manifest_raw).hexdigest(),
        "runs": scored,
    }
    if (diagnostics is None) != (diagnostics_sha256 is None):
        raise ValueError("diagnostics need an export path and exact digest")
    if diagnostics is not None:
        from .diagnostics import load_export

        assert diagnostics_sha256 is not None
        result["diagnostics"] = load_export(
            diagnostics, diagnostics_sha256, manifest_seal, seal, split
        )
    return result
