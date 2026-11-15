"""groundgate calibrate measure: the field measure of a profile on a gold set of the user (#640).

    groundgate calibrate measure --profile P --gold G --split S --out DIR \
        [--target 0.05] [--date YYYY-MM-DD] [--audit A] [--audit-since YYYY-MM-DD]

The measure reads only the profile P, the gold set G, the split file S and the audit set A. It
calls no model: the candidates and the judgments of a run are recorded files in G. The gate
decides each document with the profile, and the measure compares each admitted value with its
label.

The gold set (format 1) is a directory:

    G/docs/<doc>.txt          the document text, in Unicode NFC
    G/candidates/<doc>.json   the recorded candidates of the extractor
    G/judgments/<doc>.json    optional: the recorded judgments
    G/labels.json             {"groundgate_gold": 1, "labels": {doc: {field: label}}}

A label value is the canonical value of the receipt, as a string. Null says that the document
has no value for the field. For a field with keys, the label is an object {key: value or null},
and a value is right only under its own key. A field or a key that a document does not list is
not scored. A route or a threshold with an admitted value that has no label is not measured.

The split file (format 1) is {"groundgate_split": 1, "documents": {doc: part}}, where a part is
"calibration" or "test". The calibration part picks the judge threshold, and the test part gives
the numbers of the report. With --audit A, the blind audit labels of the audit set A (SPEC
§4.18, ``groundgate.calibrate.audit``) count with the test part. The audit rate and the alerts
come from the decisions of P as it is, not from those of the draft. No other label has an input:
a review answer and the decision of an approver never count for a bound. DIR gets report.json,
REPORT.md and profile.json, the draft profile change. The command never writes the input
profile.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from groundgate.admit import admit
from groundgate.canonical import SPEC_VERSION, jcs
from groundgate.model import PacketError
from groundgate.pack import _no_twice
from groundgate.profile import ROUTES, check_profile, load_profile

from .stats import upper_95

REPORT_FORMAT = 1
GOLD_FORMAT = 1
SPLIT_FORMAT = 1
GOLD_PREFIX = "groundgate-gold/1:"
SPLIT_PREFIX = "groundgate-split/1:"
PARTS = ("calibration", "test")
MAX_FILE = 16 << 20  # bytes of one gold set file, before it is parsed
MAX_DOCUMENTS = 10_000
MAX_THRESHOLDS = 100  # the thresholds that the operating point tries at full precision
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")


class MeasureError(Exception):
    """The gold set, the split file, the profile or the output directory is not valid."""


# ----------------------------------------------------------------------------- reading


def _read_bytes(path: Path) -> bytes:
    """The bytes of a regular file of at most MAX_FILE bytes. A link is refused, so a gold set
    cannot point the measure at a file outside it."""
    if path.is_symlink() or not path.is_file():
        raise MeasureError(f"{path} is not a regular file")
    with open(path, "rb") as f:
        data = f.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise MeasureError(f"{path} is more than {MAX_FILE} bytes")
    return data


def _read_json(path: Path) -> Any:
    try:
        return json.loads(_read_bytes(path).decode("utf-8"), object_pairs_hook=_no_twice)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        raise MeasureError(f"{path} is not JSON: {e}") from None


@dataclass(frozen=True)
class GoldDoc:
    name: str
    text: str
    candidates: list[Any]
    judgments: list[Any] | None
    labels: dict[str, Any]  # field: a value or null, or {key: a value or null}


@dataclass(frozen=True)
class Gold:
    docs: dict[str, GoldDoc]
    sha256: str


def _is_value(v: object) -> bool:
    return v is None or isinstance(v, str)


def _is_keyed(v: object) -> bool:
    return isinstance(v, dict) and bool(v) and all(_is_value(x) for x in v.values())


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def read_gold(root: Path) -> Gold:
    """Read and check a gold set of format 1, and compute its digest."""
    if root.is_symlink() or not root.is_dir():
        raise MeasureError(f"{root} is not a directory")
    for sub in ("docs", "candidates", "judgments"):
        if (root / sub).is_symlink():
            raise MeasureError(f"{root / sub} is a link; a gold set holds its own files")
    lab = _read_json(root / "labels.json")
    if not isinstance(lab, dict) or set(lab) != {"groundgate_gold", "labels"}:
        raise MeasureError("labels.json must be an object with groundgate_gold and labels only")
    if isinstance(lab["groundgate_gold"], bool) or lab["groundgate_gold"] != GOLD_FORMAT:
        raise MeasureError(f"groundgate_gold must be {GOLD_FORMAT}")
    labels = lab["labels"]
    if not isinstance(labels, dict) or not labels:
        raise MeasureError("labels must be an object with one entry for each document")
    if len(labels) > MAX_DOCUMENTS:
        raise MeasureError(f"a gold set has at most {MAX_DOCUMENTS} documents")
    texts = sorted(p.stem for p in (root / "docs").glob("*.txt"))
    if texts != sorted(labels):
        raise MeasureError("labels.json must list each document of docs/ and no other")
    files: dict[str, dict[str, str | None]] = {}
    docs: dict[str, GoldDoc] = {}
    for name in sorted(labels):
        if not _NAME.match(name):
            raise MeasureError(f"the document name {name!r} has a character that is not allowed")
        row = labels[name]
        if not isinstance(row, dict) or not all(
            isinstance(k, str) and (_is_value(v) or _is_keyed(v)) for k, v in row.items()
        ):
            raise MeasureError(
                f"the labels of {name} must map a field to a string or null, or to an object "
                "from a key to a string or null"
            )
        raw = _read_bytes(root / "docs" / f"{name}.txt")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise MeasureError(f"docs/{name}.txt is not UTF-8") from None
        if not unicodedata.is_normalized("NFC", text):
            raise MeasureError(f"docs/{name}.txt is not NFC")
        craw = _read_bytes(root / "candidates" / f"{name}.json")
        cands = _read_json(root / "candidates" / f"{name}.json")
        if not isinstance(cands, list):
            raise MeasureError(f"candidates/{name}.json must be a list")
        jpath = root / "judgments" / f"{name}.json"
        jraw: bytes | None = None
        judg: list[Any] | None = None
        if jpath.exists() or jpath.is_symlink():
            jraw = _read_bytes(jpath)
            judg = _read_json(jpath)
            if not isinstance(judg, list):
                raise MeasureError(f"judgments/{name}.json must be a list")
        files[name] = {
            "text": _sha(raw),
            "candidates": _sha(craw),
            "judgments": None if jraw is None else _sha(jraw),
        }
        docs[name] = GoldDoc(name, text, cands, judg, dict(row))
    body = {"groundgate_gold": GOLD_FORMAT, "files": files, "labels": labels}
    return Gold(docs, _sha((GOLD_PREFIX + jcs(body)).encode("utf-8")))


def read_split(path: Path, gold: Gold) -> tuple[dict[str, str], str]:
    """The part of each gold document, and the digest of the split."""
    obj = _read_json(path)
    if not isinstance(obj, dict) or set(obj) != {"groundgate_split", "documents"}:
        raise MeasureError("a split file must be an object with groundgate_split and documents")
    if isinstance(obj["groundgate_split"], bool) or obj["groundgate_split"] != SPLIT_FORMAT:
        raise MeasureError(f"groundgate_split must be {SPLIT_FORMAT}")
    parts = obj["documents"]
    if not isinstance(parts, dict) or sorted(parts) != sorted(gold.docs):
        raise MeasureError("the split must give a part for each gold document and no other")
    if any(v not in PARTS for v in parts.values()):
        raise MeasureError("a part must be calibration or test")
    if "test" not in parts.values():
        raise MeasureError("the split has no test document, so there is nothing to measure")
    return dict(parts), _sha((SPLIT_PREFIX + jcs(obj)).encode("utf-8"))


# ----------------------------------------------------------------------------- scoring


def _same(value: str | None, label: str, numeric: bool) -> bool:
    """True when the admitted value is the label. For a number or integer field, two numbers
    are the same at the same value, so "40" and "40.0" are the same. For each other field type
    the texts must be equal, so the string "001" is not the label "1"."""
    if value is None:
        return False
    if value == label or not numeric:
        return value == label
    try:
        return Decimal(value) == Decimal(label)
    except (InvalidOperation, ValueError):
        return False


@dataclass
class Route:
    admitted: int = 0
    errors: int = 0
    unscored: int = 0  # admitted values that no label covers

    def passes(self, target: Decimal) -> bool:
        """True when the route has an admitted value, each admitted value has a label, and the
        bound is below the target."""
        bound = Decimal(str(upper_95(self.errors, self.admitted)))
        return self.admitted > 0 and self.unscored == 0 and bound < target

    def summary(self, target: Decimal) -> dict[str, Any]:
        bound = upper_95(self.errors, self.admitted)
        return {
            "admitted": self.admitted,
            "errors": self.errors,
            "error_rate": _rate(self.errors, self.admitted),
            "bound": _decimal(bound),
            "unscored": self.unscored,
            "status": "measured" if self.passes(target) else "draft",
        }


@dataclass
class FieldScore:
    scored: int = 0
    with_value: int = 0
    review: int = 0
    missed: int = 0
    routes: dict[str, Route] = field(default_factory=lambda: {r: Route() for r in ROUTES})


def _rate(k: int, n: int) -> str | None:
    return None if n == 0 else _decimal(round(k / n, 4))


def _decimal(x: float) -> str:
    """A rate as a decimal string with at most 4 places and no exponent."""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def _units(doc: str, name: str, label: Any, keys: tuple[str, ...] | None) -> dict[str | None, Any]:
    """The scored labels of one field in one document: one for each key of a field with keys,
    and one, under None, for a field with no keys."""
    if keys is None:
        if not _is_value(label):
            raise MeasureError(f"{doc}: {name!r} has no keys, so its label is a string or null")
        return {None: label}
    if not _is_keyed(label):
        raise MeasureError(
            f"{doc}: {name!r} has keys, so its label is an object from a key to a string or null"
        )
    for k in label:
        # the gate admits a candidate only with a key that is equal to a schema key (SPEC §3.1),
        # so a label key is compared in the same way: with no fold
        if k not in keys:
            raise MeasureError(f"{doc}: the label of {name!r} names {k!r}, which is not a key")
    return dict(label)


def score(profile: Mapping[str, Any], gold: Gold, docs: Sequence[str]) -> dict[str, FieldScore]:
    """Decide each document of ``docs`` with ``profile`` and score it against its labels. A
    field with keys is scored for each key: a value is right only under its own key."""
    # the resolved schema: it gives the type and the keys of a field that comes from a template
    resolved = check_profile(profile).schema.fields
    numeric = {n for n, f in resolved.items() if f.type in ("number", "integer")}
    out = {name: FieldScore() for name in sorted(resolved)}
    for name in docs:
        g = gold.docs[name]
        for f in g.labels:
            if f not in resolved:
                raise MeasureError(f"the labels of {name} name {f!r}, which the profile has not")
        units = {f: _units(name, f, g.labels[f], resolved[f].keys) for f in sorted(g.labels)}
        try:
            receipt = admit(g.text, None, g.candidates, None, name, g.judgments, profile=profile)
        except PacketError as e:
            raise MeasureError(f"{name}: the gate refused the packet: {e}") from None
        by_unit: dict[tuple[str, str | None], list[Any]] = {}
        for d in receipt.decisions:
            if d.field not in out:
                continue
            k = d.key if resolved[d.field].keys is not None else None
            if d.record is None and d.field in units and k in units[d.field]:
                by_unit.setdefault((d.field, k), []).append(d)
            elif d.outcome == "admitted":
                # no label can say if this value is right: a field or a key that the labels of
                # the document do not list, or a member field of a record
                route = "cleared" if "MODEL_CLEARED" in d.codes else "checked"
                out[d.field].routes[route].unscored += 1
        for f, by_key in units.items():
            s = out[f]
            for k, label in by_key.items():
                s.scored += 1
                s.with_value += label is not None
                ds = by_unit.get((f, k), [])
                seen: set[tuple[str, str | None]] = set()
                right = False
                for d in ds:
                    if d.outcome != "admitted":
                        continue
                    route = "cleared" if "MODEL_CLEARED" in d.codes else "checked"
                    if (route, d.value) in seen:
                        continue  # one fact is one value, however many candidates propose it
                    seen.add((route, d.value))
                    ok = label is not None and _same(d.value, label, f in numeric)
                    s.routes[route].admitted += 1
                    s.routes[route].errors += not ok
                    right = right or ok
                if not seen and any(d.outcome == "needs_verification" for d in ds):
                    s.review += 1
                if label is not None and not right:
                    s.missed += 1
    return out


def _pooled(a: Mapping[str, FieldScore], b: Mapping[str, FieldScore]) -> dict[str, FieldScore]:
    """The sum of two scores of one profile: the test part and the audit documents."""
    out = {}
    for name in a:
        x, y = a[name], b[name]
        out[name] = FieldScore(
            x.scored + y.scored, x.with_value + y.with_value, x.review + y.review,
            x.missed + y.missed,
            {r: Route(x.routes[r].admitted + y.routes[r].admitted,
                      x.routes[r].errors + y.routes[r].errors,
                      x.routes[r].unscored + y.routes[r].unscored) for r in ROUTES},
        )  # fmt: skip
    return out


# ----------------------------------------------------------------------- operating point


def _clear(profile: Mapping[str, Any], t: float | None) -> dict[str, Any]:
    """The profile with ``t`` as clear.KEY_NOT_AT_VALUE, or with no clear threshold."""
    p = copy.deepcopy(dict(profile))
    judge = p["policy"]["judge"]
    clear = {k: v for k, v in judge.get("clear", {}).items() if k != "KEY_NOT_AT_VALUE"}
    if t is not None:
        clear["KEY_NOT_AT_VALUE"] = t
    if clear:
        judge["clear"] = clear
    else:
        judge.pop("clear", None)
    return p


def _thresholds(profile: Mapping[str, Any], gold: Gold, docs: Sequence[str]) -> list[float]:
    """The distinct p of the key judgments of the profile judge on ``docs``, sorted."""
    judge = profile["policy"]["judge"]
    ps: set[float] = set()
    for name in docs:
        for j in gold.docs[name].judgments or []:
            if (
                isinstance(j, dict)
                and j.get("question") == "key"
                and j.get("judge") == {"id": judge["id"], "digest": judge["digest"]}
                and isinstance(j.get("p"), (int, float))
                and not isinstance(j.get("p"), bool)
                and 0 <= j["p"] <= 1
            ):
                ps.add(float(j["p"]))
    if len(ps) > MAX_THRESHOLDS:
        # each threshold is one pass over the calibration part, so the count has a limit: two
        # decimal places, rounded up, so that a tried threshold never clears more than its p
        ps = {min(1.0, math.ceil(p * 100) / 100) for p in ps}
    return sorted(ps)


def operating_point(
    profile: Mapping[str, Any], gold: Gold, docs: Sequence[str], target: Decimal
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pick the lowest clear.KEY_NOT_AT_VALUE whose pooled ``cleared`` bound on ``docs`` is
    below ``target``. A threshold that clears a value with no label does not pass. Give the
    profile at that point and the row of each threshold tried."""
    tried: list[dict[str, Any]] = []
    chosen: float | None = None
    for t in _thresholds(profile, gold, docs):
        scores = score(_clear(profile, t), gold, docs)
        pooled = Route(
            sum(s.routes["cleared"].admitted for s in scores.values()),
            sum(s.routes["cleared"].errors for s in scores.values()),
            sum(s.routes["cleared"].unscored for s in scores.values()),
        )
        ok = pooled.passes(target)
        tried.append(
            {"threshold": t, "admitted": pooled.admitted, "errors": pooled.errors,
             "bound": _decimal(upper_95(pooled.errors, pooled.admitted)),
             "unscored": pooled.unscored, "passes": ok}
        )  # fmt: skip
        if ok and chosen is None:
            chosen = t
    return _clear(profile, chosen), tried


