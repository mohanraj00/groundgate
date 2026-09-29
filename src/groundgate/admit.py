"""The decision procedure (SPEC §3) and receipts (SPEC §5)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .canonical import Offsets, digest, is_nfc
from .model import Decision, Field, Outcome, PacketError, Policy, Receipt, Schema
from .text import (
    Token,
    canonical,
    normalize_ws,
    parse_value,
    qualifiers,
    quote_pattern,
    scale_word,
    tokens,
    unit_at,
    verbatim_equal,
)

NULL_LITERALS = {"null", "none", "nil", "n/a"}
FLAG_ORDER = (
    "NON_VERBATIM_EVIDENCE",
    "QUALIFIED_VALUE",
    "SCALE_WORD",
    "LOW_CONFIDENCE",
    "CONFLICTING_CANDIDATES",
)
REANCHORED = "EVIDENCE_REANCHORED"


class _Reject(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


def _span(obj: object) -> tuple[int, int] | None:
    """(start, end) from a span object, or None if malformed (SPEC §3 step 1)."""
    if not isinstance(obj, Mapping):
        return None
    s, e = obj.get("start"), obj.get("end")
    if (
        isinstance(s, bool)
        or isinstance(e, bool)
        or not isinstance(s, int)
        or not isinstance(e, int)
    ):
        return None
    return s, e


def _valid(offsets: Offsets, span: tuple[int, int]) -> tuple[int, int] | None:
    """Code-point span for a valid byte span (SPEC §2.2), else None."""
    s, e = span
    if not (0 <= s < e <= offsets.byte_length):
        return None
    cs, ce = offsets.to_char(s), offsets.to_char(e)
    return None if cs is None or ce is None else (cs, ce)


@dataclass
class _Ctx:
    text: str
    offsets: Offsets
    schema: Schema
    policy: Policy


@dataclass
class _Passed:
    """A candidate that passed steps 1-10."""

    field: Field
    value: str
    unit: str | None
    span: tuple[int, int]  # code points
    token: Token | None
    flags: list[str]
    reanchored: bool


def _value_at(
    ctx: _Ctx, f: Field, value: Decimal | str, span: tuple[int, int]
) -> tuple[Token | None, str | None]:
    """Steps 9-10 at one span: the supporting token (None for strings) or a failure code."""
    s, e = span
    if f.type == "string":
        assert isinstance(value, str)
        if normalize_ws(value) not in normalize_ws(ctx.text[s:e]):
            return None, "VALUE_NOT_IN_EVIDENCE"
        return None, None
    hits = [t for t in tokens(ctx.text, s, e) if t.value is not None and t.value == value]
    if not hits:
        return None, "VALUE_NOT_IN_EVIDENCE"
    if f.unit is None:
        return hits[0], None
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], []))
    for t in hits:
        if unit_at(ctx.text, t, prefixes, suffixes, ctx.policy.unit_window):
            return t, None
    return None, "UNIT_NOT_IN_EVIDENCE"


def _check(ctx: _Ctx, cand: object) -> _Passed:
    """Steps 1-10 plus per-candidate flags. Raises _Reject."""
    # 1. structure
    if not isinstance(cand, Mapping):
        raise _Reject("CANDIDATE_INVALID")
    name, raw, unit = cand.get("field"), cand.get("value"), cand.get("unit")
    conf, ev, region = cand.get("confidence"), cand.get("evidence"), cand.get("search_region")
    if not isinstance(name, str) or isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise _Reject("CANDIDATE_INVALID")
    if unit is not None and not isinstance(unit, str):
        raise _Reject("CANDIDATE_INVALID")
    if conf is not None and (
        isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0 <= conf <= 1
    ):
        raise _Reject("CANDIDATE_INVALID")
    cited = None
    if ev is not None:
        cited = _span(ev)
        if cited is None or not isinstance(ev.get("text", ""), str):
            raise _Reject("CANDIDATE_INVALID")
    region_span = None
    if region is not None:
        region_span = _span(region)
        if region_span is None:
            raise _Reject("CANDIDATE_INVALID")
    # 2-6. field, value, type, range, unit
    f = ctx.schema.fields.get(name)
    if f is None:
        raise _Reject("FIELD_UNKNOWN")
    text_value = str(raw)
    if text_value.strip().lower() in NULL_LITERALS:
        raise _Reject("NULL_STRING_LITERAL")
    value: Decimal | str
    if f.type == "string":
        if not isinstance(raw, str) or not normalize_ws(raw):
            raise _Reject("TYPE_INVALID")
        value = normalize_ws(raw)
    else:
        parsed = parse_value(text_value)
        if parsed is None or (f.type == "integer" and parsed != parsed.to_integral_value()):
            raise _Reject("TYPE_INVALID")
        value = parsed
        if (f.minimum is not None and parsed < f.minimum) or (
            f.maximum is not None and parsed > f.maximum
        ):
            raise _Reject("RANGE_INVALID")
    if unit != f.unit:
        raise _Reject("UNIT_INVALID")
    # 7-8. evidence
    if cited is None:
        raise _Reject("NO_EVIDENCE")
    span = _valid(ctx.offsets, cited)
    search = (0, len(ctx.text)) if region_span is None else _valid(ctx.offsets, region_span)
    if span is None or search is None:
        raise _Reject("SPAN_INVALID")
    # 9-10. value and unit at the evidence, with re-anchoring
    assert isinstance(ev, Mapping)
    quote = ev.get("text")
    token, failure = _value_at(ctx, f, value, span)
    reanchored = False
    if failure is not None:
        if not (ctx.policy.reanchor and isinstance(quote, str) and normalize_ws(quote)):
            raise _Reject(failure)
        passing = []
        for m in quote_pattern(quote).finditer(ctx.text, search[0], search[1]):
            alt = (m.start(), m.end())
            if alt != span:
                alt_token, alt_failure = _value_at(ctx, f, value, alt)
                if alt_failure is None:
                    passing.append((alt, alt_token))
        if len(passing) != 1:
            raise _Reject(failure)
        (span, token), reanchored = passing[0], True
    # flags
    flags = []
    if isinstance(quote, str) and not verbatim_equal(quote, ctx.text[span[0] : span[1]]):
        flags.append("NON_VERBATIM_EVIDENCE")
    if token is not None:
        found = qualifiers(ctx.text, token) - {f.comparator}
        if found:
            flags.append("QUALIFIED_VALUE")
        if scale_word(ctx.text, token):
            flags.append("SCALE_WORD")
    mc = ctx.policy.min_confidence
    if mc is not None and conf is not None and conf < mc:
        flags.append("LOW_CONFIDENCE")
    canon = value if isinstance(value, str) else canonical(value)
    return _Passed(f, canon, unit, span, token, flags, reanchored)


def admit(
    text: str,
    schema: Schema | Mapping[str, Any],
    candidates: Sequence[object],
    policy: Policy | Mapping[str, Any] | None = None,
    document_id: str | None = None,
) -> Receipt:
    """Decide every candidate and return the receipt."""
    if not isinstance(text, str) or not is_nfc(text):
        raise PacketError("document text must be a string in Unicode NFC")
    if not isinstance(schema, Schema):
        schema = Schema.from_dict(schema)
    if not isinstance(policy, Policy):
        policy = Policy() if policy is None else Policy.from_dict(policy)
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise PacketError("candidates must be a list")
    ctx = _Ctx(text, Offsets(text), schema, policy)

    results: list[tuple[str, int, object, _Passed | str]] = []
    for i, cand in enumerate(candidates):
        try:
            outcome: _Passed | str = _check(ctx, cand)
        except _Reject as r:
            outcome = r.code
        results.append((digest("candidate", cand), i, cand, outcome))

    by_field: dict[str, set[tuple[str, str | None]]] = defaultdict(set)
    for *_, p in results:
        if isinstance(p, _Passed) and not p.field.multiple:
            by_field[p.field.name].add((p.value, p.unit))
    for *_, p in results:
        if isinstance(p, _Passed) and len(by_field.get(p.field.name, ())) > 1:
            p.flags.append("CONFLICTING_CANDIDATES")

    decisions = []
    for sha, _, cand, p in sorted(results, key=lambda r: (r[0], r[1])):
        cid = cand.get("id") if isinstance(cand, Mapping) else None
        decisions.append(_decision(ctx, sha, cand, cid, p))

    live = {d.field for d in decisions if d.outcome != "rejected"}
    coverage = tuple(
        (name, "REQUIRED_FIELD_MISSING")
        for name in sorted(schema.fields)
        if schema.fields[name].required and name not in live
    )
    doc_sha = digest("document", {"text": text})
    draft = Receipt(
        document_id,
        doc_sha,
        digest("schema", schema.to_dict()),
        digest("policy", policy.to_dict()),
        tuple(decisions),
        coverage,
        "",
    )
    return Receipt(**{**draft.__dict__, "receipt_sha256": digest("receipt", draft.body())})


def _decision(ctx: _Ctx, sha: str, cand: object, cid: object, p: _Passed | str) -> Decision:
    if isinstance(p, _Passed):
        flags = [c for c in FLAG_ORDER if c in p.flags]
        codes = [*flags, REANCHORED] if p.reanchored else flags
        byte_span = (ctx.offsets.to_bytes(p.span[0]), ctx.offsets.to_bytes(p.span[1]))
        outcome: Outcome = "needs_verification" if flags else "admitted"
        return Decision(
            _json_id(cid), sha, p.field.name, outcome, tuple(codes), p.value, p.unit, byte_span
        )
    # rejected: report what is known about the candidate
    field_name: str | None = None
    value: str | None = None
    unit: str | None = None
    span: tuple[int, int] | None = None
    if isinstance(cand, Mapping):
        if isinstance(cand.get("field"), str):
            field_name = cand["field"]
        if isinstance(cand.get("unit"), str):
            unit = cand["unit"]
        f = ctx.schema.fields.get(field_name or "")
        raw = cand.get("value")
        if f is not None and isinstance(raw, (str, int)) and not isinstance(raw, bool):
            if f.type == "string" and isinstance(raw, str) and normalize_ws(raw):
                value = normalize_ws(raw)
            elif f.type != "string" and (parsed := parse_value(str(raw))) is not None:
                value = canonical(parsed)
        cited = _span(cand.get("evidence"))
        if cited is not None and _valid(ctx.offsets, cited) is not None:
            span = cited
    return Decision(_json_id(cid), sha, field_name, "rejected", (p,), value, unit, span)


def _json_id(cid: object) -> object:
    return (
        cid if cid is None or (isinstance(cid, (str, int)) and not isinstance(cid, bool)) else None
    )


@dataclass(frozen=True)
class Verification:
    ok: bool
    problems: tuple[str, ...]


def verify(
    receipt: Mapping[str, Any],
    text: str,
    schema: Schema | Mapping[str, Any],
    candidates: Sequence[object],
    policy: Policy | Mapping[str, Any] | None = None,
) -> Verification:
    """Re-derive the receipt from its inputs and compare it with ``receipt``."""
    problems = []
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if digest("receipt", body) != receipt.get("receipt_sha256"):
        problems.append("receipt_sha256 does not match the receipt body")
    doc_id = (
        receipt.get("document", {}).get("id")
        if isinstance(receipt.get("document"), Mapping)
        else None
    )
    fresh = admit(text, schema, candidates, policy, document_id=doc_id).to_dict()
    for key in ("document", "schema_sha256", "policy_sha256", "coverage", "summary"):
        if receipt.get(key) != fresh[key]:
            problems.append(f"{key} differs from the re-derived receipt")
    theirs, ours = receipt.get("decisions"), fresh["decisions"]
    if not isinstance(theirs, list) or len(theirs) != len(ours):
        problems.append("decision count differs from the re-derived receipt")
    else:
        for a, b in zip(theirs, ours, strict=True):
            if a != b:
                problems.append(f"decision for candidate {b['candidate_sha256']} differs")
    if not problems and receipt.get("receipt_sha256") != fresh["receipt_sha256"]:
        problems.append("receipt_sha256 differs from the re-derived receipt")  # pragma: no cover
    return Verification(not problems, tuple(problems))
