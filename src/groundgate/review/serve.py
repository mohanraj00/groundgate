"""The review page: a local server for the tasks in a store (docs/design/review.md §8, §9).

``Review`` holds the tasks of each packet in the store and the queue of one reviewer. It shows a
task with its source, checks a correction with the same ``admit`` call as ``review resolve``,
checks each answer against its task, and appends the answer to the answer log of the reviewer.
``server`` puts it behind an HTTP server with the eight rules of §9:

1. The server binds to 127.0.0.1, and refuses a request whose ``Host`` is not 127.0.0.1 and the
   port.
2. Each API request sends the random token of the start URL in a header.
3. A POST is ``application/json`` of 64 KiB at most.
4. Each response has the CSP of §9 rule 4, except the frame of an HTML source (rule 6).
5. The page puts document text into the page only with ``textContent``.
6. An HTML source goes into a frame with ``sandbox=""`` and its own CSP. The frame URL holds a
   ticket for one use, not the token.
7. A path names an object only by a store key. No path or URL comes from a document or a
   request.
8. Each answer is checked against its task before the write.

A calibrate task (§11, ``groundgate.review.labels``) is served only when the packet gives it. It
shows no code and no outcome, and it takes an ``answer@2`` label. ``only`` limits the queue to
the tasks of one calibrate work folder.

The store data and each request are untrusted. The token holder can answer as any reviewer name,
and a lead answer is not an authenticated act: the server is for one local user.
"""

from __future__ import annotations

import bisect
import contextlib
import hmac
import json
import re
import secrets
import threading
import unicodedata
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import MAX_PREC, Context, Decimal, Inexact, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any

from ..canonical import jcs
from ..codes import DESCRIPTIONS, INFO
from ..escape import escape
from ..model import PacketError, Schema
from ..read.layout import Layout
from ..read.markup import html_text
from ..text import (
    Token,
    bracket_sign,
    brackets_around,
    canonical,
    gain_word,
    item_scale,
    loss_sign,
    normalize_ws,
    parse_value,
    quote_pattern,
    scale_powers,
    scaled_value,
    sentence,
    token_scale,
    tokens,
    using,
)
from .labels import QUESTIONS, label_tasks
from .resolve import (
    CORRECTIONS,
    EVERY_TASK,
    VERDICTS,
    AnswerError,
    _admit_only,
    _check,
    _correct,
    _read,
    resolve,
)
from .tasks import (
    DEFAULT_POLICY,
    Slot,
    _number,
    _Source,
    check_policy,
    checked_packet,
    make_tasks,
    slots,
)

__all__ = ["CSP", "MAX_BODY", "TOKEN_HEADER", "Refused", "Review", "frame_csp", "server"]

MAX_BODY = 64 * 1024
TOKEN_HEADER = "X-Groundgate-Token"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "frame-src 'self'; img-src 'self'; form-action 'none'; base-uri 'none'; "
    "frame-ancestors 'none'"
)
# the page and its script and style hold no data, so they need no token; the API does
STATIC = {
    "/": ("review.html", "text/html"),
    "/review.js": ("review.js", "text/javascript"),
    "/review.css": ("review.css", "text/css"),
}
_KEY = re.compile(r"sha256:[0-9a-f]{64}")
_API = re.compile(r"/api/(task|reason)/(.*)")
_TICKET = re.compile(r"/frame/([A-Za-z0-9_-]{22})")
CONTEXT_LINES = 5  # the lines before and after a value in the text view
SPAN_LINES = 12  # a place with more lines than this shows its two ends, and the middle is closed
SCALE_LINES = 10  # the lines above a selected number where the page looks for a scale (#496)
MAX_TICKETS = 32
_EXACT = Context(prec=MAX_PREC, traps=[Inexact])  # a power of ten with no rounding, as in admit
MAX_PARTS = 8
ROLES = ("sign", "scale", "unit", "field", "key")
_SETTLED = frozenset({"admitted", "confirmed", "chosen", "corrected", "not_in_document"})
_MARK = '<mark style="background:#ffe066;outline:3px solid #c92a2a">'
# A frame cannot go to another host (§9 rule 6). The CSP stops each load, but not a meta refresh
# or a link that the person clicks. An attribute name has no escape form, so these two patterns
# find each http-equiv attribute and each href attribute, also an SVG animation of an href.
_EQUIV = re.compile(r"http-equiv", re.IGNORECASE)
_HREF = re.compile(r"\bhref\b", re.IGNORECASE)
# Elements whose text is not markup, where a box would show as text or break the element.
_RAW = ("script", "style", "title", "textarea", "xmp", "noscript", "noembed", "noframes",
        "iframe", "plaintext", "template")  # fmt: skip
_LIMIT = 2**31  # keys and ms


def frame_csp(origin: str) -> str:
    """The CSP of the frame of an HTML source (§9 rule 6). It replaces the CSP of rule 4 for the
    frame response, and it lets only the review page at ``origin`` hold the frame."""
    return (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'; "
        f"frame-ancestors {origin}; sandbox"
    )


