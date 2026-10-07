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
  An extraction LangExtract could not align has no evidence and is rejected ``NO_EVIDENCE``;
- ``key_evidence``: from the ``key_text`` attribute, when present: the words that name the key,
  such as a heading or a row label. The span is the last occurrence of ``key_text``, not inside a
  longer word, that ends at or before the value: the number token in ``char_interval`` that
  equals ``value``, or the interval's start. When there is none, the span is empty, so
  groundgate flags ``KEY_CITATION_INVALID``.

``alignment_status`` and ``extraction_class`` are kept on the candidate for the report; the
checks ignore them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..admit import admit
from ..canonical import Offsets, is_nfc
from ..model import PacketError, Policy, Receipt, Schema
from ..text import _NOT_ALNUM_AFTER, _NOT_ALNUM_BEFORE, parse_value, quote_pattern, scaled_value
from ..text import tokens as number_tokens


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
    key_text_attribute: str = "key_text",
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
            key_text = attrs.get(key_text_attribute)
            if isinstance(key_text, str) and key_text.strip():
                at = _value_start(text, start, end, cand["value"])
                cand["key_evidence"] = _key_span(text, offsets, key_text, at)
        out.append(cand)
    return out


def _value_start(text: str, start: int, end: int, value: object) -> int:
    """Where groundgate puts a numeric value in the interval: its first number token that equals
    the value, as written or scaled. Else the interval's start, as for a string field."""
    want = parse_value(str(value))
    if want is not None:
        for t in number_tokens(text, start, end):
            if t.value is not None and want in (t.value, scaled_value(text, t)):
                return t.start
    return start


def _key_span(text: str, offsets: Offsets, key_text: str, at: int) -> dict[str, Any]:
    """The last occurrence of ``key_text`` that ends at or before ``at`` and is not part of a
    longer word, in UTF-8 bytes. With none, an empty span at ``at``: groundgate reads it as not
    valid and flags the citation."""
    s = e = at
    whole = re.compile(_NOT_ALNUM_BEFORE + quote_pattern(key_text).pattern + _NOT_ALNUM_AFTER)
    pos = 0
    # search the whole text, so the word check sees the character after a match at ``at``
    while (m := whole.search(text, pos)) is not None and m.end() <= at:
        s, e = m.start(), m.end()
        pos = s + 1  # an occurrence may overlap the one before it
    return {"start": offsets.to_bytes(s), "end": offsets.to_bytes(e), "text": key_text}


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
