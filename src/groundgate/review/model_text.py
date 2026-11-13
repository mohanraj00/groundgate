"""The model text input of review and its item kind (docs/design/review.md §7, #531).

An app gives a model text and its statements, each with the spans of the document that it
cites. A person says for each statement if the source supports it. A statement is not a
candidate: nothing here gives the model text to ``admit``.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from ..model import PacketError, Schema
from ..read.layout import Layout

FORMAT = "model-text@1"
TEMPLATE = "model_text@1"
MAX_TEXT = 64 << 10  # bytes of the model text as UTF-8
MAX_STATEMENTS = 200
MAX_CITES = 8  # the cited spans of one statement
QUOTE_CHARS = 600  # the characters of a cited span that the page shows
STATEMENT_VERDICTS = ("supported", "unsupported", "unsure")
_MEMBERS = frozenset({"format", "packet", "name", "text", "statements"})
_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_KEY = re.compile(r"sha256:[0-9a-f]{64}\Z")
_WORD = re.compile(r"\w+")


def _fail(message: str) -> PacketError:
    return PacketError(f"model text: {message}")


def _span(obj: object, data: bytes, what: str) -> tuple[int, int]:
    """A span of ``data`` in UTF-8 bytes: not empty, inside the text, and with each end at the
    start of a character."""
    if not isinstance(obj, Mapping) or not {"start", "end"} <= set(obj):
        raise _fail(f"{what} needs a start and an end")
    start, end = obj["start"], obj["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(data):
        raise _fail(f"{what} is not a span of the text")
    for i in (start, end):
        if i < len(data) and data[i] & 0xC0 == 0x80:
            raise _fail(f"{what} starts or ends inside a character")
    return start, end


def check_model_text(obj: object, packet_key: str, document: str, schema: Schema) -> dict[str, Any]:
    """Check a ``model-text@1`` object against the packet that it names, and give it with
    only the members of the format. Raises ``PacketError``."""
    if not isinstance(obj, Mapping) or set(obj) != _MEMBERS:
        raise _fail("the object must have the members format, packet, name, text and statements")
    if obj["format"] != FORMAT:
        raise _fail(f"the format must be {FORMAT}")
    if obj["packet"] != packet_key:
        raise _fail("the object names another packet")
    name, text, statements = obj["name"], obj["text"], obj["statements"]
    if not isinstance(name, str) or not _NAME.match(name):
        raise _fail("the name must have the form of a field name")
    if name in schema.fields:
        raise _fail(f"the name {name!r} is a field of the schema")
    if not isinstance(text, str) or not unicodedata.is_normalized("NFC", text):
        raise _fail("the text must be a string in Unicode NFC")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise _fail("the text is not valid Unicode text") from None
    if not 0 < len(data) <= MAX_TEXT:
        raise _fail(f"the text must have 1 to {MAX_TEXT} bytes")
    if not isinstance(statements, list) or not 0 < len(statements) <= MAX_STATEMENTS:
        raise _fail(f"statements must be a list of 1 to {MAX_STATEMENTS} statements")
    source = document.encode("utf-8")
    out = []
    last = 0
    for n, s in enumerate(statements):
        if not isinstance(s, Mapping) or set(s) != {"start", "end", "cites"}:
            raise _fail(f"statement {n} must have the members start, end and cites")
        start, end = _span(s, data, f"statement {n}")
        if start < last:
            raise _fail(f"statement {n} starts before the end of the statement before it")
        last = end
        cites = s["cites"]
        if not isinstance(cites, list) or len(cites) > MAX_CITES:
            raise _fail(f"the cites of statement {n} must be a list of at most {MAX_CITES} spans")
        spans = []
        for c in cites:
            if not isinstance(c, Mapping) or set(c) != {"start", "end"}:
                raise _fail(f"a cite of statement {n} must have only a start and an end")
            a, b = _span(c, source, f"a cite of statement {n}")
            spans.append({"start": a, "end": b})
        out.append({"start": start, "end": end, "cites": spans})
    return {"format": FORMAT, "packet": packet_key, "name": name, "text": text, "statements": out}


def model_text_task(
    packet_key: str, key: str, checked: Mapping[str, Any], layout: Layout | None
) -> dict[str, Any]:
    """The ``task@1`` object of a checked model text whose store key is ``key``. The task
    holds offsets and no model text."""
    from .tasks import _places  # here, because tasks imports this module

    cites = [{"evidence": c} for s in checked["statements"] for c in s["cites"]]
    name = checked["name"]
    return {
        "format": "task@1",
        "packet": packet_key,
        "slot": {"field": name, "key": None, "decisions": []},
        "item": "model_text",
        "mode": "review",
        "template": TEMPLATE,
        "question": f"Does the source support each statement of {name.replace('_', ' ')}?",
        "parts": ["statement"],
        "codes": [],
        "choices": [],
        "places": _places(cites, layout),
        "model_text": {"key": key, "statements": len(checked["statements"])},
    }


def all_model_texts(store: Any) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    """Each ``model-text@1`` object of ``store`` with its key, for each packet key that an
    object names, in key order. The keys come from the list of store objects, never from an
    object. An object that cannot be read, or that is not such an object, is left out. A
    store that cannot list its objects gives none."""
    from ..store import StoreError, key

    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    if not hasattr(store, "object_keys"):  # only a folder store lists its objects
        return out
    keys, _ = store.object_keys()
    for k in sorted(keys):
        try:
            data = store.object_bytes(k)
        except StoreError:
            continue
        if key(FORMAT, data) != k:
            continue
        try:
            obj = json.loads(data)
        except (ValueError, RecursionError):
            continue
        if isinstance(obj, dict) and isinstance(obj.get("packet"), str):
            out.setdefault(obj["packet"], []).append((k, obj))
    return out


def stored_model_texts(store: Any, packet_key: str) -> list[tuple[str, dict[str, Any]]]:
    """Each ``model-text@1`` object of ``store`` that names ``packet_key``, with its key."""
    return all_model_texts(store).get(packet_key, [])


def differing(statement: str, cited: list[str]) -> list[tuple[int, int]]:
    """The words of ``statement`` that no cited text has, as spans of ``statement`` in code
    points. A word is a run of letters, digits and ``_``, and case does not count. With no
    cited text, no word has a mark."""
    if not cited:
        return []
    known = {w.casefold() for text in cited for w in _WORD.findall(text)}
    return [m.span() for m in _WORD.finditer(statement) if m.group().casefold() not in known]


def _u16(text: str, cp: int) -> int:
    return len(text[:cp].encode("utf-16-le")) // 2


def statement_views(checked: Mapping[str, Any], document: str) -> list[dict[str, Any]]:
    """Each statement for the page: its text, the start of each cited span of the document
    (at most ``QUOTE_CHARS`` characters), and the words that differ."""
    data = checked["text"].encode("utf-8")
    source = document.encode("utf-8")
    out = []
    for n, s in enumerate(checked["statements"]):
        text = data[s["start"] : s["end"]].decode("utf-8")
        cited = [source[c["start"] : c["end"]].decode("utf-8") for c in s["cites"]]
        out.append(
            {
                "n": n,
                "text": text,
                # in UTF-16 code units, as the page counts a string
                "marks": [[_u16(text, a), _u16(text, b)] for a, b in differing(text, cited)],
                "cites": [c[:QUOTE_CHARS] for c in cited],
            }
        )
    return out