class Refused(Exception):
    """A request that the server refuses. ``code`` is the HTTP status."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _printable(value: object) -> str:
    text = value if isinstance(value, str) else repr(value)
    text = escape(text)
    return text if len(text) <= 300 else text[:297] + "..."


class _Units:
    """Offsets in one text: UTF-8 bytes (the unit of a span, SPEC §2.2), code points (Python)
    and UTF-16 code units (the browser)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.source = _Source(text)
        self.astral = [i for i, ch in enumerate(text) if ord(ch) > 0xFFFF]

    def chars(self, start: int, end: int) -> tuple[int, int] | None:
        """The byte span as code points, or None when it is not a span of the text."""
        return self.source.chars((start, end))

    def u16(self, cp: int) -> int:
        return cp + bisect.bisect_left(self.astral, cp)

    def from_u16(self, u: int) -> int | None:
        """The code point at UTF-16 offset ``u``, or None inside a surrogate pair or out of
        range."""
        lo, hi = 0, len(self.text)
        while lo <= hi:
            mid = (lo + hi) // 2
            at = self.u16(mid)
            if at == u:
                return mid
            if at < u:
                lo = mid + 1
            else:
                hi = mid - 1
        return None

    def to_bytes(self, cp: int) -> int:
        return len(self.text[:cp].encode("utf-8"))


@dataclass
class _Doc:
    """One packet of the store, decided again, with its tasks."""

    key: str
    packet: Any
    schema: Schema
    layout: Layout | None
    units: _Units
    by_key: dict[str, tuple[Slot, dict[str, Any]]]  # each task that the packet gives
    labels: dict[str, tuple[Slot, dict[str, Any]]]  # each calibrate task of the store (§11)
    tasks: list[str]  # the tasks of this packet in the store
    ids: list[object]
    document: str
    kind: str = "text"  # pdf, html or text
    html: str | None = None
    open: list[str] = field(default_factory=list)  # the tasks in the queue
    words: dict[int, list[Any]] = field(default_factory=dict)  # PDF words by page


def _named(record: Mapping[str, Any]) -> bool:
    """True if an answer record gives its task and its verdict as strings. ``resolve`` refuses
    the other records, but a set or a dict key must not fail on them first."""
    return isinstance(record.get("task"), str) and isinstance(record.get("verdict"), str)


def _task_key(task: Mapping[str, Any]) -> str:
    from ..store import key

    return key("task@1", jcs(task).encode("utf-8"))


