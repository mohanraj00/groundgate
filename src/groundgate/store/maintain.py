"""Check, rebuild and forget in a folder store (docs/design/store.md §7.4, §8, §12 issue 3).

``check`` reads each object and each log of a ``FolderStore``. It finds the kind of each object
from its key, checks each object that a packet, a reading or a run names, checks each chain and
the view of each splits log (§10), compares the inputs of a packet with the inputs that its run
header names, and looks for document text in each run record. ``rebuild`` builds the views
again from the objects and logs. ``forget_packet`` removes the objects of a packet that §8 rule
3 lists as "Removed", or with ``everything`` each object and log of the packet.

The store data is untrusted. These functions build no path from it: each path comes from a key
that matches ``sha256:[0-9a-f]{64}`` or from a fixed word.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

from ..canonical import digest, jcs
from . import KEY, FolderStore, NotFound, StoreError, Torn, _canonical, check_bytes, key
from .packets import _PACKET, _READING, printable

__all__ = ["Report", "check", "forget_packet", "rebuild"]

# The kinds of §4 with a fixed version. A run record is ``run@N``: its header names N.
KINDS = (
    "packet@1",
    "reading@1",
    "receipt@1",
    "schema@1",
    "policy@1",
    "reference@1",
    "pack@1",
    "candidates@1",
    "judgments@1",
    "admission@1",
    "layout@1",
    "text@1",
    "prompt@1",
    "reply@1",
    "review-policy@1",
    "task@1",
    "resolution@1",
    "document@1",
    "source@1",
)
# §8 rule 3: the kinds that ``forget`` removes. The run record goes too if a line holds text.
REMOVED = frozenset(
    {
        "source@1",
        "text@1",
        "layout@1",
        "document@1",
        "reference@1",
        "candidates@1",
        "prompt@1",
        "reply@1",
        "admission@1",
    }
)
# The objects of a run record: the member of a line, and the kind in the record and the store.
_RUN_OBJECTS = {
    "prompt_sha256": ("prompt", "prompt@1"),
    "reply_sha256": ("reply", "reply@1"),
    "admission_sha256": ("admission", "admission@1"),
}
_RUN_KINDS = frozenset(kind for _, kind in _RUN_OBJECTS.values())
# A string of a run record line with this many characters or more, that is also in the
# document text, is document text.
MIN_TEXT = 8
VIEWS = ("readings.json", "calibrate-labels.json")
_BYTES = frozenset({"source@1", "text@1", "prompt@1", "reply@1"})


@dataclass
class Report:
    """What ``check`` found. ``findings`` are problems. ``deleted`` names each input that
    ``forget`` removed, which is not a problem. ``unchecked`` names each run record whose text
    is not in the store: ``check`` cannot look for text in its lines, and ``forget`` of its
    packet removes it. ``cut`` holds each torn line that ``repair``
    cut, with the log path."""

    objects: int = 0
    logs: int = 0
    findings: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)
    cut: list[tuple[str, bytes]] = field(default_factory=list)

    def find(self, text: str) -> None:
        if text not in self.findings:
            self.findings.append(text)


def _rel(k: str) -> str:
    return f"objects/{k[7:9]}/{k[9:]}"


def _log_rel(log: tuple[str, ...]) -> str:
    if len(log) == 1:
        return "logs/deleted.jsonl"
    return "/".join(["logs", log[0], *(k[7:] for k in log[1:-1]), log[-1][7:] + ".jsonl"])


def run_hash(runner: str, kind: str, data: str | bytes) -> str:
    """A key of the run record: SHA-256 over ``<runner>:<kind>``, a zero byte and the data, as
    the runner calculates it (runner.md). A string counts as its UTF-8 bytes."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    digest = hashlib.sha256(f"{runner}:{kind}\0".encode() + raw)
    return "sha256:" + digest.hexdigest()


def _run_kind(data: bytes) -> tuple[str, str] | None:
    """The store kind and the runner version of a run record, from its header line."""
    line = data.split(b"\n", 1)[0]
    if not line.startswith(b"{"):
        return None
    try:
        header = json.loads(line)
    except (ValueError, RecursionError):
        return None
    runner = header.get("runner") if isinstance(header, dict) else None
    if not isinstance(runner, str) or not runner.startswith("groundgate-run/"):
        return None
    number = runner.removeprefix("groundgate-run/")
    if not (number.isascii() and number.isdigit() and number[0] != "0" and len(number) <= 9):
        return None
    return f"run@{number}", runner


def kind_of(k: str, data: bytes) -> str | None:
    """The kind that gives ``data`` the key ``k``, or ``None``."""
    run = _run_kind(data)
    if run is not None and key(run[0], data) == k:
        return run[0]
    json_like = data[:1] in (b"{", b"[")  # canonical JSON of an object or a list
    for kind in KINDS:
        if (json_like or kind in _BYTES) and key(kind, data) == k:
            return kind
    return None


