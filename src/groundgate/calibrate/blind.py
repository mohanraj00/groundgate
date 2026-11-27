"""groundgate calibrate audit tasks and labels: the blind tasks of the audit pick in a store of
the review step, and the audit labels of their answers (SPEC §4.18, docs/design/review.md §5.5).

    groundgate calibrate audit tasks --audit A --store S --packet P --name DOC --profile F
    groundgate calibrate audit labels --audit A --store S

The measure reads no store: these steps write the files of the audit set, and
``calibrate measure --audit`` reads only them. ``A/blind.jsonl`` names the packet and the
profile digest of the label tasks of each document.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from groundgate.canonical import jcs
from groundgate.model import PacketError
from groundgate.profile import check_profile, load_profile

from .audit import (
    AuditError,
    _digest,
    _lines,
    _log,
    _name,
    _text,
    answer_labels,
    document_entry,
    pick,
    read_labels,
    read_seed,
)
from .measure import _read_bytes


def _bindings(root: Path) -> list[dict[str, str]]:
    """The lines of ``blind.jsonl``: the packet of the label tasks of each document, and the
    profile digest of its log entry."""
    path = root / "blind.jsonl"
    if not (path.exists() or path.is_symlink()):
        return []
    out, names = [], set()
    for obj in _lines(_text(path), "blind.jsonl"):
        if (
            not isinstance(obj, dict)
            or set(obj) != {"document", "packet", "profile"}
            or not _name(obj["document"])
            or not isinstance(obj["packet"], str)
            or not _digest(obj["profile"])
            or obj["document"] in names
        ):
            raise AuditError("blind.jsonl: each line has one other document and its packet")
        names.add(obj["document"])
        out.append(obj)
    return out


def _put_file(path: Path, data: bytes) -> None:
    """Write a file of the audit set that is not there, or check that it has these bytes."""
    if path.exists() or path.is_symlink():
        if _read_bytes(path) != data:
            raise AuditError(f"{path} has other bytes than the packet gives")
        return
    path.parent.mkdir(exist_ok=True)
    if path.parent.is_symlink():
        raise AuditError(f"{path.parent} is a link; an audit set holds its own files")
    with open(path, "xb") as f:
        f.write(data)


def write_tasks(
    root: Path, store_dir: Path, packet_key: str, name: str, profile_path: Path
) -> list[str]:
    """Write the label tasks of the packet ``packet_key`` to the store (SPEC §4.18). The
    document ``name`` must be in the pick with the digest of the profile. A packet does not
    name its profile, so the profile must decide the text and the candidates of the packet to
    the decisions of the packet receipt, and give the log entry of ``name``. Write the text, the
    candidates and the judgments of the packet to the audit set, so a measure decides the
    document again. Return the task keys."""
    from groundgate.admit import admit
    from groundgate.review.blind import write_blind_tasks
    from groundgate.review.tasks import checked_packet
    from groundgate.store import FolderStore, StoreError

    seed = read_seed(root)
    entries = _log(root)
    picks = {p["document"]: p for p in pick(seed, entries)}
    if name not in picks:
        raise AuditError(f"{name} is not in the blind audit pick")
    try:
        profile = load_profile(profile_path)
        digest = check_profile(profile).sha256
    except PacketError as e:
        raise AuditError(str(e)) from None
    if picks[name]["profile"] != digest:
        raise AuditError(f"the log entry of {name} names another profile")
    bindings = _bindings(root)
    for b in bindings:
        if b["document"] == name and b["packet"] != packet_key:
            raise AuditError(f"{name} has the label tasks of another packet")
        if b["packet"] == packet_key and b["document"] != name:
            raise AuditError(f"the packet has the label tasks of the document {b['document']}")
    try:
        with FolderStore(store_dir) as store:
            packet, schema, _, problems = checked_packet(store, packet_key)
            if problems or schema is None:
                raise AuditError(f"the packet {packet_key} does not match its receipt")
            if schema != check_profile(profile).schema:
                raise AuditError("the schema of the packet is not the schema of the profile")
            again = admit(packet.text, None, packet.candidates, None, name, packet.judgments,
                          profile=profile).to_dict()  # fmt: skip
            entry = next(e for e in entries if e.get("document") == name)
            if (
                document_entry(name, again) != entry
                or again["decisions"] != packet.receipt["decisions"]
            ):
                raise AuditError(f"the profile does not decide the packet to the entry of {name}")
            if packet.references:
                raise AuditError("an audit set holds no references, so a measure cannot decide it")
            if not unicodedata.is_normalized("NFC", packet.text):
                raise AuditError("the text of the packet is not NFC")
            files = [
                (root / "docs" / f"{name}.txt", packet.text.encode("utf-8")),
                (root / "candidates" / f"{name}.json", (jcs(packet.candidates) + "\n").encode()),
            ]
            if packet.judgments is not None:
                files.append(
                    (root / "judgments" / f"{name}.json", (jcs(packet.judgments) + "\n").encode())
                )
            for path, data in files:  # each check before a write
                if (path.exists() or path.is_symlink()) and _read_bytes(path) != data:
                    raise AuditError(f"{path} has other bytes than the packet gives")
            written = write_blind_tasks(store, packet_key)
    except (StoreError, PacketError, ValueError) as exc:
        raise AuditError(str(exc)) from None
    for path, data in files:
        _put_file(path, data)
    if not any(b["document"] == name for b in bindings):
        path = root / "blind.jsonl"
        if path.is_symlink():
            raise AuditError(f"{path} is a link; an audit set holds its own files")
        with open(path, "a", encoding="utf-8", newline="") as f:
            f.write(jcs({"document": name, "packet": packet_key, "profile": digest}) + "\n")
    return [k for k, _ in written]


@dataclass(frozen=True)
class Labels:
    """The result of ``store_labels`` and ``write_labels``: the labels (new labels for
    ``write_labels``), a line for each task with answers that gives no label, the slots
    ``(document, field, key)`` of the label tasks, and the count of lines that
    ``write_labels`` took out."""

    added: list[dict[str, Any]]
    none: list[str]
    slots: frozenset[tuple[str, str, str | None]] = frozenset()
    removed: int = 0


def store_labels(root: Path, store_dir: Path) -> Labels:
    """The audit labels that the answers to the label tasks give (SPEC §4.18):

    - ``correct``: the canonical value of the decision of the correction. The gate decides the
      correction with no other candidate, as the review API does for a blind task. A
      correction that does not count gives no label.
    - ``not_in_document``: null.
    - ``unsure``: no label.

    ``answer_labels`` gives the labels of the answers to one task. The labeler is the reviewer,
    and the profile is the profile digest of the log entry. An answer that breaks its task
    stops with the reviewer and the sequence of the record."""
    from groundgate.review.blind import blind_tasks
    from groundgate.review.resolve import AnswerError, _admit_only, _check, _read
    from groundgate.review.tasks import checked_packet
    from groundgate.store import FolderStore, StoreError, reviewer_key

    out: list[dict[str, Any]] = []
    none: list[str] = []
    slots: set[tuple[str, str, str | None]] = set()
    try:
        with FolderStore(store_dir) as store:
            names, _ = store.log_names()
            for b in _bindings(root):
                doc, pk = b["document"], b["packet"]
                packet, schema, _, problems = checked_packet(store, pk)
                if problems or schema is None:
                    raise AuditError(f"the packet {pk} does not match its receipt")
                own = blind_tasks(pk, schema)
                decisions = packet.receipt["decisions"]
                hide = range(len(decisions))  # the person's candidate only
                ids = [c.get("id") for c in packet.candidates if isinstance(c, Mapping)]
                run, cache = _admit_only(packet), {}  # type: ignore[var-annotated]
                given: dict[str, list[dict[str, Any]]] = {}
                for log in sorted(n for n in names if n[0] == "answers" and n[1] == pk):
                    for r in store.read(log):
                        if not isinstance(r.get("task"), str) or r["task"] not in own:
                            continue  # a review answer: review resolve checks it
                        reviewer = r.get("reviewer")
                        if not isinstance(reviewer, str) or reviewer_key(reviewer) != log[2]:
                            raise AuditError(f"a record of {pk} names another reviewer")
                        c = _check(reviewer, r, own, schema, ids)
                        value = None
                        if c.verdict == "correct":
                            a = _read(c, schema, packet, decisions, run, cache, hide)
                            if a.target is not None and a.correction is not None:
                                value = a.correction.decision["value"]
                        given.setdefault(c.task_key, []).append(
                            {"reviewer": reviewer, "verdict": c.verdict, "value": value,
                             "time": r["time"]}
                        )  # fmt: skip
                for tk, (slot, _task) in own.items():
                    slots.add((doc, slot.field, slot.key))
                    if tk not in given:
                        continue
                    task = {"document": doc, "profile": b["profile"], "field": slot.field,
                            "key": slot.key}  # fmt: skip
                    labels, why = answer_labels(task, given[tk])
                    if why is not None:
                        where = f"{doc} {slot.field}" + ("" if slot.key is None else f" {slot.key}")
                        none.append(f"{where}: {why}")
                    out += labels
    except AnswerError as exc:
        raise AuditError(str(exc)) from None
    except (StoreError, PacketError, ValueError, KeyError, TypeError) as exc:
        raise AuditError(str(exc)) from None
    return Labels(out, none, frozenset(slots))


def write_labels(root: Path, store_dir: Path) -> Labels:
    """Make the labels of the label tasks in ``labels.jsonl`` equal to ``store_labels``. The
    answers in the store own the slots of the label tasks: a line for such a slot that the
    current answers do not give goes out, for example after a later ``unsure``. The other
    lines stay, with their bytes and in their order, and the labels of the store come after
    them. The new file replaces the old file in one step."""
    read_seed(root)
    path = root / "labels.jsonl"
    if path.is_symlink():
        raise AuditError(f"{path} is a link; an audit set holds its own files")
    text = _text(path) if path.exists() else ""
    have = {jcs(label) for label in read_labels(text)}  # each line is a label
    found = store_labels(root, store_dir)
    now = {jcs(label) for label in found.added}
    kept: list[str] = []
    removed = 0
    for line in text.splitlines():
        if line.strip():
            obj = json.loads(line)
            if (obj["document"], obj["field"], obj["key"]) in found.slots:
                removed += jcs(obj) not in now
                continue
        kept.append(line)
    lines = [*kept, *(jcs(label) for label in found.added)]
    data = "".join(line + "\n" for line in lines)
    if data != text:
        # a new file with a random name (O_EXCL), so the write follows no link
        fd, tmp = tempfile.mkstemp(prefix=".labels.", suffix=".tmp", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    added = [label for label in found.added if jcs(label) not in have]
    return Labels(added, found.none, found.slots, removed)
