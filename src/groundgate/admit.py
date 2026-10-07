"""The decision procedure (SPEC §3) and receipts (SPEC §5)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .canonical import SPEC_VERSION, Offsets, digest, is_nfc
from .model import Decision, Field, Judgment, Outcome, PacketError, Policy, Receipt, Schema
from .text import (
    Token,
    canonical,
    key_cited,
    key_mentions,
    keys_at,
    normalize_ws,
    parse_value,
    qualifiers,
    quote_pattern,
    scale_word,
    scaled_value,
    tokens,
    unit_at,
    verbatim_equal,
)

NULL_LITERALS = {"null", "none", "nil", "n/a"}
FLAG_ORDER = (  # SPEC §3 table order; it is part of every receipt hash
    "NON_VERBATIM_EVIDENCE",
    "QUALIFIED_VALUE",
    "SCALE_WORD",
    "KEY_NOT_AT_VALUE",
    "KEY_CITATION_INVALID",
    "LOW_CONFIDENCE",
    "CONFLICTING_CANDIDATES",
    "MODEL_DOUBT",
)
REANCHORED = "EVIDENCE_REANCHORED"
KEY_CITED = "KEY_CITED"
CLEARED = "MODEL_CLEARED"
QUESTIONS = ("key", "field_match")


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
    mentions: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)
    suffixes: frozenset[str] = frozenset()  # of every unit in the table (SPEC §4.3)

    def key_mentions(self, f: Field) -> list[tuple[int, int, str]]:
        if f.name not in self.mentions:
            self.mentions[f.name] = key_mentions(self.text, f.keys or ())
        return self.mentions[f.name]


@dataclass
class _Passed:
    """A candidate that passed steps 1-11."""

    field: Field
    value: str
    unit: str | None
    key: str | None  # None on a field without keys
    span: tuple[int, int]  # code points
    token: Token | None
    flags: list[str]
    reanchored: bool
    cleared: bool = False  # a recorded judgment removed KEY_NOT_AT_VALUE (step 12)
    key_span: tuple[int, int] | None = None  # the valid span cited for the key, code points
    cited: bool = False  # the key citation removed KEY_NOT_AT_VALUE


def _value_at(
    ctx: _Ctx, f: Field, value: Decimal | str, span: tuple[int, int]
) -> tuple[Token | None, str | None]:
    """Steps 10-11 at one span: the supporting token (None for strings) or a failure code."""
    s, e = span
    if f.type == "string":
        assert isinstance(value, str)
        if normalize_ws(value) not in normalize_ws(ctx.text[s:e]):
            return None, "VALUE_NOT_IN_EVIDENCE"
        return None, None
    hits = [
        t
        for t in tokens(ctx.text, s, e)
        if t.value is not None and value in (t.value, scaled_value(ctx.text, t))
    ]
    if not hits:
        return None, "VALUE_NOT_IN_EVIDENCE"
    if f.unit is None:
        return hits[0], None
    prefixes, suffixes = ctx.schema.units.get(f.unit, ([], []))
    for t in hits:
        if unit_at(ctx.text, t, prefixes, suffixes, ctx.policy.unit_window, ctx.suffixes):
            return t, None
    return None, "UNIT_NOT_IN_EVIDENCE"


def _check(ctx: _Ctx, cand: object) -> _Passed:
    """Steps 1-11 plus per-candidate flags. Raises _Reject."""
    # 1. structure
    if not isinstance(cand, Mapping):
        raise _Reject("CANDIDATE_INVALID")
    name, raw, unit = cand.get("field"), cand.get("value"), cand.get("unit")
    conf, ev, region = cand.get("confidence"), cand.get("evidence"), cand.get("search_region")
    key = cand.get("key")
    if not isinstance(name, str) or isinstance(raw, bool) or not isinstance(raw, (str, int)):
        raise _Reject("CANDIDATE_INVALID")
    if (unit is not None and not isinstance(unit, str)) or (
        key is not None and not isinstance(key, str)
    ):
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
    key_ev = cand.get("key_evidence")
    key_cite = None
    if key_ev is not None:
        key_cite = _span(key_ev)
        if key_cite is None or not isinstance(key_ev.get("text", ""), str):
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
    # 7. key
    if f.keys is None:
        key = None
    elif key not in f.keys:
        raise _Reject("KEY_INVALID")
    # 8-9. evidence
    if cited is None:
        raise _Reject("NO_EVIDENCE")
    span = _valid(ctx.offsets, cited)
    search = (0, len(ctx.text)) if region_span is None else _valid(ctx.offsets, region_span)
    if span is None or search is None:
        raise _Reject("SPAN_INVALID")
    # 10-11. value and unit at the evidence, with re-anchoring
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
        if scale_word(ctx.text, token) and token.value == value:  # written, not scaled
            flags.append("SCALE_WORD")
    key_span = None
    key_used = False
    if f.keys is not None:
        at = token.start if token is not None else span[0]
        mentions = ctx.key_mentions(f)
        held = key in keys_at(ctx.text, mentions, at)
        if key_cite is not None:
            assert isinstance(key_ev, Mapping)
            assert key is not None
            key_span = _valid(ctx.offsets, key_cite)
            ok = key_span is not None and key_cited(ctx.text, mentions, key, key_span, at)
            shown = key_ev.get("text")
            if ok and isinstance(shown, str):
                assert key_span is not None
                ok = verbatim_equal(shown, ctx.text[key_span[0] : key_span[1]])
            if ok:
                key_used = not held
                held = True
            else:
                flags.append("KEY_CITATION_INVALID")
        if not held:
            flags.append("KEY_NOT_AT_VALUE")
    mc = ctx.policy.min_confidence
    if mc is not None and conf is not None and conf < mc:
        flags.append("LOW_CONFIDENCE")
    canon = value if isinstance(value, str) else canonical(value)
    return _Passed(f, canon, unit, key, span, token, flags, reanchored, False, key_span, key_used)


@dataclass(frozen=True)
class _Judgment:
    question: str
    judge: tuple[str, str]
    answer: str | None
    p: float


def _judgments(raw: object, candidates: Sequence[object]) -> dict[int, dict[str, _Judgment]]:
    """The recorded judgments (SPEC §2.6) by candidate position and question."""
    if raw is None:
        return {}
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise PacketError("judgments must be a list")
    ids: dict[tuple[type, object], list[int]] = defaultdict(list)
    for i, cand in enumerate(candidates):
        cid = cand.get("id") if isinstance(cand, Mapping) else None
        if isinstance(cid, (str, int)) and not isinstance(cid, bool):
            ids[type(cid), cid].append(i)
    out: dict[int, dict[str, _Judgment]] = defaultdict(dict)
    for n, j in enumerate(raw):
        where = f"judgment {n}"
        if not isinstance(j, Mapping):
            raise PacketError(f"{where} must be an object")
        known = {"candidate_id", "question", "judge", "p"} | (
            {"answer"} if j.get("question") == "key" else set()
        )
        if set(j) - known:
            raise PacketError(f"{where} has unknown keys {sorted(set(j) - known)}")
        question, judge, p = j.get("question"), j.get("judge"), j.get("p")
        if question not in QUESTIONS:
            raise PacketError(f"{where}: question must be one of {list(QUESTIONS)}")
        if (
            not isinstance(judge, Mapping)
            or set(judge) != {"id", "digest"}
            or not all(isinstance(judge[k], str) and judge[k].strip() for k in judge)
        ):
            raise PacketError(f"{where}: judge must hold a non-blank id and digest")
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not 0 <= p <= 1:
            raise PacketError(f"{where}: p must be a number in [0, 1]")
        answer = j.get("answer")
        if question == "key" and ("answer" not in j or not isinstance(answer, (str, type(None)))):
            raise PacketError(f"{where}: a key judgment needs an answer, a key or null")
        cid = j.get("candidate_id")
        if isinstance(cid, bool) or not isinstance(cid, (str, int)):
            raise PacketError(f"{where}: candidate_id must be a string or an integer")
        at = ids.get((type(cid), cid), [])
        if len(at) != 1:
            raise PacketError(f"{where}: {len(at)} candidates have the id {cid!r}, not 1")
        if question in out[at[0]]:
            raise PacketError(f"{where}: the candidate has a {question} judgment already")
        out[at[0]][question] = _Judgment(question, (judge["id"], judge["digest"]), answer, float(p))
    return out


def _judge(policy: Policy, p: _Passed, js: dict[str, _Judgment]) -> list[_Judgment]:
    """Step 12: apply the recorded judgments of one candidate; return those that applied."""
    jp = policy.judge
    if jp is None:
        return []
    applied = []
    for j in js.values():
        if j.judge != (jp.id, jp.digest):
            continue
        if j.question == "key" and jp.clear_key is not None:
            applied.append(j)
            if j.p < jp.clear_key:
                continue
            if "KEY_NOT_AT_VALUE" in p.flags:
                if j.answer == p.key:
                    p.flags.remove("KEY_NOT_AT_VALUE")
                    p.cleared = True
                else:
                    p.flags.append("MODEL_DOUBT")
            elif p.cited and j.answer != p.key:  # a judge that names another key doubts a citation
                p.flags.append("MODEL_DOUBT")
        elif j.question == "field_match" and jp.doubt_field is not None:
            applied.append(j)
            if j.p < jp.doubt_field:
                p.flags.append("MODEL_DOUBT")
    return applied


def admit(
    text: str,
    schema: Schema | Mapping[str, Any],
    candidates: Sequence[object],
    policy: Policy | Mapping[str, Any] | None = None,
    document_id: str | None = None,
    judgments: Sequence[object] | None = None,
) -> Receipt:
    """Decide every candidate and return the receipt.

    ``text`` is the document in Unicode NFC. ``schema`` and ``policy`` are dicts or ``Schema`` and
    ``Policy`` objects; ``policy=None`` uses the defaults. ``candidates`` is a list of candidate
    dicts with UTF-8 byte spans as evidence. A malformed candidate gets a ``rejected`` decision,
    not an exception. ``document_id`` is copied into the receipt. ``judgments`` are recorded
    answers of a judge (SPEC §2.6); the policy's ``judge`` block says which apply.

    Raises ``PacketError`` when the text is not NFC, ``candidates`` is not a list, or the schema,
    policy or judgments are invalid. Then no receipt is made.
    """
    if not isinstance(text, str) or not is_nfc(text):
        raise PacketError("document text must be a string in Unicode NFC")
    if not isinstance(schema, Schema):
        schema = Schema.from_dict(schema)
    if not isinstance(policy, Policy):
        policy = Policy() if policy is None else Policy.from_dict(policy)
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise PacketError("candidates must be a list")
    by_cand = _judgments(judgments, candidates)
    table = frozenset(x for _, suffixes in schema.units.values() for x in suffixes)
    ctx = _Ctx(text, Offsets(text), schema, policy, suffixes=table)

    results: list[tuple[str, int, object, _Passed | str]] = []
    for i, cand in enumerate(candidates):
        try:
            outcome: _Passed | str = _check(ctx, cand)
        except _Reject as r:
            outcome = r.code
        results.append((digest("candidate", cand), i, cand, outcome))

    by_key: dict[tuple[str, str | None], set[tuple[str, str | None]]] = defaultdict(set)
    for *_, p in results:
        if isinstance(p, _Passed) and not p.field.multiple:
            by_key[p.field.name, p.key].add((p.value, p.unit))
    for *_, p in results:
        if isinstance(p, _Passed) and len(by_key.get((p.field.name, p.key), ())) > 1:
            p.flags.append("CONFLICTING_CANDIDATES")

    decisions: list[Decision] = []
    applied: list[Judgment] = []
    for sha, i, cand, p in sorted(results, key=lambda r: (r[0], r[1])):
        if isinstance(p, _Passed):
            for j in sorted(_judge(policy, p, by_cand.get(i, {})), key=lambda j: j.question):
                applied.append(Judgment(sha, j.question, j.answer, j.p))
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
        tuple(applied),
    )
    return Receipt(**{**draft.__dict__, "receipt_sha256": digest("receipt", draft.body())})


def _decision(ctx: _Ctx, sha: str, cand: object, cid: object, p: _Passed | str) -> Decision:
    if isinstance(p, _Passed):
        flags = [c for c in FLAG_ORDER if c in p.flags]
        codes = [
            *flags,
            *([REANCHORED] if p.reanchored else []),
            *([KEY_CITED] if p.cited else []),
            *([CLEARED] if p.cleared else []),
        ]
        byte_span = (ctx.offsets.to_bytes(p.span[0]), ctx.offsets.to_bytes(p.span[1]))
        key_byte_span = (
            None
            if p.key_span is None
            else (ctx.offsets.to_bytes(p.key_span[0]), ctx.offsets.to_bytes(p.key_span[1]))
        )
        outcome: Outcome = "needs_verification" if flags else "admitted"
        return Decision(
            _json_id(cid),
            sha,
            p.field.name,
            outcome,
            tuple(codes),
            p.value,
            p.unit,
            byte_span,
            p.key,
            key_byte_span,
        )
    # rejected: report what is known about the candidate
    field_name: str | None = None
    value: str | None = None
    unit: str | None = None
    span: tuple[int, int] | None = None
    key: str | None = None
    if isinstance(cand, Mapping):
        if isinstance(cand.get("field"), str):
            field_name = cand["field"]
        if isinstance(cand.get("unit"), str):
            unit = cand["unit"]
        f = ctx.schema.fields.get(field_name or "")
        if f is not None and f.keys is not None and isinstance(cand.get("key"), str):
            key = cand["key"]
        raw = cand.get("value")
        if f is not None and isinstance(raw, (str, int)) and not isinstance(raw, bool):
            if f.type == "string" and isinstance(raw, str) and normalize_ws(raw):
                value = normalize_ws(raw)
            elif f.type != "string" and (parsed := parse_value(str(raw))) is not None:
                value = canonical(parsed)
        cited = _span(cand.get("evidence"))
        if cited is not None and _valid(ctx.offsets, cited) is not None:
            span = cited
    return Decision(_json_id(cid), sha, field_name, "rejected", (p,), value, unit, span, key)


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
    judgments: Sequence[object] | None = None,
) -> Verification:
    """Re-derive the receipt from its inputs and compare it with ``receipt``.

    ``receipt`` is the JSON object that ``Receipt.to_dict()`` returned. The other arguments are
    the inputs given to ``admit``, with the same ``judgments``. The result has ``ok`` and
    ``problems``: ``(True, ())`` when every byte re-derives. A receipt from another spec version
    gives one problem and no further
    checks. Raises ``PacketError`` when ``receipt`` is not a JSON object or an input is invalid.
    """
    if not isinstance(receipt, Mapping):
        raise PacketError("receipt must be a JSON object")
    if (version := receipt.get("groundgate")) != SPEC_VERSION:
        problem = f"receipt was decided under spec {version}; this groundgate implements "
        return Verification(False, (problem + SPEC_VERSION,))
    problems = []
    body = {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    if digest("receipt", body) != receipt.get("receipt_sha256"):
        problems.append("receipt_sha256 does not match the receipt body")
    doc_id = (
        receipt.get("document", {}).get("id")
        if isinstance(receipt.get("document"), Mapping)
        else None
    )
    fresh = admit(text, schema, candidates, policy, doc_id, judgments).to_dict()
    for key in ("document", "schema_sha256", "policy_sha256", "coverage", "judgments", "summary"):
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