class _Objects:
    """The kind of each object in the store, found one time."""

    def __init__(self, store: FolderStore, report: Report | None = None) -> None:
        self.store = store
        self.kinds: dict[str, str | None] = {}
        keys, problems = store.object_keys()
        for problem in problems:
            if report is not None:
                report.find(problem)
        for k in keys:
            try:
                data = store.object_bytes(k)
            except NotFound:
                continue  # removed after the walk
            except StoreError as exc:
                if report is not None:
                    report.find(str(exc))
                self.kinds[k] = None
                continue
            found = kind_of(k, data)
            self.kinds[k] = found
            if report is None:
                continue
            if found is None:
                report.find(f"{_rel(k)} does not match its key as any kind: it changed")
                continue
            try:
                check_bytes(found, data)
            except ValueError as exc:
                report.find(f"{_rel(k)} is not a valid {found} object: {exc}")
        self._deleted: dict[str, Mapping[str, Any]] | None = None
        self._deleted_runs: dict[str, str] | None = None
        self._run_keys: dict[str, list[str]] | None = None
        self._by_run: dict[str, dict[str, tuple[str, str]]] = {}

    def of(self, kind: str) -> Iterator[str]:
        return (k for k, v in self.kinds.items() if v == kind)

    def deleted(self) -> dict[str, Mapping[str, Any]]:
        if self._deleted is None:
            self._deleted = {}
            try:
                for entry in self.store.read(("deleted",)):
                    if isinstance(entry.get("key"), str):
                        self._deleted[entry["key"]] = entry
            except StoreError:
                pass  # check reports the log itself
        return self._deleted

    def deleted_runs(self) -> dict[str, str]:
        """The store key of each prompt, reply and admission that ``forget`` removed, by its
        run keys in the deleted log (§7.1). Each entry counts, not only the last entry of a key:
        a later deletion of the same object with no run keys does not hide the run keys of an
        earlier one. The log is untrusted: an entry whose ``key`` or ``run_keys`` does not have
        the format is skipped."""
        if self._deleted_runs is None:
            self._deleted_runs = {}
            try:
                entries = self.store.read(("deleted",))
            except StoreError:
                entries = []  # check reports the log itself
            for entry in entries:
                k = entry.get("key")
                runs = entry.get("run_keys")
                if not isinstance(k, str) or not KEY.fullmatch(k) or not isinstance(runs, list):
                    continue
                for run in runs:
                    if isinstance(run, str) and KEY.fullmatch(run):
                        self._deleted_runs[run] = k
        return self._deleted_runs

    def run_keys(self, k: str) -> list[str]:
        """The run keys of the prompt, reply or admission ``k``: one for each runner version
        of a run record in the store, sorted. The first call builds the index for all the
        objects, so a ``forget`` of many objects does the work one time."""
        if self._run_keys is None:
            self._run_keys = _run_keys_index(self)
        return self._run_keys.get(k, [])

    def by_run_key(self, runner: str) -> dict[str, tuple[str, str]]:
        """The store kind and key of each prompt, reply and admission object, by its key in a
        run record of ``runner``. The hash takes the bytes as they are, so an object that is
        not UTF-8 needs no decode. An object that ``get`` refuses after the walk is skipped,
        and its kind in ``kinds`` becomes ``None``, so ``unread`` names it."""
        if runner not in self._by_run:
            index: dict[str, tuple[str, str]] = {}
            for word, kind in _RUN_OBJECTS.values():
                for k in list(self.of(kind)):
                    try:
                        data = self.store.get(kind, k)
                    except StoreError:  # it changed or went after the walk
                        self.kinds[k] = None
                        continue
                    index[run_hash(runner, word, data)] = (kind, k)
            self._by_run[runner] = index
        return self._by_run[runner]

    def unread(self) -> list[tuple[str, str | None]]:
        """The key of each object that the walk could not read or match to a kind, with
        ``None`` as its kind."""
        return [(k, None) for k, v in sorted(self.kinds.items()) if v is None]

    def json(self, kind: str, k: str) -> Any:
        data = self.store.get(kind, k)
        try:
            return _canonical(data.decode("utf-8"), f"the {kind} object {k}")
        except (UnicodeDecodeError, ValueError) as exc:
            raise StoreError(str(exc)) from exc


