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
- ``evidence``: ``char_interval`` converted to UTF-8 byte offsets, quoting ``extraction_text``.
  An extraction LangExtract could not align has no evidence and is rejected ``NO_EVIDENCE``.

``alignment_status`` and ``extraction_class`` are kept on the candidate for the report; the
checks ignore them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..admit import admit
from ..canonical import Offsets, is_nfc
from ..model import PacketError, Policy, Receipt, Schema


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _status(raw: Any) -> str | None:
    if raw is None:
        return None
    return str(getattr(raw, "value", raw))  # an AlignmentStatus enum or its string value


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


def to_candidates(
    document: Any,
    *,
    fields: Mapping[str, str] | None = None,
    value_attribute: str = "value",
    unit_attribute: str = "unit",
    key_attribute: str = "key",
) -> list[dict[str, Any]]:
    """One groundgate candidate per extraction in a LangExtract ``AnnotatedDocument``."""
    text = document_text(document)
    offsets = Offsets(text)
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
        interval = _get(x, "char_interval")
        start, end = _get(interval, "start_pos"), _get(interval, "end_pos")
        if isinstance(start, int) and isinstance(end, int):
            if not 0 <= start <= end <= len(text):
                raise PacketError(f"extraction {i} has a char_interval outside the document text")
            cand["evidence"] = {
                "start": offsets.to_bytes(start),
                "end": offsets.to_bytes(end),
                "text": quote,
            }
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
