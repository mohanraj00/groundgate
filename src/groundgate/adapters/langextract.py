"""Admit LangExtract results.

LangExtract checks that each ``extraction_text`` is found in the source and records where
(``char_interval``). It does not check the typed value you asked for in the attributes. This
adapter turns each extraction into a groundgate candidate so the value and unit are checked at
that location::

    result = lx.extract(text_or_documents=text, prompt_description=..., examples=...)
    receipt = admit_document(result, schema)

Works on ``lx.data.AnnotatedDocument`` objects and on the dicts LangExtract writes to JSONL
(``lx.io.save_annotated_documents``). LangExtract itself is not imported.

Mapping, per extraction:

- ``field``: ``extraction_class``, renamed through ``fields`` when given;
- ``value``: the ``value`` attribute, or ``extraction_text`` when there is none;
- ``unit``: the ``unit`` attribute, when present;
- ``key``: the ``key`` attribute, when present, for a keyed field;
- ``evidence``: a list of evidence items. The first is the value item: ``char_interval``
  converted to UTF-8 byte offsets, quoting ``extraction_text``. Then one quote for each of the
  attributes ``sign_text``, ``scale_text``, ``unit_text``, ``key_text`` and ``field_text`` that
  holds text, with the role ``sign``, ``scale``, ``unit``, ``key`` or ``field``. A quote has no
  offsets: groundgate finds it near the value. Then the outside items: one ``external`` item from
  ``source_url``, ``source_retrieved`` and ``source_quote`` when all three hold text, and one
  ``knowledge`` item from ``knowledge``.

An extraction LangExtract could not align has no value item. With outside items, its evidence is
those items, and groundgate takes the outside path. Without them, it has no evidence and is
rejected ``NO_EVIDENCE``. ``attributes`` renames the evidence attributes, for example
``{"key_text": "row_label"}``.

``alignment_status`` and ``extraction_class`` are kept on the candidate for the report; the
checks ignore them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..admit import admit
from ..canonical import Offsets, is_nfc
from ..model import PacketError, Policy, Receipt, Schema

ROLES = {
    "sign": "sign_text",
    "scale": "scale_text",
    "unit": "unit_text",
    "key": "key_text",
    "field": "field_text",
}
"""The role of each quote item, and the attribute that gives its text."""

ATTRIBUTES = (*ROLES.values(), "source_url", "source_quote", "source_retrieved", "knowledge")
"""The attributes that become evidence items. ``attributes=`` renames them."""


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _status(raw: Any) -> str | None:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))  # an AlignmentStatus enum or its string value


def _text(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and raw.strip() else None


def document_text(document: Any) -> str:
    text = _get(document, "text")
    if not isinstance(text, str):
        raise PacketError("the LangExtract document has no text")
    if not is_nfc(text):
        raise PacketError(
            "the LangExtract document text is not NFC; normalise it before calling lx.extract "
            "(unicodedata.normalize('NFC', text)) so offsets line up"
        )
    return text


def _names(attributes: Mapping[str, str] | None) -> dict[str, str]:
    """Each evidence attribute's name in the app, from our name."""
    unknown = sorted(set(attributes or {}) - set(ATTRIBUTES))
    if unknown:
        raise ValueError(f"unknown evidence attributes {unknown}; use names from {ATTRIBUTES}")
    return {name: (attributes or {}).get(name, name) for name in ATTRIBUTES}


def _role_items(attrs: Mapping[str, Any], names: Mapping[str, str]) -> list[dict[str, Any]]:
    """One quote for each role attribute that holds text. groundgate finds it."""
    out = []
    for role, name in ROLES.items():
        text = _text(attrs.get(names[name]))
        if text is not None:
            out.append({"role": role, "text": text})
    return out


def _outside_items(attrs: Mapping[str, Any], names: Mapping[str, str]) -> list[dict[str, Any]]:
    """The external item, when the URL, the date and the quote all hold text, and the knowledge
    item."""
    out: list[dict[str, Any]] = []
    url, retrieved, quote = (
        _text(attrs.get(names[n])) for n in ("source_url", "source_retrieved", "source_quote")
    )
    if url is not None and retrieved is not None and quote is not None:
        out.append({"source": "external", "url": url, "retrieved": retrieved, "text": quote})
    knowledge = _text(attrs.get(names["knowledge"]))
    if knowledge is not None:
        out.append({"source": "knowledge", "text": knowledge})
    return out


def to_candidates(
    document: Any,
    *,
    fields: Mapping[str, str] | None = None,
    value_attribute: str = "value",
    unit_attribute: str = "unit",
    key_attribute: str = "key",
    attributes: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """One groundgate candidate per extraction in a LangExtract ``AnnotatedDocument``.
    ``attributes`` maps an evidence attribute in ``ATTRIBUTES`` to the name the app gives it."""
    text = document_text(document)
    offsets = Offsets(text)
    names = _names(attributes)
    out = []
    for i, x in enumerate(_get(document, "extractions") or []):
        cls = _get(x, "extraction_class")
        quote = _get(x, "extraction_text")
        attrs = _get(x, "attributes") or {}
        cand: dict[str, Any] = {
            "id": i,
            "field": (fields or {}).get(cls, cls),
            "value": attrs.get(value_attribute, quote),
            "extraction_class": cls,
            "alignment_status": _status(_get(x, "alignment_status")),
        }
        if attrs.get(unit_attribute) is not None:
            cand["unit"] = attrs[unit_attribute]
        if attrs.get(key_attribute) is not None:
            cand["key"] = attrs[key_attribute]
        outside = _outside_items(attrs, names)
        interval = _get(x, "char_interval")
        start, end = _get(interval, "start_pos"), _get(interval, "end_pos")
        if isinstance(start, int) and isinstance(end, int):
            if not 0 <= start <= end <= len(text):
                raise PacketError(f"extraction {i} has a char_interval outside the document text")
            value = {"start": offsets.to_bytes(start), "end": offsets.to_bytes(end), "text": quote}
            cand["evidence"] = [value, *_role_items(attrs, names), *outside]
        elif outside:  # not aligned: only the outside items can support the value
            cand["evidence"] = outside
        out.append(cand)
    return out


def admit_document(
    document: Any,
    schema: Schema | Mapping[str, Any],
    policy: Policy | Mapping[str, Any] | None = None,
    *,
    document_id: str | None = None,
    **options: Any,
) -> Receipt:
    """Admit every extraction in a LangExtract document. ``options`` go to ``to_candidates``.

    ``document_id`` defaults to the id the caller gave LangExtract. An id LangExtract generated
    itself is random, so it is left out to keep the receipt reproducible.
    """
    if document_id is None:
        if isinstance(document, Mapping):
            given = document.get("document_id")
        else:  # reading the property would make LangExtract invent a random id
            given = vars(document).get("_document_id") if hasattr(document, "__dict__") else None
        document_id = given if isinstance(given, str) else None
    return admit(
        document_text(document),
        schema,
        to_candidates(document, **options),
        policy,
        document_id=document_id,
    )