def _run_keys_index(objects: _Objects) -> dict[str, list[str]]:
    """The sorted run keys of each prompt, reply and admission, by its store key, for each
    runner version of a run record in the store."""
    runners = {f"groundgate-run/{v[4:]}" for v in objects.kinds.values() if v and v[:4] == "run@"}
    index: dict[str, set[str]] = {}
    for runner in sorted(runners):
        for r, (_, n) in objects.by_run_key(runner).items():
            index.setdefault(n, set()).add(r)
    return {n: sorted(rs) for n, rs in index.items()}


# The objects that a packet names


def _packet(objects: _Objects, k: str) -> dict[str, Any]:
    obj = objects.json("packet@1", k)
    if not isinstance(obj, dict) or sorted(obj) != list(_PACKET) or obj["format"] != "packet@1":
        raise StoreError(f"the packet@1 object {k} does not have the members of packet@1")
    document = obj["document"]
    if not isinstance(document, dict) or sorted(document) != ["id", "source", "text"]:
        raise StoreError(f"the packet {k} member document does not have id, source, text")
    return obj


def _reading(objects: _Objects, k: str) -> dict[str, Any]:
    obj = objects.json("reading@1", k)
    if not isinstance(obj, dict) or sorted(obj) != list(_READING) or obj["format"] != "reading@1":
        raise StoreError(f"the reading@1 object {k} does not have the members of reading@1")
    return obj


def _keys(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str) and KEY.fullmatch(value):
        return [value]
    if isinstance(value, list) and all(isinstance(v, str) and KEY.fullmatch(v) for v in value):
        return list(value)
    raise StoreError(f"{printable(value)} is not a store key, a list of keys or null")


def _named(packet: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The kind and the key of each object that a packet names, without its reading and run."""
    named = [("text@1", k) for k in _keys(packet["document"]["text"])]
    for name, kind in (
        ("schema", "schema@1"),
        ("policy", "policy@1"),
        ("references", "reference@1"),
        ("packs", "pack@1"),
        ("candidates", "candidates@1"),
        ("judgments", "judgments@1"),
        ("receipt", "receipt@1"),
    ):
        named.extend((kind, k) for k in _keys(packet[name]))
    return named


def _reading_named(objects: _Objects, k: str) -> list[tuple[str, str]]:
    reading = _reading(objects, k)
    named = [("source@1", k) for k in _keys(reading["source"])]
    named += [("text@1", k) for k in _keys(reading["text"])]
    named += [("layout@1", k) for k in _keys(reading["layout"])]
    return named


@dataclass
class _Run:
    kind: str
    runner: str
    lines: list[dict[str, Any]]


def _run(objects: _Objects, k: str) -> _Run:
    """The run record of key ``k``. Its kind comes from its header."""
    kind = objects.kinds.get(k)
    if kind is None or not kind.startswith("run@"):
        raise StoreError(f"the run record {k} is not a run@N object")
    data = objects.store.get(kind, k)
    found = _run_kind(data)
    if found is None or found[0] != kind:
        raise StoreError(f"the header of the run record {k} cannot be read")
    lines = []
    for line in data.decode("utf-8")[:-1].split("\n"):
        value = _canonical(line, f"a line of the run record {k}")
        if not isinstance(value, dict):
            raise StoreError(f"a line of the run record {k} is not a JSON object")
        lines.append(value)
    return _Run(kind, found[1], lines)


def _run_chain(run: _Run) -> str | None:
    """The first line of a run record that does not continue the chain, as a message."""
    previous = None
    for n, line in enumerate(run.lines, 1):
        body = {m: v for m, v in line.items() if m != "entry_sha256"}
        if (
            type(line.get("sequence")) is not int
            or line.get("sequence") != n
            or line.get("previous") != previous
            or line.get("entry_sha256") != run_hash(run.runner, "entry", jcs(body))
        ):
            return f"line {n} does not continue the chain"
        previous = line["entry_sha256"]
    if not run.lines or run.lines[0].get("kind") != "header":
        return "the first line is not the header"
    return None


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def text_lines(run: _Run, text: str, kept: set[str]) -> list[int]:
    """The number of each line of a run record that holds document text: a string of at least
    ``MIN_TEXT`` characters that is also in ``text``. A store key and a string of ``kept`` are
    not document text: the kept objects hold them already."""
    found = []
    for n, line in enumerate(run.lines, 1):
        for s in _strings(line):
            if len(s) >= MIN_TEXT and s not in kept and not KEY.fullmatch(s) and s in text:
                found.append(n)
                break
    return found


def _holds_text(objects: _Objects, packet: Mapping[str, Any], run: _Run) -> list[int] | None:
    """The lines of a run record that hold the text of its packet, or ``None`` if the text is
    not in the store. The field names of the schema and the document id and source are kept
    in the packet and the schema, so they are not document text."""
    text_key = packet["document"]["text"]
    if objects.kinds.get(text_key) != "text@1":
        return None
    text = objects.store.get("text@1", text_key).decode("utf-8")
    kept = {s for s in (packet["document"]["id"], packet["document"]["source"]) if s}
    if objects.kinds.get(packet["schema"]) == "schema@1":
        schema = objects.json("schema@1", packet["schema"])
        if isinstance(schema, dict) and isinstance(schema.get("fields"), dict):
            kept.update(schema["fields"])
    return text_lines(run, text, kept)


def _run_objects(
    objects: _Objects, run: _Run
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The store kind and key of each prompt, reply and admission that the run record names,
    and the store kind and run key of each one that matches no object. The record names them
    by run keys: ``_Objects.by_run_key`` hashes each object of these kinds one time for each
    runner version."""
    index = objects.by_run_key(run.runner)
    found = []
    missing = []
    for line in run.lines:
        for member, (_, kind) in _RUN_OBJECTS.items():
            value = line.get(member)
            if not isinstance(value, str):
                continue
            if value in index and index[value][0] == kind:
                found.append(index[value])
            else:
                missing.append((kind, value))
    return found, missing


def _compare_inputs(objects: _Objects, packet: Mapping[str, Any], run: _Run) -> list[str]:
    """Compare the inputs of a packet with the inputs that its run header names. An input that
    is not in the store is not compared."""
    problems: list[str] = []
    inputs = run.lines[0].get("inputs")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("document"), dict):
        return ["the run header does not name its inputs"]
    document = inputs["document"]
    for name in ("id", "source"):
        if document.get(name) != packet["document"][name]:
            problems.append(f"the run header names another document {name}")

    def same(
        word: str, kind: str, k: str | None, named: object, default: str | None = None
    ) -> None:
        if k is None:
            data = default
        elif objects.kinds.get(k) != kind:
            return  # absent or changed: reported as a named object
        else:
            data = objects.store.get(kind, k).decode("utf-8")
        if data is None or run_hash(run.runner, word, data) != named:
            problems.append(f"the run header names another {word}")

    same("text", "text@1", packet["document"]["text"], document.get("sha256"))
    same("schema", "schema@1", packet["schema"], inputs.get("schema_sha256"))
    from ..model import Policy

    default = jcs(Policy.from_dict({}).to_dict())
    same("policy", "policy@1", packet["policy"], inputs.get("policy_sha256"), default)
    named = inputs.get("reference_sha256")
    references = _keys(packet["references"])
    if not isinstance(named, list) or len(named) != len(references):
        problems.append("the run header names other references")
    else:
        for k, h in zip(references, named, strict=True):
            same("reference", "reference@1", k, h)
    return problems