# ------------------------------------------------------------------------------ report


def _next_version(version: str) -> str:
    m = _VERSION.match(version)
    assert m is not None  # check_profile has checked the form
    return f"{m[1]}.{m[2]}.{int(m[3]) + 1}"


def measure(
    profile: Mapping[str, Any],
    gold: Gold,
    parts: Mapping[str, str],
    split_sha256: str,
    target: Decimal,
    date: str,
    audit: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The report and the draft profile change. ``profile`` is not changed. ``audit`` is the
    ``AuditSet`` of the profile, or None: its labelled documents count with the test part. The
    ``audit`` member of the report has the numbers of ``profile``, not those of the draft."""
    checked = check_profile(profile)
    calibration = sorted(d for d, p in parts.items() if p == "calibration")
    test = sorted(d for d, p in parts.items() if p == "test")
    point: dict[str, Any] = {"judge": None, "KEY_NOT_AT_VALUE": None, "tried": []}
    measured_profile: Mapping[str, Any] = profile
    if checked.policy.judge is not None:
        measured_profile, tried = operating_point(profile, gold, calibration, target)
        clear = measured_profile["policy"]["judge"].get("clear", {})
        point = {
            "judge": {"id": checked.policy.judge.id, "digest": checked.policy.judge.digest},
            "KEY_NOT_AT_VALUE": clear.get("KEY_NOT_AT_VALUE"),
            "tried": tried,
        }
    scores = score(measured_profile, gold, test)
    documents = len(test)
    if audit is not None:
        names = sorted(audit.gold.docs)
        # the monitor of the profile version of the log: its decisions, not those of the draft
        logged_audit = draft_audit = score(measured_profile, audit.gold, names)
        logged = _pooled(scores, draft_audit)
        if measured_profile != profile:  # the draft has another clear threshold
            logged_audit = score(profile, audit.gold, names)
            logged = _pooled(score(profile, gold, test), logged_audit)
        scores = _pooled(scores, draft_audit)
        documents += len(names)
    fields: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for name, s in scores.items():
        routes = {r: s.routes[r].summary(target) for r in ROUTES}
        fields[name] = {
            "scored": s.scored,
            "with_value": s.with_value,
            "review": s.review,
            "review_share": _rate(s.review, s.scored),
            "missed": s.missed,
            "miss_rate": _rate(s.missed, s.with_value),
            "routes": routes,
        }
        for r, sm in routes.items():
            if sm["admitted"]:
                rows.append(
                    {"field": name, "route": r, "status": sm["status"], "date": date,
                     "documents": documents, "bound": sm["bound"]}
                )  # fmt: skip
    draft = copy.deepcopy(dict(measured_profile))
    draft["version"] = _next_version(checked.version)
    draft["routes"] = rows
    draft["gold_sha256"] = gold.sha256
    try:
        draft_checked = check_profile(draft)
    except PacketError as e:
        raise MeasureError(f"the draft profile is not valid: {e}") from None
    report = {
        "groundgate_calibration_report": REPORT_FORMAT,
        "spec": SPEC_VERSION,
        "date": date,
        "profile": checked.entry(),
        "gold_sha256": gold.sha256,
        "split_sha256": split_sha256,
        "documents": {"calibration": len(calibration), "test": len(test)},
        "target": str(target),
        "operating_point": point,
        "fields": fields,
        "draft_profile": draft_checked.entry(),
    }
    if audit is not None:
        from .audit import rate

        summaries = [(n, r, s.routes[r].summary(target)) for n, s in logged.items() for r in ROUTES]
        # the admitted values of the profile version that an audit label covers
        covered = sum(r.admitted for s in logged_audit.values() for r in s.routes.values())
        report["audit"] = {
            "audit_sha256": audit.sha256,
            "seed": audit.seed,
            "since": audit.since,
            "picked": audit.picked,
            "documents": len(audit.gold.docs),
            "admitted": covered,
            "skipped": audit.skipped,
            "routes": [
                {"field": n, "route": r, **sm}
                for n, r, sm in summaries
                if sm["admitted"] + sm["unscored"] > 0
            ],
            "rate": rate([sm for _, _, sm in summaries], covered),
            "alerts": [
                {"field": n, "route": r, "bound": sm["bound"]}
                for n, r, sm in summaries
                if sm["admitted"] > 0 and Decimal(sm["bound"]) >= target
            ],
        }
    return report, draft


def _audit_lines(report: Mapping[str, Any]) -> list[str]:
    a = report.get("audit")
    if a is None:
        return []
    lines = [
        f"- Blind audit: `{a['audit_sha256']}`, {a['documents']} labelled documents of "
        f"{a['picked']} picked, {a['admitted']} admitted values. The numbers count them with "
        f"the test part. Next audit rate: {a['rate']}."
    ]
    lines += [
        f"- The profile version of the log, {_cell(x['field'])} {x['route']}: "
        f"{x['admitted']} admitted, {x['errors']} errors, {x['unscored']} with no label, "
        f"bound {x['bound']} ({x['status']})."
        for x in a["routes"]
    ]
    lines += [
        f"- Alert: the bound of {_cell(x['field'])} on the route {x['route']} is "
        f"{x['bound']}, not below the target."
        for x in a["alerts"]
    ]
    return lines


def _cell(x: object) -> str:
    """A table cell: a schema name can hold a pipe or a line end, so both are escaped."""
    s = "-" if x is None else str(x)
    return s.replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def markdown(report: Mapping[str, Any]) -> str:
    p, d = report["profile"], report["draft_profile"]
    point = report["operating_point"]
    lines = [
        f"# Calibration report: {_cell(p['id'])} {_cell(p['version'])}",
        "",
        f"- Profile: `{p['sha256']}`",
        f"- Gold set: `{report['gold_sha256']}`",
        f"- Split: `{report['split_sha256']}`, {report['documents']['calibration']} calibration "
        f"and {report['documents']['test']} test documents",
        f"- Target bound: {report['target']}. Date: {report['date']}. Spec {report['spec']}.",
        f"- Operating point: clear.KEY_NOT_AT_VALUE = {_cell(point['KEY_NOT_AT_VALUE'])}",
        f"- Draft profile: {_cell(d['version'])} `{d['sha256']}`",
        *_audit_lines(report),
        "",
        "The numbers are on the test part. The bound is the one-sided 95% upper bound of the "
        "admitted error rate.",
        "",
        "| Field | Route | Admitted | Errors | Error rate | Bound | Status | Review share | "
        "Miss rate |",
        "|---|---|---:|---:|---:|---:|---|---:|---:|",
    ]
    for name, f in report["fields"].items():
        for r, sm in f["routes"].items():
            lines.append(
                "| " + " | ".join(_cell(x) for x in (
                    name, r, sm["admitted"], sm["errors"], sm["error_rate"], sm["bound"],
                    sm["status"], f["review_share"], f["miss_rate"],
                )) + " |"
            )  # fmt: skip
    return "\n".join(lines) + "\n"


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def _real_day(day: str) -> bool:
    try:
        return bool(_DATE.match(day)) and datetime.date.fromisoformat(day).isoformat() == day
    except ValueError:
        return False


def run(
    profile_path: Path,
    gold_path: Path,
    split_path: Path,
    out: Path,
    target: str,
    date: str,
    audit_path: Path | None = None,
    since: str | None = None,
) -> dict[str, Any]:
    """Measure, write DIR/report.json, DIR/REPORT.md and DIR/profile.json, and give the report."""
    try:
        t = Decimal(target)
    except InvalidOperation:
        raise MeasureError("--target must be a decimal number") from None
    if not (t.is_finite() and 0 < t <= 1):
        raise MeasureError("--target must be in (0, 1]")
    if not _real_day(date):
        raise MeasureError("--date must be a real day as YYYY-MM-DD")
    if since is not None and (audit_path is None or not _real_day(since)):
        raise MeasureError("--audit-since must be a real day as YYYY-MM-DD, with --audit")
    names = ("report.json", "REPORT.md", "profile.json")
    if out.exists() and (out.is_symlink() or not out.is_dir()):
        raise MeasureError(f"{out} is not a directory")
    if any((out / n).exists() or (out / n).is_symlink() for n in names):
        raise MeasureError(f"{out} has a report or a profile already; use a new directory")
    try:
        profile = load_profile(profile_path)
    except PacketError as e:
        raise MeasureError(str(e)) from None
    gold = read_gold(gold_path)
    parts, split_sha = read_split(split_path, gold)
    audit = None
    if audit_path is not None:
        from .audit import read_audit

        audit = read_audit(audit_path, check_profile(profile).sha256, since)
    report, draft = measure(profile, gold, parts, split_sha, t, date, audit)
    out.mkdir(parents=True, exist_ok=True)
    for n, body in zip(names, (_dump(report), markdown(report), _dump(draft)), strict=True):
        with open(out / n, "x", encoding="utf-8") as f:  # "x": never write over a file
            f.write(body)
    return report


def add_parser(sub: Any) -> None:
    p = sub.add_parser("measure", help="measure a profile on your gold set")
    p.add_argument("--profile", type=Path, required=True, help="a profile file (SPEC §4.10)")
    p.add_argument("--gold", type=Path, required=True, help="the gold set directory")
    p.add_argument("--split", type=Path, required=True, help="the split file")
    p.add_argument("--out", type=Path, required=True, help="a new directory for the output")
    p.add_argument("--target", default="0.05", help="the bound that a measured route is below")
    p.add_argument("--date", default=None, help="the day of the measure, YYYY-MM-DD")
    p.add_argument("--audit", type=Path, help="an audit set: count its blind audit labels")
    p.add_argument("--audit-since", help="count the audit labels from this day on, YYYY-MM-DD")


def main(args: argparse.Namespace) -> None:
    date = args.date or datetime.date.today().isoformat()
    try:
        report = run(
            args.profile, args.gold, args.split, args.out, args.target, date,
            args.audit, args.audit_since,
        )  # fmt: skip
    except (MeasureError, OSError) as e:
        raise SystemExit(f"calibrate measure: {e}") from None
    n = sum(
        sm["status"] == "measured" for f in report["fields"].values() for sm in f["routes"].values()
    )
    print(f"wrote {args.out}/report.json, REPORT.md and profile.json: {n} measured routes")
    for x in report.get("audit", {}).get("alerts", []):
        print(f"alert: the bound of {x['field']!r} on the route {x['route']} is {x['bound']}")
