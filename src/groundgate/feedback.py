"""Feedback messages for an extractor from one candidate's decision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .canonical import digest
from .codes import DESCRIPTIONS, INFO
from .model import Decision, Schema

_RETRY = {
    "PART_MISSING",
    "QUOTE_NOT_FOUND",
    "NON_VERBATIM_EVIDENCE",
    "SCALE_WORD",
    "NO_EVIDENCE",
    "SIGN_CITATION_INVALID",
    "SCALE_CITATION_INVALID",
    "UNIT_CITATION_INVALID",
    "FIELD_CITATION_INVALID",
    "KEY_CITATION_INVALID",
}


def _in_table_row(
    decision: Decision, text: str | None, references: Sequence[object] | None
) -> bool:
    if decision.source == "reference":
        text = next(
            (
                r.get("text")
                for r in references or ()
                if isinstance(r, Mapping) and r.get("id") == decision.ref
            ),
            None,
        )
    elif decision.source != "document":
        return False
    if text is None or decision.evidence is None:
        return False
    data = text.encode("utf-8")
    pos = decision.evidence[0]
    start = data.rfind(b"\n", 0, pos) + 1
    end = data.find(b"\n", pos)
    return b"\t" in data[start : end if end >= 0 else len(data)]


def feedback_message(
    decision: Decision,
    candidate: object,
    schema: Schema | Mapping[str, Any],
    text: str | None = None,
    references: Sequence[object] | None = None,
) -> str | None:
    """Build the text for the extractor, or None when a new answer cannot fix the decision.

    ``candidate`` is the candidate that ``decision`` decided. ``schema`` and ``references``
    take the same forms as in ``admit``. A missing unit or key needs the field's aliases.
    A missing key with ``KEY_NOT_AT_VALUE`` also needs a table row at the value's byte span
    in ``text`` or in the reference that ``decision.ref`` names.

    The message repeats the value and quotes, describes each code outside ``INFO``, and names
    each missing part and each part that failed. An admitted decision returns None.
    Raises ``ValueError`` when the candidate's digest does not match the decision.
    """
    if digest("candidate", candidate) != decision.candidate_sha256:
        raise ValueError("candidate digest does not match the decision")
    if decision.outcome == "admitted":
        return None
    for code in decision.codes:
        if code in INFO or code in _RETRY:
            continue
        if (
            code == "KEY_NOT_AT_VALUE"
            and "key" in decision.missing
            and _in_table_row(decision, text, references)
        ):
            continue
        return None
    s = schema if isinstance(schema, Schema) else Schema.from_dict(schema)
    if {"unit", "key"} & set(decision.missing):
        field = s.fields.get(decision.field) if decision.field is not None else None
        if field is None or not field.aliases:
            return None
    if not isinstance(candidate, Mapping):
        return None
    evidence = candidate.get("evidence")
    items = [evidence] if isinstance(evidence, Mapping) else evidence or []
    quotes = ", ".join(
        f'{e.get("role", "value")} "{e["text"]}"'
        for e in items
        if isinstance(e, Mapping) and isinstance(e.get("text"), str)
    )
    lines = [
        f'Field "{decision.field}": you gave the value "{candidate.get("value")}" '
        f"with {quotes or 'no quotes'}."
    ]
    for code in decision.codes:
        if code not in INFO:
            lines.append(f"- {code}: {DESCRIPTIONS[code]}")
    for missing in decision.missing:
        lines.append(f'- Cite the {missing} with a "{missing}" item.')
        if missing in ("unit", "key"):
            lines.append('- Also cite the words that name the field with a "field" item.')
    for part in decision.parts:
        if not part.passed:
            lines.append(f'- The "{part.role}" item does not support the {part.role} at the value.')
    return "\n".join(lines)