# check


def check(store: FolderStore, *, repair: bool = False) -> Report:
    """Check each object and each log of ``store`` (§12 issue 3). With ``repair``, cut a torn
    last line of a log, and keep the cut bytes in ``Report.cut``."""
    report = Report()
    objects = _Objects(store, report)
    report.objects = len(objects.kinds)
    deleted = objects.deleted()

    def named(owner: str, kind: str, k: str) -> None:
        found = objects.kinds.get(k, "absent")
        if found == "absent":
            if k in deleted:
                entry = f"{kind} {k}"
                if entry not in report.deleted:
                    report.deleted.append(entry)
            else:
                report.find(f"{owner} names the {kind} object {k}, which is missing")
        elif found != kind:
            report.find(f"{owner} names the {kind} object {k}, but {_rel(k)} is not one")

    readings = set(objects.of("reading@1"))
    for k in list(objects.of("packet@1")):
        owner = f"the packet {k}"
        try:
            packet = _packet(objects, k)
            for kind, n in _named(packet):
                named(owner, kind, n)
            for n in _keys(packet["reading"]):
                named(owner, "reading@1", n)
                readings.add(n)
            runs = _keys(packet["run"])
        except StoreError as exc:
            report.find(str(exc))
            continue
        for n in runs:
            found = objects.kinds.get(n, "absent")
            if found == "absent":
                named(owner, "run@N", n)
                continue
            try:
                run = _run(objects, n)
                problem = _run_chain(run)
                if problem is not None:
                    report.find(f"the run record {n}: {problem}")
                    continue
                for problem in _compare_inputs(objects, packet, run):
                    report.find(f"{owner}: {problem}")
                lines = _holds_text(objects, packet, run)
                if lines is None and n not in report.unchecked:
                    report.unchecked.append(n)
                for line in lines or []:
                    report.find(f"the run record {n}: line {line} holds document text")
            except (StoreError, ValueError, RecursionError) as exc:  # a key, but not a format
                report.find(f"{owner}: {exc}")
    for k in sorted(readings):
        if objects.kinds.get(k) != "reading@1":
            continue
        try:
            for kind, n in _reading_named(objects, k):
                named(f"the reading {k}", kind, n)
        except StoreError as exc:
            report.find(str(exc))

    logs, problems = store.log_names()
    for problem in problems:
        report.find(problem)
    report.logs = len(logs)
    for log in logs:
        try:
            _split_view(report, log, store.read(log))
            continue
        except StoreError as exc:
            if not (repair and isinstance(exc, Torn)):
                report.find(str(exc))
                continue
        try:
            cut = store.repair(log)
            if cut is not None:
                report.cut.append((_log_rel(log), cut))
            _split_view(report, log, store.read(log))
        except StoreError as exc:
            report.find(str(exc))
    return report


