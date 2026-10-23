"""Readings and packets in a store (docs/design/store.md §5, §9).

``put_reading`` reads a file and writes the source, the text, the layout and a ``reading@1``
object. ``admit_packet`` runs ``admit`` and writes the inputs, the receipt and a ``packet@1``
object. ``load_packet`` gets each input of a packet back, so that ``verify`` and ``report`` can
decide again from the packet key alone.

The store data is untrusted. ``load_packet`` calculates each key again, parses each JSON object
as canonical JSON, and checks the packet members before it gets an object. An object that is
not in the store raises ``InputGone``: "input deleted" with the key, the time and the reason of
the deleted log, or "input missing" when the log has no record of the key.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..admit import admit
from ..canonical import SPEC_VERSION, jcs
from ..escape import escape
from ..model import PacketError, Receipt
from . import KEY, NotFound, Store, StoreError, _canonical, key

__all__ = [
    "InputGone",
    "Packet",
    "admit_packet",
    "load_packet",
    "load_reading",
    "put_reading",
]

READER = "groundgate.read"
_PACKET = (
    "candidates",
    "document",
    "format",
    "judgments",
    "packs",
    "policy",
    "reading",
    "receipt",
    "references",
    "run",
    "schema",
    "spec",
)
_READING = ("document", "format", "layout", "options", "reader", "source", "text")


class InputGone(StoreError):
    """An object that a packet or a reading names is not in the store. ``deleted`` is the record
    of the deleted log for the key, or ``None`` when the log has no record: then the input is
    missing. This is not a mismatch: ``verify`` cannot decide again without the input."""

    def __init__(self, kind: str, key: str, deleted: Mapping[str, Any] | None) -> None:
        self.kind = kind
        self.key = key
        self.deleted = deleted
        if deleted is None:
            message = f"input missing: the {kind} object {key} is not in the store"
        else:
            message = (
                f"input deleted: the {kind} object {key} was deleted at "
                f"{_printable(deleted.get('time'))}, reason: {_printable(deleted.get('reason'))}"
            )
        super().__init__(message)


@dataclass(frozen=True)
class Packet:
    """The inputs of one ``admit`` call, from the store. The members are the arguments of
    ``verify`` and ``render``. ``layout`` is the layout of the reading as a dict, if the packet
    names a reading of a PDF and ``load_packet`` got it."""

    key: str
    receipt: dict[str, Any]
    text: str
    schema: Any
    candidates: Any
    policy: Any
    judgments: Any
    references: list[Any] | None
    document_source: str | None
    packs: list[Any]
    reading: str | None
    layout: dict[str, Any] | None = None

    def inputs(self) -> dict[str, Any]:
        """The keyword arguments of ``verify`` and ``render`` after the first four."""
        return {
            "policy": self.policy,
            "judgments": self.judgments,
            "references": self.references,
            "document_source": self.document_source,
            "packs": self.packs,
        }


def printable(value: object, limit: int | None = 200) -> str:
    """A value from the store as text with no control character, for a message. With a
    ``limit``, a longer text is cut."""
    text = value if isinstance(value, str) else repr(value)
    text = escape(text)
    return text if limit is None or len(text) <= limit else text[: limit - 3] + "..."


_printable = printable


def _json(value: Any, what: str) -> bytes:
    try:
        return jcs(value).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise PacketError(f"the {what} has no canonical JSON form: {exc}") from exc


def _same(a: Any, b: Any) -> bool:
    """``a`` and ``b`` are equal and have the same JSON types. A float 5.0 is not the integer
    5, and a tuple is not a list."""
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and a.keys() == b.keys()
            and all(_same(v, b[k]) for k, v in a.items())
        )
    if isinstance(a, list):
        return (
            isinstance(b, list)
            and len(a) == len(b)
            and all(_same(x, y) for x, y in zip(a, b, strict=True))
        )
    return type(a) is type(b) and a == b


def _gone(store: Store, kind: str, k: str) -> InputGone:
    record = None
    for entry in store.read(("deleted",)):
        if entry.get("key") == k:
            record = entry
    return InputGone(kind, k, record)


def _get(store: Store, kind: str, k: str) -> bytes:
    """The bytes of an object, with its key calculated again."""
    try:
        data = store.get(kind, k)
    except NotFound:
        raise _gone(store, kind, k) from None
    if not isinstance(data, bytes) or key(kind, data) != k:
        raise StoreError(f"the {kind} object {k} does not match its key")
    return data


def _get_json(store: Store, kind: str, k: str) -> Any:
    raw = _get(store, kind, k)
    try:
        return _canonical(raw.decode("utf-8"), f"the {kind} object {k}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise StoreError(str(exc)) from exc


def _key_or_none(obj: Mapping[str, Any], name: str, what: str) -> str | None:
    value = obj[name]
    if value is not None and not (isinstance(value, str) and KEY.fullmatch(value)):
        raise StoreError(f"the {what} member {name} is not a store key or null")
    return value


def _key_list(obj: Mapping[str, Any], name: str, what: str) -> list[str]:
    value = obj[name]
    if not isinstance(value, list) or not all(
        isinstance(v, str) and KEY.fullmatch(v) for v in value
    ):
        raise StoreError(f"the {what} member {name} is not a list of store keys")
    return value


def _members(obj: object, names: tuple[str, ...], kind: str, k: str) -> Mapping[str, Any]:
    if not isinstance(obj, dict) or sorted(obj) != list(names):
        raise StoreError(f"the {kind} object {k} does not have the members of {kind}")
    if obj["format"] != kind:
        raise StoreError(f"the {kind} object {k} has the format {_printable(obj['format'])}")
    return obj


# Readings


def put_reading(
    store: Store, path: str | Path, pages: Sequence[int] | None = None
) -> tuple[str, Any]:
    """Read the file at ``path`` as ``groundgate read`` does, and write the source, the text,
    the layout (PDF only) and a ``reading@1`` object. Return the reading key and the result of
    ``read``. The file must be a regular file. ``put_reading`` reads its bytes one time and
    gives them to ``read``, so ``source@1`` and ``text@1`` come from the same bytes.

    If the file is a PDF and the store has a reading cache (``views/readings.json``, from
    ``store rebuild``) with one reading of the same source, reader version and options,
    ``put_reading`` uses that reading and does not run ``read``. Only a PDF reading has a
    layout, so the reading shows its format. A reading of other files does not name the format
    (text, HTML or XML), so ``put_reading`` always reads those files. A new reader version
    misses the cache. On a cache hit, the warnings come from the stored text and layout, so a
    warning about words drawn outside a PDF page shows only on the read that wrote the
    reading."""
    from .. import __version__
    from ..read import ReadError, read

    path = Path(path)
    if not path.is_file():
        raise ReadError(f"{path} is not a regular file")
    source = path.read_bytes()
    want = {
        "source": key("source@1", source),
        "reader": {"name": READER, "version": __version__},
        "options": {"pages": None if pages is None else list(pages)},
    }
    hit = _cached_reading(store, path, want)
    if hit is not None:
        store.put("source@1", source)
        return hit
    doc = read(path, pages=pages, data=source)
    store.put("source@1", source)
    layout = None
    if doc.layout is not None:
        layout = store.put("layout@1", _json(doc.layout.to_dict(), "layout"))
    reading = {
        "format": "reading@1",
        **want,
        "text": store.put("text@1", doc.text.encode("utf-8")),
        "layout": layout,
        "document": None,
    }
    return store.put("reading@1", _json(reading, "reading")), doc


def _cached_reading(store: Store, path: Path, want: dict[str, Any]) -> tuple[str, Any] | None:
    """The reading key and the result of ``read`` from the reading cache, or ``None`` on a miss.
    The cache and the objects are untrusted. Each value that does not agree with ``want`` is a
    miss, and so is a row with more than one reading. Only a PDF can hit."""
    view = getattr(store, "read_view", None)
    if view is None or path.suffix.lower() != ".pdf":
        return None
    try:
        cache = json.loads(view("readings.json"))
        rows = cache["readings"] if cache.get("format") == "reading-cache@1" else []
        name = jcs(want)
        for row in rows:
            if jcs({m: row.get(m) for m in want}) != name:
                continue
            found = row.get("readings")
            if not isinstance(found, list) or len(found) != 1 or not isinstance(found[0], str):
                return None
            return _stored_reading(store, found[0], name)
    except (StoreError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None  # a deep nest in the view or an object is a miss too
    return None


def _stored_reading(store: Store, k: str, name: str) -> tuple[str, Any] | None:
    """The reading of key ``k`` as the result of ``read``, if its members give ``name``."""
    from ..canonical import digest, is_nfc
    from ..read import Extracted, Layout

    obj = load_reading(store, k)
    if jcs({m: obj[m] for m in ("source", "reader", "options")}) != name:
        return None
    if obj["document"] is not None:
        return None
    text = store.get("text@1", obj["text"]).decode("utf-8")
    if not is_nfc(text):
        return None
    if obj["layout"] is None:  # a reading of text, HTML or XML
        return None
    layout = Layout.from_dict(_get_json(store, "layout@1", obj["layout"]))
    if layout.document_sha256 != digest("document", {"text": text}):
        return None
    from ..read.pdf import layout_warnings

    return k, Extracted(text, layout, tuple(layout_warnings(layout.pages, obj["options"]["pages"])))


def load_reading(store: Store, k: str) -> dict[str, Any]:
    """The ``reading@1`` object of key ``k``, with its members checked."""
    obj = _members(_get_json(store, "reading@1", k), _READING, "reading@1", k)
    for name in ("source", "text"):
        if _key_or_none(obj, name, "reading") is None:
            raise StoreError(f"the reading member {name} is not a store key")
    _key_or_none(obj, "layout", "reading")
    return dict(obj)


# Packets


def admit_packet(
    store: Store,
    text: str,
    schema: Mapping[str, Any],
    candidates: Sequence[object],
    policy: Mapping[str, Any] | None = None,
    document_id: str | None = None,
    judgments: Sequence[object] | None = None,
    *,
    references: Sequence[object] | None = None,
    document_source: str | None = None,
    packs: Sequence[object] = (),
    reading: str | None = None,
) -> tuple[str, Receipt]:
    """Run ``admit``, then write the text, the schema, the policy, each reference, each pack,
    the candidates, the judgments, the receipt and a ``packet@1`` object. Return the packet key
    and the receipt. The same inputs give the same packet key.

    The arguments are the arguments of ``admit``, with ``schema`` and ``policy`` as dicts and
    ``packs`` as the packs of the app. ``reading`` is the key of a reading of the same text.
    The store keeps canonical JSON, where the number 5.0 is 5. If that change gives another
    receipt, ``admit_packet`` raises ``PacketError`` and writes nothing, because ``verify``
    from the store would then fail."""
    for value, what in ((schema, "schema"), (policy, "policy")):
        if value is not None and not isinstance(value, Mapping):
            raise PacketError(f"give the {what} as a dict to store it")
    receipt = admit(
        text,
        schema,
        candidates,
        policy,
        document_id,
        judgments,
        references=references,
        document_source=document_source,
        packs=packs,
    )
    given: dict[str, Any] = {
        "schema": schema,
        "policy": policy,
        "references": list(references) if references is not None else [],
        "packs": list(packs),
        "candidates": candidates,
        "judgments": judgments,
        "document_id": document_id,
    }
    back = json.loads(_json(given, "inputs"))
    if not _same(given, back):
        again = admit(
            text,
            back["schema"],
            back["candidates"],
            back["policy"],
            back["document_id"],
            back["judgments"],
            references=None if references is None else back["references"],
            document_source=document_source,
            packs=back["packs"],
        )
        if again.to_dict() != receipt.to_dict():
            raise PacketError(
                "the store keeps canonical JSON, and in canonical JSON the inputs give another "
                "receipt. Write each whole number with no fraction (5, not 5.0)."
            )
    if reading is not None:
        if not isinstance(reading, str) or not KEY.fullmatch(reading):
            raise PacketError(f"{_printable(reading)} is not a store key")
        text_key = key("text@1", text.encode("utf-8"))
        if load_reading(store, reading)["text"] != text_key:
            raise PacketError(f"the reading {reading} is of another text")
    return _put_packet(store, text, given, receipt, document_source, reading, None), receipt


def _put_packet(
    store: Store,
    text: str,
    given: Mapping[str, Any],
    receipt: Receipt,
    document_source: str | None,
    reading: str | None,
    run: str | None,
) -> str:
    """Write the inputs in ``given``, the receipt and a ``packet@1`` object, and return the
    packet key. The caller checked that these inputs give ``receipt``."""

    def put(kind: str, value: Any) -> str:
        return store.put(kind, _json(value, kind))

    policy, judgments = given["policy"], given["judgments"]
    packet = {
        "format": "packet@1",
        "spec": SPEC_VERSION,
        "document": {
            "id": given["document_id"],
            "source": document_source,
            "text": store.put("text@1", text.encode("utf-8")),
        },
        "reading": reading,
        "schema": put("schema@1", given["schema"]),
        "policy": None if policy is None else put("policy@1", policy),
        "references": [put("reference@1", r) for r in given["references"]],
        "packs": [put("pack@1", p) for p in given["packs"]],
        "candidates": put("candidates@1", given["candidates"]),
        "judgments": None if judgments is None else put("judgments@1", judgments),
        "receipt": put("receipt@1", receipt.to_dict()),
        "run": run,
    }
    return put("packet@1", packet)


def load_packet(store: Store, k: str, *, layout: bool = False) -> Packet:
    """Get the packet of key ``k`` and each input that it names. With ``layout``, also get the
    layout of its reading. The packet member ``spec`` must be the ``groundgate`` member of the
    receipt, and ``verify`` checks that spec version against its own. An object that is not in
    the store raises ``InputGone``, and data that does not match its key or its format raises
    ``StoreError``."""
    if not isinstance(k, str) or not KEY.fullmatch(k):
        raise ValueError(f"{_printable(k)} is not a store key")
    obj = _members(_get_json(store, "packet@1", k), _PACKET, "packet@1", k)
    document = obj["document"]
    if not isinstance(document, dict) or sorted(document) != ["id", "source", "text"]:
        raise StoreError("the packet member document does not have the members id, source, text")
    if document["source"] is not None and not isinstance(document["source"], str):
        raise StoreError("the packet member document.source is not a string or null")
    text_key = _key_or_none(document, "text", "packet document")
    if text_key is None:
        raise StoreError("the packet member document.text is not a store key")
    for name in ("schema", "candidates", "receipt"):
        if _key_or_none(obj, name, "packet") is None:
            raise StoreError(f"the packet member {name} is not a store key")
    for name in ("reading", "policy", "judgments", "run"):
        _key_or_none(obj, name, "packet")
    references = _key_list(obj, "references", "packet")
    packs = _key_list(obj, "packs", "packet")
    if not isinstance(obj["spec"], str):
        raise StoreError("the packet member spec is not a string")

    receipt = _get_json(store, "receipt@1", obj["receipt"])
    if not isinstance(receipt, dict):
        raise StoreError(f"the receipt@1 object {obj['receipt']} is not a JSON object")
    if receipt.get("groundgate") != obj["spec"]:
        raise StoreError("the packet and its receipt name different spec versions")
    named = receipt.get("document")
    if not isinstance(named, dict) or named.get("id") != document["id"]:
        raise StoreError("the packet and its receipt name different document ids")
    try:
        text = _get(store, "text@1", text_key).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreError(f"the text@1 object {text_key} is not UTF-8") from exc
    layout_dict = None
    if layout and obj["reading"] is not None:
        found = load_reading(store, obj["reading"])
        if found["text"] != text_key:
            raise StoreError(f"the reading {obj['reading']} is of another text")
        if found["layout"] is not None:
            layout_dict = _get_json(store, "layout@1", found["layout"])
    return Packet(
        key=k,
        receipt=receipt,
        text=text,
        schema=_get_json(store, "schema@1", obj["schema"]),
        candidates=_get_json(store, "candidates@1", obj["candidates"]),
        policy=None if obj["policy"] is None else _get_json(store, "policy@1", obj["policy"]),
        judgments=(
            None if obj["judgments"] is None else _get_json(store, "judgments@1", obj["judgments"])
        ),
        references=[_get_json(store, "reference@1", r) for r in references] or None,
        document_source=document["source"],
        packs=[_get_json(store, "pack@1", p) for p in packs],
        reading=obj["reading"],
        layout=layout_dict,
    )
