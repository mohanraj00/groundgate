"""groundgate calibrate audit: the blind audit sample of a profile (SPEC §4.18, #643).

    groundgate calibrate audit add  --audit A --name DOC --receipt R
    groundgate calibrate audit pick --audit A [--profile P] [--out FILE]
    groundgate calibrate audit rate --audit A --report DIR/report.json

The audit set (format 1) is a directory:

    A/audit.json              {"groundgate_audit": 1, "seed": "..."}
    A/log.jsonl               the audit log: one canonical JSON entry on each line
    A/labels.jsonl            the audit labels: one canonical JSON label on each line
    A/docs/<doc>.txt          the text of each labelled document, in Unicode NFC
    A/candidates/<doc>.json   the recorded candidates of the extractor
    A/judgments/<doc>.json    optional: the recorded judgments

The pick is a function of the seed and the log only. It reads no clock and no label, so a replay
gives the same documents. A task names a document and a field, and never a proposed value.
``calibrate measure --audit A`` counts the audit labels with the gold set labels. A review
answer or the decision of an approver is not a label: ``check_label`` refuses each record with
a member that the label format does not list.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from groundgate.canonical import jcs
from groundgate.model import PacketError
from groundgate.pack import _no_twice
from groundgate.profile import check_profile, load_profile
from groundgate.review.tasks import audit_picked

from .measure import (
    _NAME,
    MAX_DOCUMENTS,
    Gold,
    GoldDoc,
    MeasureError,
    _read_bytes,
    _read_json,
    _sha,
)

AUDIT_FORMAT = 1
TASK_FORMAT = 1
LABEL_FORMAT = 1
PICK_PREFIX = "groundgate-blind-audit/1:"
SET_PREFIX = "groundgate-audit-set/1:"
START = "0.1"  # the rate of a new profile version
LOW = "0.02"  # the rate while the bound of each route is below the target
MINIMUM = 30  # the picked items of a profile version before the rate applies
MAX_ITEMS = 2**53 - 1
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_DOCUMENT = frozenset({"entry", "document", "profile", "items"})
_RATE = frozenset({"entry", "profile", "rate"})
_LABEL = frozenset(
    {"groundgate_audit_label", "document", "profile", "field", "key", "value", "labeler", "date"}
)


class AuditError(MeasureError):
    """The audit log, a label or the audit set is not valid."""


def _int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _digest(v: object) -> bool:
    return isinstance(v, str) and bool(_DIGEST.match(v))


def _name(v: object) -> bool:
    return isinstance(v, str) and bool(_NAME.match(v))


def _day(v: object) -> bool:
    if not isinstance(v, str) or not _DAY.match(v):
        return False
    try:
        return datetime.date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def _lines(text: str, what: str) -> list[Any]:
    """The object of each line of ``text``. Each line must be canonical JSON, and the last line
    ends with a line break."""
    if text and not text.endswith("\n"):
        raise AuditError(f"{what}: the last line has no line break")
    out = []
    for n, line in enumerate(text.split("\n")[:-1], 1):
        try:
            obj = json.loads(line, object_pairs_hook=_no_twice)
            canonical = jcs(obj) == line
        except (ValueError, RecursionError, PacketError, TypeError):
            canonical = False
        if not canonical:
            raise AuditError(f"{what}: line {n} is not canonical JSON")
        out.append(obj)
    return out


# ------------------------------------------------------------------------------ the log


def check_entry(obj: object) -> dict[str, Any]:
    """An entry of the audit log (SPEC §4.18), or ``AuditError``."""
    if not isinstance(obj, dict):
        raise AuditError("an entry of the audit log must be an object")
    kind = obj.get("entry")
    if kind == "document":
        ok = (
            set(obj) == _DOCUMENT
            and _name(obj["document"])
            and _digest(obj["profile"])
            and _int(obj["items"])
            and 0 <= obj["items"] <= MAX_ITEMS
        )
    elif kind == "rate":
        ok = set(obj) == _RATE and _digest(obj["profile"]) and obj["rate"] in (START, LOW)
    else:
        raise AuditError("the entry of an audit log line must be document or rate")
    if not ok:
        raise AuditError(f"a {kind} entry of the audit log has a wrong or a missing member")
    return dict(obj)


def check_log(entries: Iterable[object]) -> list[dict[str, Any]]:
    """Each entry of an audit log, checked. A document name has one entry only."""
    out, names = [], set()
    for obj in entries:
        e = check_entry(obj)
        if e["entry"] == "document":
            if e["document"] in names:
                raise AuditError(f"the audit log has two entries for {e['document']}")
            names.add(e["document"])
        out.append(e)
    return out


def read_log(text: str) -> list[dict[str, Any]]:
    """The entries of the text of an audit log file."""
    return check_log(_lines(text, "the audit log"))


def items(receipt: Mapping[str, Any]) -> int:
    """The count of the admitted values of a receipt: the ``items`` of its document entry."""
    values = {
        (d["field"], d.get("key"), d["value"])
        for d in receipt["decisions"]
        if d["outcome"] == "admitted"
    }
    return len(values)


def document_entry(name: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    """The document entry of a receipt that a profile decided."""
    profile = receipt.get("profile")
    if not isinstance(profile, dict) or not _digest(profile.get("sha256")):
        raise AuditError("the receipt names no profile, so it has no audit entry")
    return check_entry(
        {"entry": "document", "document": name, "profile": profile["sha256"],
         "items": items(receipt)}
    )  # fmt: skip


# ----------------------------------------------------------------------------- the pick


def pick_hash(seed: str, profile: str, document: str) -> int:
    """H: the first 8 bytes, big-endian, of SHA-256 over ``groundgate-blind-audit/1:`` and the
    canonical JSON of ``[seed, profile, document]``."""
    data = (PICK_PREFIX + jcs([seed, profile, document])).encode("utf-8")
    return int.from_bytes(hashlib.sha256(data).digest()[:8], "big")


def pick(seed: str, entries: Iterable[object]) -> list[dict[str, str]]:
    """The picked documents of an audit log, in log order (SPEC §4.18). The same seed and the
    same log give the same pick."""
    if not isinstance(seed, str):
        raise AuditError("the seed must be a string")
    rates: dict[str, str] = {}
    picked_items: dict[str, int] = {}
    out = []
    for e in check_log(entries):
        profile = e["profile"]
        if e["entry"] == "rate":
            rates[profile] = e["rate"]
            continue
        rate = rates.get(profile, START)
        if picked_items.get(profile, 0) < MINIMUM:
            reason = "minimum"
        elif audit_picked(pick_hash(seed, profile, e["document"]), rate):
            reason = "rate"
        else:
            continue
        picked_items[profile] = picked_items.get(profile, 0) + e["items"]
        out.append({"document": e["document"], "profile": profile, "rate": rate, "reason": reason})
    return out


# -------------------------------------------------------------------- tasks and labels


def tasks(profile: Mapping[str, Any], document: str) -> list[dict[str, Any]]:
    """The audit tasks of one picked document: one for each field of the profile and each key.
    A task gives no proposed value, so it is the same with and without an admitted value."""
    checked = check_profile(profile)
    out = []
    for field in sorted(checked.schema.fields):
        f = checked.schema.fields[field]
        if f.record is not None:
            continue
        for key in [None] if f.keys is None else sorted(f.keys):
            out.append(
                {"groundgate_audit_task": TASK_FORMAT, "document": document,
                 "profile": checked.sha256, "field": field, "key": key}
            )  # fmt: skip
    return out


def check_label(obj: object) -> dict[str, Any]:
    """An audit label (SPEC §4.18), or ``AuditError``. The format is closed, so an answer of the
    review step or a decision of an approver is not a label."""
    if not isinstance(obj, dict) or set(obj) != _LABEL:
        raise AuditError("an audit label must be an object with the members of format 1 only")
    labeler = obj["labeler"]
    ok = (
        _int(obj["groundgate_audit_label"])
        and obj["groundgate_audit_label"] == LABEL_FORMAT
        and _name(obj["document"])
        and _digest(obj["profile"])
        and isinstance(obj["field"], str)
        and bool(obj["field"])
        and (obj["key"] is None or isinstance(obj["key"], str))
        and (obj["value"] is None or isinstance(obj["value"], str))
        and isinstance(labeler, str)
        and bool(labeler.strip())
        and unicodedata.is_normalized("NFC", labeler)
        and _day(obj["date"])
    )
    if not ok:
        raise AuditError("an audit label has a member with a wrong form")
    return dict(obj)


def read_labels(text: str) -> list[dict[str, Any]]:
    """The labels of the text of a label file, in file order."""
    return [check_label(obj) for obj in _lines(text, "the audit labels")]


# ------------------------------------------------------------------------ the rate rule


def rate(routes: Iterable[Mapping[str, Any]], covered: int) -> str:
    """The audit rate after a measure (SPEC §4.18). ``routes`` holds the summary of each route
    of the report, and ``covered`` is the count of the admitted values that the audit labels
    cover. A route has an admitted value when one has a label (``admitted``) or when one has
    no label (``unscored``)."""
    with_value = [r for r in routes if r["admitted"] + r["unscored"] > 0]
    measured = all(r["status"] == "measured" for r in with_value)
    return LOW if covered >= MINIMUM and with_value and measured else START


# ------------------------------------------------------------------------ the audit set


@dataclass(frozen=True)
class AuditSet:
    """The audit set of one measure: the labelled, picked documents of one profile digest in
    the form of a gold set, and the counts that the report gives."""

    gold: Gold
    sha256: str
    seed: str
    since: str | None
    picked: int  # the picked documents of the profile digest
    skipped: int  # the labels of another profile digest, or of a day before ``since``


def _text(path: Path) -> str:
    try:
        return _read_bytes(path).decode("utf-8")
    except UnicodeDecodeError:
        raise AuditError(f"{path} is not UTF-8") from None


def read_seed(root: Path) -> str:
    """The seed of the audit set ``root``."""
    if root.is_symlink() or not root.is_dir():
        raise AuditError(f"{root} is not a directory")
    head = _read_json(root / "audit.json")
    if (
        not isinstance(head, dict)
        or set(head) != {"groundgate_audit", "seed"}
        or not _int(head["groundgate_audit"])
        or head["groundgate_audit"] != AUDIT_FORMAT
        or not isinstance(head["seed"], str)
    ):
        raise AuditError(
            f"audit.json must be an object with groundgate_audit {AUDIT_FORMAT} and a seed string"
        )
    return str(head["seed"])


def read_audit(root: Path, profile_sha256: str, since: str | None = None) -> AuditSet:
    """Read and check the audit set ``root`` for a measure of the profile ``profile_sha256``.
    Replay the pick, and keep each label of that profile from ``since`` on."""
    seed = read_seed(root)
    for sub in ("docs", "candidates", "judgments"):
        if (root / sub).is_symlink():
            raise AuditError(f"{root / sub} is a link; an audit set holds its own files")
    log_text = _text(root / "log.jsonl")
    labels_path = root / "labels.jsonl"
    labels_text = _text(labels_path) if labels_path.exists() or labels_path.is_symlink() else ""
    picks = {p["document"]: p for p in pick(seed, read_log(log_text))}
    rows: dict[str, dict[str, Any]] = {}
    skipped = 0
    for label in read_labels(labels_text):
        name = label["document"]
        if name not in picks:
            raise AuditError(f"a label names {name}, which is not in the blind audit pick")
        if picks[name]["profile"] != label["profile"]:
            raise AuditError(f"a label of {name} names another profile than its log entry")
        if label["profile"] != profile_sha256 or (since is not None and label["date"] < since):
            skipped += 1
            continue
        row = rows.setdefault(name, {})
        field, key = label["field"], label["key"]
        if key is None:
            if isinstance(row.get(field), dict):
                raise AuditError(f"{name}: {field!r} has labels with a key and with no key")
            row[field] = label["value"]
        else:
            if field in row and not isinstance(row[field], dict):
                raise AuditError(f"{name}: {field!r} has labels with a key and with no key")
            row.setdefault(field, {})[key] = label["value"]
    if len(rows) > MAX_DOCUMENTS:
        raise AuditError(f"a measure counts at most {MAX_DOCUMENTS} audit documents")
    files: dict[str, dict[str, str | None]] = {}
    docs: dict[str, GoldDoc] = {}
    for name in sorted(rows):
        raw = _read_bytes(root / "docs" / f"{name}.txt")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise AuditError(f"docs/{name}.txt is not UTF-8") from None
        if not unicodedata.is_normalized("NFC", text):
            raise AuditError(f"docs/{name}.txt is not NFC")
        craw = _read_bytes(root / "candidates" / f"{name}.json")
        cands = _read_json(root / "candidates" / f"{name}.json")
        if not isinstance(cands, list):
            raise AuditError(f"candidates/{name}.json must be a list")
        jpath = root / "judgments" / f"{name}.json"
        jraw: bytes | None = None
        judg: list[Any] | None = None
        if jpath.exists() or jpath.is_symlink():
            jraw = _read_bytes(jpath)
            judg = _read_json(jpath)
            if not isinstance(judg, list):
                raise AuditError(f"judgments/{name}.json must be a list")
        files[name] = {
            "text": _sha(raw),
            "candidates": _sha(craw),
            "judgments": None if jraw is None else _sha(jraw),
        }
        docs[name] = GoldDoc(name, text, cands, judg, rows[name])
    body = {
        "groundgate_audit": AUDIT_FORMAT,
        "seed": seed,
        "log": _sha(log_text.encode("utf-8")),
        "labels": _sha(labels_text.encode("utf-8")),
        "files": files,
    }
    digest = _sha((SET_PREFIX + jcs(body)).encode("utf-8"))
    mine = sum(p["profile"] == profile_sha256 for p in picks.values())
    return AuditSet(Gold(docs, digest), digest, seed, since, mine, skipped)


# ------------------------------------------------------------------------------ the CLI


def _append(root: Path, entry: Mapping[str, Any], existing: Sequence[Mapping[str, Any]]) -> None:
    """Add one entry to the log of the audit set, after a check of the log with the entry."""
    check_log([*existing, entry])
    path = root / "log.jsonl"
    if path.is_symlink():
        raise AuditError(f"{path} is a link; an audit set holds its own files")
    with open(path, "a", encoding="utf-8", newline="") as f:
        f.write(jcs(dict(entry)) + "\n")


def _log(root: Path) -> list[dict[str, Any]]:
    path = root / "log.jsonl"
    return read_log(_text(path)) if path.exists() or path.is_symlink() else []


def add(root: Path, name: str, receipt_path: Path) -> dict[str, Any]:
    """Add the document entry of a receipt to the log of the audit set."""
    read_seed(root)
    receipt = _read_json(receipt_path)
    if not isinstance(receipt, dict) or not isinstance(receipt.get("decisions"), list):
        raise AuditError(f"{receipt_path} is not a receipt")
    try:
        entry = document_entry(name, receipt)
    except (KeyError, TypeError, AttributeError):
        raise AuditError(f"{receipt_path} is not a receipt") from None
    _append(root, entry, _log(root))
    return entry


def picked(root: Path, profile_path: Path | None) -> dict[str, Any]:
    """The pick of the audit set and, with a profile, the tasks of its picked documents."""
    seed = read_seed(root)
    picks = pick(seed, _log(root))
    out: dict[str, Any] = {"groundgate_audit_pick": AUDIT_FORMAT, "seed": seed, "picks": picks}
    if profile_path is not None:
        try:
            profile = load_profile(profile_path)
            digest = check_profile(profile).sha256
        except PacketError as e:
            raise AuditError(str(e)) from None
        out["tasks"] = [
            t for p in picks if p["profile"] == digest for t in tasks(profile, p["document"])
        ]
    return out


def write_rate(root: Path, report_path: Path) -> dict[str, Any]:
    """Add the rate entry of a measure report to the log of the audit set."""
    read_seed(root)
    report = _read_json(report_path)
    try:
        entry = check_entry(
            {"entry": "rate", "profile": report["profile"]["sha256"],
             "rate": report["audit"]["rate"]}
        )  # fmt: skip
    except (KeyError, TypeError):
        raise AuditError(f"{report_path} is not a report of a measure with --audit") from None
    _append(root, entry, _log(root))
    return entry


def add_parser(sub: Any) -> None:
    p = sub.add_parser("audit", help="the blind audit sample of a profile (SPEC 4.18)")
    steps = p.add_subparsers(dest="audit_step", required=True)
    a = steps.add_parser("add", help="add the document entry of a receipt to the audit log")
    a.add_argument("--name", required=True, help="the document name")
    a.add_argument("--receipt", type=Path, required=True, help="the receipt JSON of the document")
    k = steps.add_parser("pick", help="replay the pick; with --profile, write the blind tasks")
    k.add_argument("--profile", type=Path, help="a profile file: add the tasks of its documents")
    k.add_argument("--out", type=Path, help="write the pick here instead of stdout")
    r = steps.add_parser("rate", help="add the audit rate of a measure report to the audit log")
    r.add_argument("--report", type=Path, required=True, help="report.json of measure --audit")
    for s in (a, k, r):
        s.add_argument("--audit", type=Path, required=True, help="the audit set directory")


def main(args: argparse.Namespace) -> None:
    try:
        if args.audit_step == "add":
            entry = add(args.audit, args.name, args.receipt)
            print(f"added {entry['document']} with {entry['items']} items")
        elif args.audit_step == "rate":
            entry = write_rate(args.audit, args.report)
            print(f"the audit rate of {entry['profile']} is {entry['rate']}")
        else:
            text = json.dumps(picked(args.audit, args.profile), indent=1, ensure_ascii=False) + "\n"
            if args.out is None:
                print(text, end="")
            else:
                with open(args.out, "x", encoding="utf-8") as f:  # "x": never write over a file
                    f.write(text)
    except (MeasureError, OSError) as e:
        raise SystemExit(f"calibrate audit: {e}") from None