def _split_view(report: Report, log: tuple[str, ...], records: list[dict[str, Any]]) -> None:
    """A finding for a splits log whose view fails: a bad record, or a second split for one
    document (§10)."""
    from .splits import split_view

    if log[0] != "splits":
        return
    try:
        split_view(records, log[1])
    except ValueError as exc:
        report.find(f"{_log_rel(log)}: {exc}")


# rebuild


def _reading_cache(objects: _Objects) -> bytes:
    """The reading cache (§5.1): for each source, reader and options, the readings. A reading
    whose text or layout is not in the store is not in the cache."""
    entries: dict[str, dict[str, Any]] = {}
    for k in objects.of("reading@1"):
        try:
            reading = _reading(objects, k)
            parts = _reading_named(objects, k)
        except StoreError:
            continue  # check reports it
        if any(objects.kinds.get(n) != kind for kind, n in parts if kind != "source@1"):
            continue
        entry = {"source": reading["source"], "reader": reading["reader"]}
        entry["options"] = reading["options"]
        name = jcs(entry)
        entries.setdefault(name, {**entry, "readings": []})["readings"].append(k)
    rows = []
    for name in sorted(entries):
        row = entries[name]
        row["readings"] = sorted(row["readings"])
        rows.append(row)
    return jcs({"format": "reading-cache@1", "readings": rows}).encode("utf-8")


def rebuild(store: FolderStore) -> list[str]:
    """Build each view again from the objects and logs, and return the path of each view
    file. The same objects and logs give the same bytes."""
    from ..review.labels import labels_view

    objects = _Objects(store)
    return [
        store.write_view("readings.json", _reading_cache(objects)),
        store.write_view("calibrate-labels.json", labels_view(store)),
    ]


# forget


def _others(objects: _Objects, packet: str, skip: frozenset[str] = frozenset()) -> dict[str, int]:
    """For each key, how many other packets name it, with their readings, their run records
    and the objects of the run records. A packet in ``skip`` does not count. A packet that
    cannot be read names nothing: ``check`` reports it. A reading or a run record that cannot be
    read names nothing, but the rest of its packet still counts."""
    counts: dict[str, int] = {}
    for k in objects.of("packet@1"):
        if k == packet or k in skip:
            continue
        try:
            obj = _packet(objects, k)
            named = {n for _, n in _named(obj)}
            readings = _keys(obj["reading"])
            runs = _keys(obj["run"])
        except (StoreError, ValueError, RecursionError):
            continue
        for n in readings:
            named.add(n)
            if objects.kinds.get(n) == "reading@1":
                with suppress(StoreError, ValueError, RecursionError):  # check reports it
                    named.update(m for _, m in _reading_named(objects, n))
        for n in runs:
            named.add(n)
            if (objects.kinds.get(n) or "").startswith("run@"):
                with suppress(StoreError, ValueError, RecursionError):  # check reports it
                    named.update(m for _, m in _run_objects(objects, _run(objects, n))[0])
        for n in named:
            counts[n] = counts.get(n, 0) + 1
    return counts


# The members that a correction packet of ``review resolve`` shares with its packet (#516).
_SAME_INPUTS = ("spec", "document", "reading", "schema", "policy", "references", "packs")
_CORRECTIONS = frozenset({"correct", "adjust_span"})