class Review:
    """The tasks of a store and the queue of one reviewer. Each method takes the request data
    and gives a JSON value, or raises ``Refused``. The caller holds one lock around each call.

    ``store`` is a ``FolderStore``: ``Review`` lists its task objects and answer logs. A packet
    whose receipt does not match its inputs, or whose input is not in the store, gives no task
    and a line in ``skipped``."""

    def __init__(
        self,
        store: Any,
        reviewer: str,
        policy: Mapping[str, Any] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        only: Collection[str] | None = None,
    ) -> None:
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("a reviewer name must have a character that is not a space")
        self.store = store
        self.reviewer = reviewer
        self.policy = check_policy(dict(DEFAULT_POLICY) if policy is None else policy)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.docs: dict[str, _Doc] = {}
        self.tasks: dict[str, str] = {}  # task key -> packet key
        self.skipped: list[str] = []
        self.tickets: dict[str, tuple[str, str | None]] = {}  # frame ticket -> packet, value
        self._only = None if only is None else frozenset(only)  # calibrate label: its tasks
        self._load()

    # Loading

    def _load(self) -> None:
        from ..store import StoreError, key

        keys, _ = self.store.object_keys()
        found: dict[str, list[str]] = {}
        for k in keys:
            try:
                data = self.store.object_bytes(k)
            except StoreError:
                continue
            if key("task@1", data) != k or (self._only is not None and k not in self._only):
                continue
            try:
                task = json.loads(data)
            except (ValueError, RecursionError):  # deep nesting fits in a store object
                continue
            pk = task.get("packet") if isinstance(task, dict) else None
            if isinstance(pk, str) and _KEY.fullmatch(pk):
                found.setdefault(pk, []).append(k)
        for pk in sorted(found):
            try:
                doc = self._doc(pk, found[pk])
            except Exception as exc:  # a packet in the store is untrusted input (§9)
                self.skipped.append(f"packet {pk}: {_printable(str(exc))}")
                continue
            other = len(found[pk]) - len(doc.tasks)
            if other:
                self.skipped.append(f"packet {pk}: {other} task objects of another packet")
            self.docs[pk] = doc
            for tk in doc.tasks:
                self.tasks[tk] = pk
            self._refresh(pk)

    def _doc(self, pk: str, stored: list[str]) -> _Doc:
        from ..store import StoreError
        from ..store.packets import load_reading

        packet, schema, layout, problems = checked_packet(self.store, pk)
        if problems or schema is None:
            raise ValueError("the receipt does not match its inputs")
        every = make_tasks(pk, packet.receipt, packet.text, schema, EVERY_TASK,
                           references=packet.references, layout=layout)  # fmt: skip
        by_slot = {(s.field, s.key, s.decisions): s for s in slots(packet.receipt, schema)}
        by_key: dict[str, tuple[Slot, dict[str, Any]]] = {}
        for t in every:
            s = t["slot"]
            slot = by_slot.get((s["field"], s["key"], tuple(s["decisions"])))
            if slot is not None:
                by_key[_task_key(t)] = (slot, t)
        labels: dict[str, tuple[Slot, dict[str, Any]]] = {}
        if set(stored) - set(by_key):  # a calibrate task must come from this packet too
            labels = label_tasks(pk, packet.receipt, packet.text, schema,
                                 references=packet.references, layout=layout,
                                 raw_schema=packet.schema)  # fmt: skip
        document = packet.receipt.get("document", {}).get("id")
        doc = _Doc(
            key=pk,
            packet=packet,
            schema=schema,
            layout=layout,
            units=_Units(packet.text),
            by_key=by_key,
            labels=labels,
            tasks=sorted(k for k in set(stored) if k in by_key or k in labels),
            ids=[c.get("id") for c in packet.candidates if isinstance(c, Mapping)],
            document="" if document is None else _printable(document),
        )
        if layout is not None:
            doc.kind = "pdf"
            for w in layout.words:
                doc.words.setdefault(w.box.page, []).append(w)
        elif packet.reading is not None:
            try:
                raw = self.store.get("source@1", load_reading(self.store, packet.reading)["source"])
                text = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
            except (StoreError, UnicodeDecodeError):
                text = None  # the text view still works
            if (
                text is not None
                and unicodedata.normalize("NFC", text) != packet.text
                and unicodedata.normalize("NFC", html_text(text)) == packet.text
            ):
                doc.kind, doc.html = "html", text
        return doc

    def _logs(self, pk: str) -> dict[str, list[dict[str, Any]]]:
        """The answer log of each reviewer of the packet. A log whose records name another
        reviewer than its file is left out, and so is a log that the store cannot read."""
        from ..store import StoreError, reviewer_key

        names, _ = self.store.log_names()
        out: dict[str, list[dict[str, Any]]] = {}
        for log in names:
            if log[0] != "answers" or log[1] != pk:
                continue
            try:
                records = self.store.read(log)
            except StoreError:
                continue
            name = records[0].get("reviewer") if records else None
            if isinstance(name, str) and reviewer_key(name) == log[2]:
                out[name] = records
        return out

    def _refresh(self, pk: str) -> None:
        """The queue of the packet: each task that this reviewer did not answer, and whose slot
        an answer does not settle (§8, Order)."""
        logs = self._logs(pk)
        answered = {r.get("task") for r in logs.get(self.reviewer, []) if _named(r)}
        settled = self.settled(pk, logs, self.policy)
        doc = self.docs[pk]
        doc.open = [k for k in doc.tasks if k not in answered and k not in settled]

    def settled(
        self, pk: str, logs: Mapping[str, list[dict[str, Any]]], policy: Mapping[str, Any]
    ) -> set[str]:
        """The tasks of the packet whose slot an answer of ``logs`` settles under ``policy``,
        a checked ``review-policy@1`` object."""
        doc = self.docs[pk]
        latest: dict[object, set[object]] = {}  # task -> the latest verdict of each reviewer
        for records in logs.values():
            last = {r.get("task"): r.get("verdict") for r in records if _named(r)}
            for task, verdict in last.items():
                latest.setdefault(task, set()).add(verdict)
        settled: set[str] = set()
        try:  # an answer to a calibrate task settles no slot
            resolution, _ = resolve(pk, doc.packet, doc.schema, policy, logs,
                                    layout=doc.layout)  # fmt: skip
        except (AnswerError, PacketError, ValueError):
            resolution = {"slots": []}  # a bad log settles nothing; resolve names it
        for s in resolution["slots"]:
            if s["status"] in _SETTLED and latest.get(s["task"], set()) - {"unsure"}:
                settled.add(s["task"])
        return settled

    # The API

    def queue(self) -> dict[str, Any]:
        """The open tasks, grouped by document and in page order."""
        items = [self.place(pk, tk) for pk, doc in self.docs.items() for tk in doc.open]
        return {
            "reviewer": self.reviewer,
            "tasks": [
                {"task": tk, "document": d, "page": page} for d, _, _, tk, page in sorted(items)
            ],
        }

    def place(self, pk: str, tk: str) -> tuple[str, str, int, str, int | None]:
        """The queue order of a task (document, packet, first offset, task), and its page."""
        doc = self.docs[pk]
        places = (doc.by_key.get(tk) or doc.labels[tk])[1]["places"]
        first = places[0]["start"] if places else len(doc.units.source.data)
        page = places[0]["page"] if places else None
        return doc.document, pk, first, tk, page

    def _task(self, tk: object) -> tuple[str, _Doc, Slot, dict[str, Any]]:
        if not isinstance(tk, str) or not _KEY.fullmatch(tk):
            raise Refused(400, "the task is not a store key")
        pk = self.tasks.get(tk)
        if pk is None:
            raise Refused(404, "the task is not a task of this store")
        doc = self.docs[pk]
        slot, task = doc.by_key.get(tk) or doc.labels[tk]
        return tk, doc, slot, task

    def view(self, tk: object) -> dict[str, Any]:
        """The task and its source, with each offset in UTF-16 code units."""
        tk, doc, slot, task = self._task(tk)
        u = doc.units
        places = []  # (start, end in code points, kind, choice numbers)
        for p in task["places"]:
            span = u.chars(p["start"], p["end"])
            if span is None:
                continue
            ns = [
                n
                for n, c in enumerate(task["choices"], 1)
                if c["evidence"] == {"start": p["start"], "end": p["end"]}
            ]
            places.append((span, p, ns))
        choices = []
        for n, c in enumerate(task["choices"], 1):
            quote = None
            for span, _, ns in places:
                if n in ns:
                    quote = u.text[span[0] : min(span[1], span[0] + 300)]
                    break
            choices.append({"n": n, "decision": c["decision"], "shown": c["shown"],
                            "quote": quote})  # fmt: skip
        mine = [r for r in self._logs(doc.key).get(self.reviewer, []) if r.get("task") == tk]
        label = None
        if tk in doc.labels:  # the page asks a calibrate question (§11)
            question = QUESTIONS[task["template"]]
            keys = doc.schema.fields[task["slot"]["field"]].keys if question == "key" else None
            label = {"question": question, "keys": list(keys or ())}
        return {
            "task": tk,
            "document": doc.document,
            "item": task["item"],
            "question": task["question"],
            # the question of a calibrate task holds the description already
            "definition": None if label else doc.schema.fields[slot.field].description,
            "parts": task["parts"],
            "choices": choices,
            "answered": mine[-1].get("verdict") if mine else None,
            "label": label,
            "view": self._source(doc, task, places),
        }

    def _source(self, doc: _Doc, task: Mapping[str, Any], places: list[Any]) -> dict[str, Any]:
        u = doc.units
        marks = [(span, "value" if ns else "part", ns) for span, _, ns in places]
        if doc.kind == "pdf" and doc.layout is not None:
            numbers = sorted({p["page"] for _, p, _ in places if p["page"] is not None})
            pages = []
            for page in doc.layout.pages:
                if numbers and page.number not in numbers:
                    continue
                words = []
                for w in doc.words.get(page.number, []):
                    span = u.chars(w.start, w.end)
                    if span is None:
                        continue
                    b = w.box
                    words.append([u.u16(span[0]), u.text[span[0] : span[1]],
                                  b.x0, b.top, b.x1, b.bottom])  # fmt: skip
                boxes = []
                for _, p, ns in places:
                    for b in doc.layout.locate(p["start"], p["end"]):
                        if b.page == page.number:
                            kind = "value" if ns else "part"
                            boxes.append([b.x0, b.top, b.x1, b.bottom, kind, ns])
                pages.append({"page": page.number, "width": page.width, "height": page.height,
                              "words": words, "marks": boxes})  # fmt: skip
            return {"kind": "pdf", "pages": pages}
        out: dict[str, Any] = {"kind": doc.kind, "blocks": self._blocks(u, task["item"], marks)}
        if doc.kind == "html" and doc.html is not None:
            value = next((u.text[s[0] : s[1]] for s, kind, _ in marks if kind == "value"), None)
            value = value or next((u.text[s[0] : s[1]] for s, _, _ in marks), None)
            _, marked, count = _marked(doc.html, value)
            ticket = secrets.token_urlsafe(16)
            self.tickets[ticket] = (doc.key, value)
            while len(self.tickets) > MAX_TICKETS:
                del self.tickets[next(iter(self.tickets))]
            out["frame"] = f"/frame/{ticket}"
            if marked:
                out["note"] = "The box in the original page marks the value."
            elif value is None:
                out["note"] = "The task has no value to mark in the original page."
            else:
                out["note"] = (
                    f"The value occurs {count} times in the original page, so it is not marked "
                    "there. The text below marks it."
                )
        return out

    @staticmethod
    def _blocks(u: _Units, item: str, marks: list[Any]) -> list[dict[str, Any]]:
        """The lines around each place, as blocks of text. A long span shows the lines at its
        two ends, and its middle is a closed block. Without a place, the whole text is one
        block."""
        text = u.text
        if not marks:
            return [{"start": 0, "text": text, "closed": False, "marks": []}]
        starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]

        def line(cp: int) -> int:
            return bisect.bisect_right(starts, cp) - 1

        def begin(n: int) -> int:
            return starts[max(n, 0)]

        def finish(n: int) -> int:
            return starts[n + 1] if n + 1 < len(starts) else len(text)

        opened: list[tuple[int, int]] = []
        closed: list[tuple[int, int]] = []
        for (s, e), _, _ in marks:
            a, b = line(s), line(max(e - 1, s))
            if item == "span" and b - a > SPAN_LINES:
                head, tail = finish(a + CONTEXT_LINES), begin(b - CONTEXT_LINES)
                opened += [(begin(a - CONTEXT_LINES), head), (tail, finish(b + CONTEXT_LINES))]
                closed.append((head, tail))
            else:
                opened.append((begin(a - CONTEXT_LINES), finish(b + CONTEXT_LINES)))
        merged: list[list[int]] = []
        for a, b in sorted(opened):
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        pieces = [(a, b, False) for a, b in merged]
        for a, b in closed:  # the part of a closed middle that no open block shows
            at = a
            for c, d in merged:
                if d <= at or c >= b:
                    continue
                if c > at:
                    pieces.append((at, c, True))
                at = max(at, d)
            if at < b:
                pieces.append((at, b, True))
        blocks = []
        for a, b, shut in sorted(pieces):
            inside = [
                [u.u16(max(s, a)), u.u16(min(e, b)), kind, ns]
                for (s, e), kind, ns in marks
                if s < b and e > a
            ]
            blocks.append({"start": u.u16(a), "text": text[a:b], "closed": shut, "marks": inside})
        return blocks

    def frame(self, ticket: str) -> str | None:
        """The HTML source of a frame ticket, with the value in a box when it occurs one time.
        A ticket works one time."""
        found = self.tickets.pop(ticket, None)
        html = None if found is None else self.docs[found[0]].html
        return None if found is None or html is None else _inert(_marked(html, found[1])[0])

    def reason(self, tk: object) -> dict[str, Any]:
        """The codes of the task and the outcome of each choice (§8, The reason is closed)."""
        tk, doc, _, task = self._task(tk)
        if tk in doc.labels:  # a calibrate task is blind: it shows no gate output
            return {"codes": [], "choices": []}
        decisions = doc.packet.receipt["decisions"]
        return {
            "codes": [{"code": c, "text": DESCRIPTIONS.get(c, "")} for c in task["codes"]],
            "choices": [
                {"n": n, "outcome": decisions[c["decision"]]["outcome"],
                 "codes": list(decisions[c["decision"]]["codes"])}
                for n, c in enumerate(task["choices"], 1)
            ],
        }  # fmt: skip

    def _span(self, doc: _Doc, start: object, end: object) -> tuple[int, int, int, int]:
        """A selection in UTF-16 offsets as code points and as UTF-8 bytes (§9 rule 8)."""
        if type(start) is not int or type(end) is not int:
            raise Refused(400, "start and end must be integers")
        a, b = doc.units.from_u16(start), doc.units.from_u16(end)
        if a is None or b is None or not a < b:
            raise Refused(400, "the selection is not a span inside the text")
        return a, b, doc.units.to_bytes(a), doc.units.to_bytes(b)

    def _part_scale(self, doc: _Doc, body: Mapping[str, Any]) -> int | None:
        """The power of ten of the first scale part of a request that gives one, or None."""
        parts = body.get("parts")
        for p in parts[:MAX_PARTS] if isinstance(parts, list) else []:
            if isinstance(p, Mapping) and p.get("role") == "scale":
                a, b, _, _ = self._span(doc, p.get("start"), p.get("end"))
                power = item_scale(doc.units.text, a, b)
                if power is not None:
                    return power
        return None

    def _part_sign(
        self, doc: _Doc, body: Mapping[str, Any], tok: Token, prefixes: list[str]
    ) -> bool:
        """Whether a sign part of a request makes the number negative, as admit reads a sign
        item (SPEC §4.6): brackets around the number inside the part, or a loss word before it
        in the same sentence. Call it with the vocabulary of the packet."""
        text = doc.units.text
        parts = body.get("parts")
        for p in parts[:MAX_PARTS] if isinstance(parts, list) else []:
            if not isinstance(p, Mapping) or p.get("role") != "sign":
                continue
            a, b, _, _ = self._span(doc, p.get("start"), p.get("end"))
            br = brackets_around(text, tok, prefixes)
            if br is not None and a <= br[0] and br[1] <= b:
                return True
            if b <= tok.start and loss_sign(text, a, b, tok.start):
                between = text[a : tok.start]
                if (
                    a >= sentence(text, tok.start)[0]
                    and not tokens(text, a, tok.start)
                    and "\n" not in between
                    and "\t" not in between
                    and not gain_word(text, a, tok.start)
                ):
                    return True
        return False

    def _candidate(
        self, doc: _Doc, slot: Slot, task: Mapping[str, Any], body: Mapping[str, Any]
    ) -> dict[str, Any]:
        """The person's candidate from a selection (§8, A correction is a selection)."""
        with using(doc.schema.vocabulary):  # the scale words of the packet's packs
            return self._read_candidate(doc, slot, task, body)

    def _read_candidate(
        self, doc: _Doc, slot: Slot, task: Mapping[str, Any], body: Mapping[str, Any]
    ) -> dict[str, Any]:
        a, b, start, end = self._span(doc, body.get("start"), body.get("end"))
        spec = doc.schema.fields[slot.field]
        typed = body.get("value")
        if typed is not None and (not isinstance(typed, str) or len(typed) > 1000):
            raise Refused(400, "the typed value must be a string of 1000 characters at most")
        typed = typed.strip() if typed else None
        candidate: dict[str, Any] = {"field": slot.field}
        if task["item"] == "number":
            if typed:
                number = parse_value(typed)
                if number is None:
                    raise Refused(400, "the typed value is not a number")
            else:
                found = [t for t in tokens(doc.units.text, a, b) if t.value is not None]
                if not found or found[0].value is None:
                    raise Refused(400, "the selection has no number: select it, or type it")
                # The value in full (§8): a scale word or suffix inside the selection scales it,
                # else a cited scale part (#496).
                scaled = scaled_value(doc.units.text[:b], found[0])
                power = self._part_scale(doc, body) if scaled is None else None
                if power is not None:
                    scaled = found[0].value.scaleb(power, _EXACT)
                number = found[0].value if scaled is None else scaled
            candidate["value"] = canonical(number)
            units = [c["unit"] for c in task["choices"] if isinstance(c["unit"], str)]
            unit = spec.unit or (units[0] if units else None)
            if unit is not None:
                candidate["unit"] = unit
        else:
            candidate["value"] = typed or normalize_ws(doc.units.text[a:b]).strip()
        if slot.key is not None:
            candidate["key"] = slot.key
        evidence = [{"start": start, "end": end}]
        parts = body.get("parts") or []
        if not isinstance(parts, list) or len(parts) > MAX_PARTS:
            raise Refused(400, f"parts must be a list of {MAX_PARTS} parts at most")
        for p in parts:
            if not isinstance(p, Mapping) or p.get("role") not in ROLES:
                raise Refused(400, f"each part needs a role: one of {', '.join(ROLES)}")
            _, _, ps, pe = self._span(doc, p.get("start"), p.get("end"))
            evidence.append({"role": p["role"], "start": ps, "end": pe})
        n = 1
        while f"review-{n}" in doc.ids:
            n += 1
        candidate["id"] = f"review-{n}"
        candidate["proposer"] = f"person:{self.reviewer}"
        candidate["evidence"] = evidence
        return candidate

    def _ask(
        self,
        doc: _Doc,
        slot: Slot,
        task: Mapping[str, Any],
        body: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        """The parts of a number correction that do not agree, each with its part and the words
        that the page shows (#496). The page asks again before it saves. The value must be the
        selected number with the scale and the sign of the text near it: a scale in the
        selection, a cited scale part, or a scale word on the lines above it. A choice of the
        task that differs only in its sign is also a question."""
        if task["item"] != "number":
            return []
        with using(doc.schema.vocabulary):  # the scale and loss words of the packet's packs
            return self._ask_number(doc, slot, task, body, candidate)

    def _ask_number(
        self,
        doc: _Doc,
        slot: Slot,
        task: Mapping[str, Any],
        body: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        a, b, _, _ = self._span(doc, body.get("start"), body.get("end"))
        text = doc.units.text
        found = [t for t in tokens(text, a, b) if t.value is not None]
        value = Decimal(candidate["value"])  # canonical() of a parsed number: finite
        if not found or value == 0:
            return []
        # each number that the value matches at some scale. admit takes one of them by its unit,
        # so the scale and sign questions read each one.
        abs_value = value.copy_abs()
        matched = [
            t for t in found if t.value is not None and abs_value in _scaled(t.value.copy_abs())
        ]
        spec = doc.schema.fields[slot.field]
        out = []
        cited = self._part_scale(doc, body) is not None  # a part with no scale asks too
        for m in (matched or found[:1]) if not cited and spec.unit != "%" else []:
            # the first number as written with a scale above it gets the question
            assert m.value is not None
            near = _near_scale(text, m) if token_scale(text[:b], m) is None else None
            if near is not None and abs_value == m.value.copy_abs():
                power, line = near
                full = abs_value.scaleb(power, _EXACT)
                out.append({"part": "scale", "text": (
                    f"The value is the number as written, {text[m.start : m.end]}, but the text "
                    f'above it gives a scale: "{line}". If the scale applies, select the scale '
                    f'words, or type the value in full: {canonical(full)}, with "-" for a '
                    "negative value."
                )})  # fmt: skip
                break
        # as admit reads it: brackets make a sign only on a field with a unit, or a cited sign part
        signs = doc.schema.units.get(spec.unit, ([], []))[0] if spec.unit is not None else None
        prefixes = signs if signs is not None else []
        for m in matched:  # the first number with the other sign gets the question
            assert m.value is not None
            negative = (
                m.value < 0
                or bracket_sign(text, m, signs)
                or self._part_sign(doc, body, m, prefixes)
            )
            if (value < 0) != negative:
                out.append({"part": "sign", "text": (
                    f"The value is {_sign(value)}, but the text writes the number "
                    f"{text[m.start : m.end]} as {'negative' if negative else 'positive'}."
                )})  # fmt: skip
                break
        for n, c in enumerate(task["choices"], 1):
            try:
                other = Decimal(c["value"])
            except (InvalidOperation, TypeError):
                continue
            if not other.is_finite() or other == 0 or (other < 0) == (value < 0):
                continue
            if other.copy_abs() in _scaled(value.copy_abs()) or value.copy_abs() in _scaled(
                other.copy_abs()
            ):
                out.append({"part": "sign", "text": (
                    f"The value is {_sign(value)}, but value {n} of the task is "
                    f"{_sign(other)}: {c['shown']}. Read the sign that the field description "
                    "asks for. For a positive amount, select the number without its sign."
                )})  # fmt: skip
        return out

    def check(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Run the ``admit`` call of ``review resolve`` for a correction, and give the outcome
        (§6.2). This writes nothing."""
        tk, doc, slot, task = self._task(body.get("task"))
        verdict = body.get("verdict")
        if tk in doc.labels:
            raise Refused(400, "a calibrate task takes no correction")
        if not isinstance(verdict, str) or verdict not in CORRECTIONS:
            raise Refused(400, "the verdict must be correct or adjust_span")
        candidate = self._candidate(doc, slot, task, body)

        def fail(message: str) -> AnswerError:
            return AnswerError(self.reviewer, None, message)

        decisions = doc.packet.receipt["decisions"]
        try:
            found = _correct(slot, candidate, doc.packet, decisions, _admit_only(doc.packet), fail)
        except AnswerError as exc:
            raise Refused(400, exc.reason) from exc
        d = found.decision
        shown = d.get("value")
        if task["item"] == "number" and isinstance(shown, str):
            value = candidate["evidence"][0]
            with contextlib.suppress(PacketError):
                span = (value["start"], value["end"])
                shown = _number(shown, d.get("unit"), span, doc.units.source)
        return {
            "outcome": d["outcome"],
            "codes": [{"code": c, "text": DESCRIPTIONS.get(c, "")} for c in d["codes"]],
            "keep": [c for c in d["codes"] if c not in INFO],
            "missing": list(d.get("missing") or []),
            "shown": shown,
            "ask": self._ask(doc, slot, task, body, candidate),
        }

    def answer(self, body: Mapping[str, Any]) -> dict[str, Any]:
        """Check an answer against its task (§9 rule 8), then append it to the answer log of the
        reviewer. A correction counts only when the gate does not reject it and the person kept
        each code that is not informational (§6.2)."""
        from ..store import StoreError, reviewer_key

        tk, doc, slot, task = self._task(body.get("task"))
        verdict = body.get("verdict")
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            raise Refused(400, "the verdict is not an answer verdict")
        if tk in doc.labels and verdict in CORRECTIONS:
            raise Refused(400, "a calibrate task takes no correction")
        candidate = None
        kept = body.get("codes_kept") or []
        for name in ("keys", "ms"):
            if type(body.get(name)) is int and body[name] >= _LIMIT:
                raise Refused(400, f"{name} must be less than 2^31")
        if verdict in CORRECTIONS:
            candidate = self._candidate(doc, slot, task, body)
        record: dict[str, Any] = {
            "format": "answer@1",
            "task": tk,
            "reviewer": self.reviewer,
            "verdict": verdict,
            "decision": body.get("decision"),
            "candidate": candidate,
            "codes_kept": kept,
            "statements": None,
            "nodes": None,
            "reason_seen": body.get("reason_seen"),
            "keys": body.get("keys"),
            "ms": body.get("ms"),
            "time": self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if tk in doc.labels or verdict == "wrong":  # §5.3: answer@2
            record["format"] = "answer@2"
            record["field_keys"] = body.get("field_keys")
        decisions = doc.packet.receipt["decisions"]
        try:
            checked = _check(self.reviewer, record, doc.by_key, doc.schema, doc.ids,
                             chained=False, labels=doc.labels)  # fmt: skip
            if checked.answer is None:
                read = _read(checked, doc.schema, doc.packet, decisions,
                             _admit_only(doc.packet), {})  # fmt: skip
                assert read.correction is not None
                d = read.correction.decision
                extra = [c for c in kept if c not in d["codes"]]
                if extra:
                    raise Refused(400, "the correction has no code " + ", ".join(extra))
                if d["outcome"] == "rejected":
                    raise Refused(409, "the gate rejects this correction: " + ", ".join(d["codes"]))
                if read.target is None:
                    left = [c for c in d["codes"] if c not in INFO and c not in kept]
                    raise Refused(409, "keep each code of the correction: " + ", ".join(left))
        except AnswerError as exc:
            raise Refused(400, f"the answer breaks its task: {exc.reason}") from exc
        if candidate is not None and body.get("parts_seen") is not True:
            ask = self._ask(doc, slot, task, body, candidate)
            if ask:
                words = " ".join(x["text"] for x in ask)
                raise Refused(409, "the parts of the correction do not agree: " + words)
        try:
            self.store.append(("answers", doc.key, reviewer_key(self.reviewer)), record)
        except (StoreError, ValueError) as exc:  # ValueError: a number out of the JSON range
            raise Refused(
                409, f"the answer log cannot take the answer: {_printable(str(exc))}"
            ) from exc
        self._refresh(doc.key)
        return self.queue()


def _near_scale(text: str, tok: Token) -> tuple[int, str] | None:
    """The nearest scale word or currency scale above a number on its page (#496): on its line
    before it, or on one of the ``SCALE_LINES`` lines above it. Its power of ten, and the words
    of its line. This is a question for the person, not a decision of the gate."""
    end = tok.start
    for _ in range(SCALE_LINES + 1):
        start = text.rfind("\n", 0, end) + 1
        page = text.rfind("\f", start, end)
        start = max(start, page + 1)
        power = item_scale(text, start, end)
        if power is not None:
            line = normalize_ws(text[start:end]).strip()
            return power, line if len(line) <= 80 else line[:77] + "..."
        if page >= 0 or start == 0:
            return None
        end = start - 1
    return None


def _scaled(amount: Decimal) -> set[Decimal]:
    """``amount`` at each scale that the reader knows, and not scaled."""
    return {amount.scaleb(p, _EXACT) for p in scale_powers()}


def _sign(value: Decimal) -> str:
    return "negative" if value < 0 else "positive"


def _inert(source: str) -> str:
    """``source`` with no meta refresh and no link, so that the frame cannot go to another host.
    This changes each http-equiv and href attribute name, also in the text."""
    return _HREF.sub("data-href", _EQUIV.sub("data-equiv", source))


def _marked(source: str, value: str | None) -> tuple[str, bool, int]:
    """``source`` with a box around ``value`` when the value occurs one time and not inside a
    tag. Return the HTML, whether it has the box, and the count of occurrences."""
    if value is None or not value.strip():
        return source, False, 0
    found = list(quote_pattern(value).finditer(source))
    if len(found) != 1:
        return source, False, len(found)
    m = found[0]
    at = m.start()
    if source.rfind("<", 0, at) > source.rfind(">", 0, at):
        return source, False, 1  # inside a tag: a box there would change the tag
    if source.rfind("<!--", 0, at) > source.rfind("-->", 0, at):
        return source, False, 1  # inside a comment
    low = source[:at].lower()
    for name in _RAW:
        opened = [o.start() for o in re.finditer(rf"<{name}[\t\n\f\r />]", low)]
        if opened and opened[-1] > low.rfind(f"</{name}"):
            return source, False, 1  # inside an element whose text is not markup
    return source[: m.start()] + _MARK + m.group() + "</mark>" + source[m.end() :], True, 1


def server(review: Review, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """The review server on 127.0.0.1 and its start URL, which holds the token after #."""
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    host = ""  # 127.0.0.1 and the bound port, set once the server binds

    class Handler(BaseHTTPRequestHandler):
        timeout = 30  # a client that sends less than its Content-Length holds a thread no longer

        def send(
            self, body: str, kind: str = "application/json", code: int = 200, csp: str = CSP
        ) -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Security-Policy", csp)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def refuse(self, code: int, why: str) -> None:
            self.close_connection = True
            self.send(json.dumps({"error": why}), code=code)

        def allowed(self, api: bool) -> bool:
            """Refuse a request for another host, and an API request without the token."""
            if self.headers.get("Host") != host:
                self.refuse(421, "the Host header must be 127.0.0.1 and the port")
                return False
            sent = self.headers.get(TOKEN_HEADER, "")
            if api and not hmac.compare_digest(sent.encode(), token.encode()):
                self.refuse(403, "open the start URL with its token")
                return False
            return True

        def run(self, call: Callable[[], Any]) -> None:
            try:
                with lock:
                    result = call()
            except Refused as exc:
                self.refuse(exc.code, exc.message)
                return
            except Exception:  # never send a trace with store data to the page
                self.refuse(500, "the server failed on this request")
                return
            self.send(json.dumps(result))

        def do_GET(self) -> None:
            path = self.path
            if path in STATIC:
                if self.allowed(api=False):
                    name, kind = STATIC[path]
                    self.send(files(__package__).joinpath(name).read_text("utf-8"), kind)
                return
            ticket = _TICKET.fullmatch(path)
            if ticket is not None:  # a frame cannot send the header; its ticket works one time
                if not self.allowed(api=False):
                    return
                with lock:
                    page = review.frame(ticket.group(1))
                if page is None:
                    self.refuse(404, "the frame ticket is not valid")
                else:
                    self.send(page, "text/html", csp=frame_csp(f"http://{host}"))
                return
            if not self.allowed(api=True):
                return
            if path == "/api/queue":
                self.run(review.queue)
                return
            found = _API.fullmatch(path)
            if found is None:
                self.refuse(404, "no such path")
            elif not _KEY.fullmatch(found.group(2)):
                self.refuse(400, "the path does not end in a store key")
            elif found.group(1) == "task":
                self.run(lambda: review.view(found.group(2)))
            else:
                self.run(lambda: review.reason(found.group(2)))

        def do_POST(self) -> None:
            if not self.allowed(api=True):
                return
            kind = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if kind != "application/json":
                self.refuse(415, "the body must be application/json")
                return
            length = self.headers.get("Content-Length", "")
            # only digits: int() also takes "+5", "1_0" and spaces
            if not (length.isascii() and length.isdigit()):
                self.refuse(411, "the request needs a Content-Length")
                return
            size = int(length)
            if size > MAX_BODY:
                self.refuse(413, f"the body must be {MAX_BODY} bytes at most")
                return
            try:
                body = json.loads(self.rfile.read(size))
            except (ValueError, RecursionError):  # deep nesting fits in 64 KiB
                self.refuse(400, "the body is not JSON")
                return
            if not isinstance(body, dict):
                self.refuse(400, "the body must be a JSON object")
            elif self.path == "/api/check":
                self.run(lambda: review.check(body))
            elif self.path == "/api/answer":
                self.run(lambda: review.answer(body))
            else:
                self.refuse(404, "no such path")

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    host = f"127.0.0.1:{httpd.server_port}"
    return httpd, f"http://{host}/#{token}"
