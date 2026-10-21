"""Check, rebuild and forget in a folder store (docs/design/store.md §7.4, §8, §12 issue 3).

``check`` reads each object and each log of a ``FolderStore``. It finds the kind of each object
from its key, checks each object that a packet, a reading or a run names, checks each chain,
compares the inputs of a packet with the inputs that its run header names, and looks for
document text in each run record. ``rebuild`` builds the views again from the objects and logs.
``forget_packet`` removes the objects of a packet that §8 rule 3 lists as "Removed", or with
``everything`` each object and log of the packet.

The store data is untrusted. These functions build no path from it: each path comes from a key
that matches ``sha256:[0-9a-f]{64}`` or from a fixed word.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from ..canonical import jcs
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
# A string of a run record line with this many characters or more, that is also in the
# document text, is document text.
MIN_TEXT = 8
VIEWS = ("readings.json",)
_BYTES = frozenset({"source@1", "text@1", "prompt@1", "reply@1"})


@dataclass
class Report:
    """What ``check`` found. ``findings`` are problems. ``deleted`` names each input that
    ``forget`` removed, which is not a problem. ``cut`` holds each torn line that ``repair``
    cut, with the log path."""

    objects: int = 0
    logs: int = 0
    findings: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
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


def run_hash(runner: str, kind: str, data: str) -> str:
    """A key of the run record: SHA-256 over ``<runner>:<kind>``, a zero byte and the data, as
    the runner calculates it (runner.md)."""
    digest = hashlib.sha256(f"{runner}:{kind}\0".encode() + data.encode("utf-8"))
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

    def json(self, kind: str, k: str) -> Any:
        data = self.store.get(kind, k)
        try:
            return _canonical(data.decode("utf-8"), f"the {kind} object {k}")
        except (UnicodeDecodeError, ValueError) as exc:
            raise StoreError(str(exc)) from exc


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
    assert found is not None  # kind_of found the kind from the header
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


def _run_objects(objects: _Objects, run: _Run) -> list[tuple[str, str]]:
    """The store kind and key of each prompt, reply and admission that the run record names.
    The record names them by run keys, so each object of these kinds is hashed again."""
    wanted: dict[str, str] = {}
    for line in run.lines:
        for member, (_, kind) in _RUN_OBJECTS.items():
            value = line.get(member)
            if isinstance(value, str):
                wanted[value] = kind
    found = []
    for word, kind in _RUN_OBJECTS.values():
        for k in objects.of(kind):
            data = objects.store.get(kind, k).decode("utf-8")
            if wanted.get(run_hash(run.runner, word, data)) == kind:
                found.append((kind, k))
    return found


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
                for line in _holds_text(objects, packet, run) or []:
                    report.find(f"the run record {n}: line {line} holds document text")
            except (StoreError, ValueError) as exc:  # bytes that match a key but not a format
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
            store.read(log)
            continue
        except StoreError as exc:
            if not (repair and isinstance(exc, Torn)):
                report.find(str(exc))
                continue
        try:
            cut = store.repair(log)
            if cut is not None:
                report.cut.append((_log_rel(log), cut))
            store.read(log)
        except StoreError as exc:
            report.find(str(exc))
    return report


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
    objects = _Objects(store)
    return [store.write_view("readings.json", _reading_cache(objects))]


# forget


def _others(objects: _Objects, packet: str) -> dict[str, int]:
    """For each key, how many other packets name it, with their readings and run records. A
    packet that cannot be read names nothing: ``check`` reports it."""
    counts: dict[str, int] = {}
    for k in objects.of("packet@1"):
        if k == packet:
            continue
        try:
            obj = _packet(objects, k)
            named = {n for _, n in _named(obj)}
            for n in _keys(obj["reading"]):
                named.add(n)
                if objects.kinds.get(n) == "reading@1":
                    named.update(m for _, m in _reading_named(objects, n))
            named.update(_keys(obj["run"]))
        except StoreError:
            continue
        for n in named:
            counts[n] = counts.get(n, 0) + 1
    return counts


def forget_packet(
    store: FolderStore, packet: str, reason: str, *, everything: bool = False
) -> list[tuple[str, str, str, int]]:
    """Remove the objects of a packet that §8 rule 3 lists as "Removed", and record each
    deletion in ``logs/deleted.jsonl``. An object that two packets share goes for both.

    ``forget`` also removes the run record if a line holds document text, if its text is not in
    the store (then the lines cannot be checked), or if it does not match its key. The run
    record goes first, so a ``forget`` that stops can run again. The text check finds only a
    string of ``MIN_TEXT`` or more characters that is in the text: it is not a proof.

    With ``everything``, remove each object and each answer log of the packet, and the packet
    last. An object of the "Kept" column that another packet names stays. Tasks and
    resolutions are not in the store yet, so ``everything`` does not look for them (#432).

    Return the kind, the key, the state (``deleted``, ``absent`` or ``kept``) and the number
    of other packets that name the key, for each object. A log has the kind ``log`` and its
    path in place of the key."""
    if not isinstance(packet, str) or not KEY.fullmatch(packet):
        raise ValueError(f"{printable(packet)} is not a store key")
    objects = _Objects(store)
    if objects.kinds.get(packet) != "packet@1":
        raise NotFound(f"the packet {packet} is not in the store")
    obj = _packet(objects, packet)
    plan: list[tuple[str, str, bool]] = []  # the kind, the key, and "remove in any mode"
    for k in _keys(obj["run"]):
        kind = objects.kinds.get(k, "absent")
        if kind is None or kind == "absent" or not kind.startswith("run@"):
            plan.append(("run@N", k, kind is None))  # a changed record cannot be checked
            continue
        run = _run(objects, k)
        lines = _holds_text(objects, obj, run)
        plan.append((run.kind, k, lines is None or bool(lines)))
        plan += [(kind, n, False) for kind, n in _run_objects(objects, run)]
    plan += [(kind, k, False) for kind, k in _named(obj)]
    for k in _keys(obj["reading"]):
        plan.append(("reading@1", k, False))
        if objects.kinds.get(k) == "reading@1":
            plan += [(kind, n, False) for kind, n in _reading_named(objects, k)]
    if not everything:
        plan = [(kind, k, always) for kind, k, always in plan if kind in REMOVED or always]
    others = _others(objects, packet)
    done: list[tuple[str, str, str, int]] = []
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
            store.forget(k, reason)
            done.append((kind, k, "deleted", shared))
    if everything:
        logs, _ = store.log_names()
        for log in logs:
            if log[0] == "answers" and log[1] == packet:
                store.forget_log(log, reason)
                done.append(("log", _log_rel(log), "deleted", 0))
        store.forget(packet, reason)
        done.append(("packet@1", packet, "deleted", 0))
    return done