def _review_plan(
    objects: _Objects, packet: str, obj: Mapping[str, Any]
) -> tuple[list[tuple[str, str]], frozenset[str], dict[str, int], list[tuple[str, ...]]]:
    """The review objects of a packet for ``forget`` with ``everything`` (#516): each
    correction packet of ``review resolve`` with its candidates, judgments and receipt, then
    each ``task@1`` and ``resolution@1`` that names the packet. Also return the keys of the
    correction packets, and for each object of a correction packet whose receipt a resolution
    of another packet names, the number of those packets: that correction is shared, so its
    kept objects stay. Last, return each answer log of the packet that the store cannot read.
    A ``review-policy@1`` object holds no document data and stays.

    A correction packet is a packet with the inputs of the packet, no run record, and the exact
    candidates and judgments that ``review resolve`` gives to ``admit`` for a correction answer
    of the packet (review.md §6.2): the candidates of the packet without those of the slot, and
    the person's candidate last. ``_correction_inputs`` finds them from the receipt, the
    judgments and the task, which ``forget`` keeps, so a plain ``forget`` before does not hide
    a correction. Each key comes from the list of store objects, never from an object or a
    log, so no path comes from untrusted data. An object that cannot be read names nothing."""
    tasks: dict[str, Any] = {}
    resolutions: list[tuple[str, str]] = []
    unread: list[tuple[str, ...]] = []
    elsewhere: dict[str, set[str]] = {}  # receipt -> the other packets whose resolution names it
    for kind in ("task@1", "resolution@1"):
        for k in sorted(objects.of(kind)):
            with suppress(StoreError, ValueError, RecursionError):
                found = objects.json(kind, k)
                if not isinstance(found, dict) or not isinstance(found.get("packet"), str):
                    continue
                if found["packet"] != packet:
                    if kind == "resolution@1" and isinstance(found.get("slots"), list):
                        for slot in found["slots"]:
                            r = slot.get("receipt") if isinstance(slot, dict) else None
                            if isinstance(r, str):
                                elsewhere.setdefault(r, set()).add(found["packet"])
                elif kind == "task@1":
                    tasks[k] = found
                else:
                    resolutions.append((kind, k))
    wanted = _correction_inputs(objects, packet, obj, tasks, unread)
    plan: list[tuple[str, str]] = []
    corrections: set[str] = set()
    shared: dict[str, int] = {}
    for k in sorted(objects.of("packet@1")) if wanted else []:
        if k == packet:
            continue
        try:
            other = _packet(objects, k)
            if other["run"] is not None or any(other[m] != obj[m] for m in _SAME_INPUTS):
                continue
            named = _named(other)
            if not _is_correction(objects, other, wanted):
                continue
        except (StoreError, ValueError, TypeError, RecursionError):
            continue
        corrections.add(k)
        own = [(kind, n) for kind, n in named if kind in ("candidates@1", "judgments@1")]
        receipts = [(kind, n) for kind, n in named if kind == "receipt@1"]
        plan += own + receipts + [("packet@1", k)]
        users = set().union(*(elsewhere.get(n, set()) for _, n in receipts)) - {packet}
        if users:  # the same correction of another packet: it is shared
            for _, n in [*own, *receipts, ("packet@1", k)]:
                shared[n] = shared.get(n, 0) + len(users)
    review = plan + [("task@1", k) for k in tasks] + resolutions
    return review, frozenset(corrections), shared, unread


def _correction_inputs(
    objects: _Objects,
    packet: str,
    obj: Mapping[str, Any],
    tasks: Mapping[str, Any],
    unread: list[tuple[str, ...]],
) -> list[tuple[Counter[str], str, str | None]]:
    """For each correction answer of the packet, the inputs that ``review resolve`` gives to
    ``admit`` (review.md §6.2): the digests of the kept candidates, the person's candidate as
    canonical JSON, and the key of the kept judgments. The kept candidates come from the
    candidate digests of the receipt, so the candidates of the packet need not be in the store.
    A record, a task or a receipt that does not have the expected form gives nothing. Each
    answer log of the packet that the store cannot read goes into ``unread``."""
    try:
        receipt = objects.json("receipt@1", obj["receipt"])
        decisions = receipt["decisions"]
        judgments = None
        if obj["judgments"] is not None:
            judgments = objects.json("judgments@1", obj["judgments"])
        if not isinstance(decisions, list) or not isinstance(judgments, (list, type(None))):
            return []
        every = [d["candidate_sha256"] for d in decisions]
    except (StoreError, ValueError, TypeError, KeyError, RecursionError):
        return []
    out: list[tuple[Counter[str], str, str | None]] = []
    logs, _ = objects.store.log_names()
    for log in logs:
        if log[0] != "answers" or log[1] != packet:
            continue
        try:
            records = objects.store.read(log)
        except StoreError:
            unread.append(log)
            continue
        for r in records:
            with suppress(ValueError, TypeError, KeyError, IndexError, RecursionError):
                tk = r.get("task")
                task = tasks.get(tk) if isinstance(tk, str) else None
                c = r.get("candidate")
                if r.get("verdict") not in _CORRECTIONS or not isinstance(c, dict) or not task:
                    continue
                slot = task["slot"]["decisions"]
                if not isinstance(slot, list) or not all(type(i) is int and i >= 0 for i in slot):
                    continue
                removed = {decisions[i]["candidate_sha256"] for i in slot}
                gone = {
                    d["candidate_id"] for d in decisions
                    if d["candidate_sha256"] in removed and type(d["candidate_id"]) in (str, int)
                }  # fmt: skip
                left = None
                if judgments is not None:
                    left = _json_key("judgments@1", [
                        j for j in judgments
                        if not (isinstance(j, dict) and type(j.get("candidate_id")) in (str, int)
                                and j["candidate_id"] in gone)
                    ])  # fmt: skip
                out.append((Counter(h for h in every if h not in removed), jcs(c), left))
    return out


def _is_correction(
    objects: _Objects,
    other: Mapping[str, Any],
    wanted: list[tuple[Counter[str], str, str | None]],
) -> bool:
    """True if the candidates and the judgments of ``other`` are the exact inputs of one
    correction in ``wanted``: the kept candidates, then the person's candidate last."""
    if not wanted or not isinstance(other["candidates"], str):
        return False
    found = objects.json("candidates@1", other["candidates"])
    if not isinstance(found, list) or not found:
        return False
    last = jcs(found[-1])
    kept = Counter(digest("candidate", c) for c in found[:-1])
    return any(
        last == person and kept == digests and other["judgments"] == judged
        for digests, person, judged in wanted
    )


def _json_key(kind: str, value: Any) -> str:
    return key(kind, jcs(value).encode("utf-8"))


def forget_packet(
    store: FolderStore, packet: str, reason: str, *, everything: bool = False
) -> list[tuple[str, str, str, int]]:
    """Remove the objects of a packet that §8 rule 3 lists as "Removed", and record each
    deletion in ``logs/deleted.jsonl``. An object that two packets share goes for both.

    ``forget`` also removes the run record if a line holds document text, or if its text is not
    in the store (then the lines cannot be checked). The run
    record goes after the objects that it names, so a ``forget`` that stops can run again. The
    text check finds only a string of ``MIN_TEXT`` or more characters that is in the text: it
    is not a proof.

    With ``everything``, remove each object and each answer log of the packet, and the packet
    last. It also removes each ``task@1`` and ``resolution@1`` that names the packet, and
    each correction packet that ``review resolve`` wrote for it, with its candidates, judgments
    and receipt (#516). A ``review-policy@1`` object stays. If an answer log of the packet
    cannot be read, it is ``unchecked``: it can name a correction. Then ``everything`` removes
    only what a plain ``forget`` removes and the corrections that it finds, and keeps the
    packet, its tasks, its resolutions and its logs, so a second call after a repair of the
    log can finish. An object of the "Kept" column that
    another packet names stays, but a correction packet of this packet does not count. A
    packet that cannot be read counts as a packet that names nothing, so run ``check`` first. If
    an answer log is locked, ``everything`` stops before it removes the packet, so a second
    call can finish the work. This is also the result when another ``forget`` of the same
    packet holds the lock of the log. A log or packet that another ``forget`` removed first
    is ``absent``.

    An object of the packet that ``forget`` cannot read is ``unchecked``, and the rest is still
    removed. A run record is ``unchecked`` and stays if ``forget`` cannot read its lines, the
    header too, if its bytes do not match its key, or if the store refuses its file. Only the
    record names its prompts, replies and admissions, and ``forget`` does not trust the lines
    of a changed record (#486). With
    ``everything``, the packet then stays too, so ``check`` and ``forget`` still name the
    record. An edit gives the record another key, so it cannot repair the record. Put back a
    copy of the original record, or call ``FolderStore.forget`` on its key: then the objects
    that it names stay with no record that names them, and a second ``forget`` with
    ``everything`` removes the packet.

    The deleted-log entry of a removed prompt, reply or admission holds its run keys (§7.1).
    If the run record names a run key of the deleted log, that object was removed before, and
    it is ``absent`` (#442). If the run record names a run key that matches no object and no
    deletion, each object of the store that cannot be read is ``unchecked``, because it can be
    that object. An entry from 0.12 or earlier has no run keys, so this rule applies to it.

    Return the kind, the key, the state (``deleted``, ``absent``, ``kept`` or ``unchecked``)
    and the number of other packets that name the key, for each object. A log has the kind
    ``log`` and its path in place of the key."""
    if not isinstance(packet, str) or not KEY.fullmatch(packet):
        raise ValueError(f"{printable(packet)} is not a store key")
    objects = _Objects(store)
    if objects.kinds.get(packet) != "packet@1":
        raise NotFound(f"the packet {packet} is not in the store")
    obj = _packet(objects, packet)
    named = _named(obj)  # a packet with bad members raises: then nothing is known
    plan: list[tuple[str, str, bool]] = []  # the kind, the key, and "remove in any mode"
    unchecked: list[tuple[str, str]] = []
    unread_runs: list[str] = []  # the run records that cannot be read, which stay
    for k in _keys(obj["run"]):
        kind = objects.kinds.get(k, "absent")
        if kind is None:
            # The packet names it as its run record, but forget cannot read it, or its bytes
            # do not match its key. Keep it: only the record names its prompts, replies and
            # admissions, and the lines of a changed record are not trusted (#444, #486).
            unchecked.append(("run@N", k))
            unread_runs.append(k)
            continue
        if kind == "absent" or not kind.startswith("run@"):
            plan.append(("run@N", k, False))
            continue
        try:
            run = _run(objects, k)
        except (StoreError, ValueError, RecursionError):
            # Keep a record whose lines cannot be read: it is the only thing that names its
            # prompts, replies and admissions.
            unchecked.append((kind, k))
            unread_runs.append(k)
            continue
        try:
            lines = _holds_text(objects, obj, run)
        except (StoreError, ValueError, RecursionError):  # the text or schema cannot be read
            lines = None
        # The record goes after the objects that it names: a forget that stops can find them
        # again from the record.
        found, missing = _run_objects(objects, run)
        plan += [(kind, n, False) for kind, n in found]
        plan.append((run.kind, k, lines is None or bool(lines)))
        # A run key that matches no object: forgotten before, or an object that cannot be read.
        # The deleted log names the run keys of each object that forget removed (#442). A
        # deletion that names an object of the store is not trusted: that object is there.
        deleted = objects.deleted_runs()
        unknown = False
        for kind, r in missing:
            n = deleted.get(r)
            if n is not None and n not in objects.kinds:
                plan.append((kind, n, False))
            else:
                unknown = True
        if unknown:
            # The objects that cannot be read are "unchecked", so the user can see them.
            unchecked += [(kind or "object", n) for n, kind in objects.unread()]
    plan += [(kind, k, False) for kind, k in named]
    for k in _keys(obj["reading"]):
        plan.append(("reading@1", k, False))
        if objects.kinds.get(k) == "reading@1":
            try:
                plan += [(kind, n, False) for kind, n in _reading_named(objects, k)]
            except StoreError:
                unchecked.append(("reading@1", k))
    corrections: frozenset[str] = frozenset()
    shared_corrections: dict[str, int] = {}
    unread_logs: list[tuple[str, ...]] = []
    if everything:
        review, corrections, shared_corrections, unread_logs = _review_plan(objects, packet, obj)
        if unread_logs:
            # An answer log that cannot be read can name a correction. Keep what finds it
            # again: the packet, its kept objects, its tasks, its resolutions and its logs. A
            # later forget with everything can then finish (#516).
            plan = [(kind, k, always) for kind, k, always in plan if kind in REMOVED or always]
            review = [(kind, k) for kind, k in review if kind not in ("task@1", "resolution@1")]
            unchecked += [("log", _log_rel(log)) for log in unread_logs]
        plan += [(kind, k, False) for kind, k in review]
    else:
        plan = [(kind, k, always) for kind, k, always in plan if kind in REMOVED or always]
    others = _others(objects, packet, corrections)
    for ck, cn in shared_corrections.items():
        others[ck] = others.get(ck, 0) + cn
    done: list[tuple[str, str, str, int]] = [
        (kind, k, "unchecked", others.get(k, 0)) for kind, k in dict.fromkeys(unchecked)
    ]
    seen: set[str] = set()
    for kind, k, always in plan:
        if k in seen:
            continue
        seen.add(k)
        shared = others.get(k, 0)
        if k not in objects.kinds:
            done.append((kind, k, "absent", shared))
        elif everything and shared and kind not in REMOVED and not always:
            done.append((kind, k, "kept", shared))
        else:
            runs = objects.run_keys(k) if kind in _RUN_KINDS else []
            try:
                store.forget(k, reason, run_keys=runs)
            except NotFound:  # another forget removed it after the walk
                done.append((kind, k, "absent", shared))
                continue
            done.append((kind, k, "deleted", shared))
    if everything and unread_logs:
        done.append(("packet@1", packet, "kept", 0))
        return done
    if everything:
        logs, _ = store.log_names()
        for log in logs:
            if log[0] == "answers" and log[1] == packet:
                try:
                    store.forget_log(log, reason)
                except NotFound:  # another forget removed it after the list
                    done.append(("log", _log_rel(log), "absent", 0))
                    continue
                done.append(("log", _log_rel(log), "deleted", 0))
        if unread_runs:  # the packet stays, so check and forget still name the kept record
            done.append(("packet@1", packet, "kept", 0))
            return done
        try:
            store.forget(packet, reason)
        except NotFound:  # another forget removed it after the walk
            done.append(("packet@1", packet, "absent", 0))
        else:
            done.append(("packet@1", packet, "deleted", 0))
    return done
