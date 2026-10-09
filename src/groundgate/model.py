"""Schema, policy, decision and receipt types (SPEC §2, §5)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from importlib import resources
from typing import Any, Literal

from .canonical import SPEC_VERSION
from .text import builtin_units, normalize_ws, parse_value

FieldType = Literal["number", "integer", "string"]
Comparator = Literal["eq", "gt", "ge", "lt", "le", "approx", "range"]
Outcome = Literal["admitted", "needs_verification", "rejected"]
Action = Literal["admit", "review", "reject"]

_TYPES = ("number", "integer", "string")
_COMPARATORS = ("eq", "gt", "ge", "lt", "le", "approx", "range")


class PacketError(ValueError):
    """The inputs themselves are invalid (SPEC §2): no receipt can be produced."""


def _bound(name: str, raw: object) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise PacketError(f"field bound {name} must be a decimal string or integer")
    if isinstance(raw, int) and not -(2**53 - 1) <= raw <= 2**53 - 1:
        raise PacketError(f"field bound {name}: integer is outside [-(2^53-1), 2^53-1]")
    value = parse_value(str(raw))
    if value is None:
        raise PacketError(f"field bound {name}={raw!r} is not a decimal")
    return value


@dataclass(frozen=True)
class Field:
    name: str
    type: FieldType = "number"
    unit: str | None = None
    comparator: Comparator = "eq"
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    required: bool = False
    multiple: bool = False
    keys: tuple[str, ...] | None = None
    aliases: tuple[str, ...] | None = None
    description: str | None = None
    _raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, name: str, d: object) -> Field:
        if not isinstance(d, dict):
            raise PacketError(f"field {name!r} must be an object")
        unknown = set(d) - {
            "type",
            "unit",
            "comparator",
            "minimum",
            "maximum",
            "required",
            "multiple",
            "keys",
            "aliases",
            "description",
        }
        if unknown:
            raise PacketError(f"field {name!r} has unknown keys {sorted(unknown)}")
        raw = {
            "type": d.get("type", "number"),
            "unit": d.get("unit"),
            "comparator": d.get("comparator", "eq"),
            "minimum": d.get("minimum"),
            "maximum": d.get("maximum"),
            "required": d.get("required", False),
            "multiple": d.get("multiple", False),
            "keys": d.get("keys"),
            "aliases": d.get("aliases"),
        }
        if "description" in d:
            description = d["description"]
            if not isinstance(description, str) or not description.strip():
                raise PacketError(f"field {name!r} description must be a non-blank string")
            raw["description"] = description
        if raw["type"] not in _TYPES:
            raise PacketError(f"field {name!r} has unknown type {raw['type']!r}")
        if raw["comparator"] not in _COMPARATORS:
            raise PacketError(f"field {name!r} has unknown comparator {raw['comparator']!r}")
        if raw["unit"] is not None and not isinstance(raw["unit"], str):
            raise PacketError(f"field {name!r} unit must be a string or null")
        for flag in ("required", "multiple"):
            if not isinstance(raw[flag], bool):
                raise PacketError(f"field {name!r} {flag} must be a boolean")
        for member in ("keys", "aliases"):
            words = raw[member]
            if words is None:
                continue
            if (
                not isinstance(words, list)
                or not words
                or not all(isinstance(k, str) for k in words)
            ):
                raise PacketError(f"field {name!r} {member} must be null or a list of strings")
            seen = [normalize_ws(k).lower() for k in words]
            if "" in seen or len(set(seen)) != len(seen):
                raise PacketError(f"field {name!r} {member} must be distinct, non-blank text")
            raw[member] = list(words)
        keys, aliases = raw["keys"], raw["aliases"]
        return cls(
            name=name,
            type=raw["type"],
            unit=raw["unit"],
            comparator=raw["comparator"],
            minimum=_bound(f"{name}.minimum", raw["minimum"]),
            maximum=_bound(f"{name}.maximum", raw["maximum"]),
            required=raw["required"],
            multiple=raw["multiple"],
            keys=None if keys is None else tuple(keys),
            aliases=None if aliases is None else tuple(aliases),
            description=raw.get("description"),
            _raw=raw,
        )


@dataclass(frozen=True)
class Schema:
    fields: dict[str, Field]
    units: dict[str, tuple[list[str], list[str]]]
    _raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_dict(cls, d: object) -> Schema:
        if not isinstance(d, dict) or not isinstance(d.get("fields"), dict):
            raise PacketError("schema must be an object with a 'fields' object")
        if set(d) - {"fields", "units"}:
            raise PacketError(f"schema has unknown keys {sorted(set(d) - {'fields', 'units'})}")
        fields = {name: Field.from_dict(name, f) for name, f in d["fields"].items()}
        user_units = d.get("units", {})
        if not isinstance(user_units, dict):
            raise PacketError("schema units must be an object")
        units = builtin_units()
        raw_units: dict[str, Any] = {}
        for code, forms in user_units.items():
            if not isinstance(forms, dict) or set(forms) - {"prefix", "suffix"}:
                raise PacketError(f"unit {code!r} must be an object with prefix/suffix lists")
            prefix, suffix = forms.get("prefix", []), forms.get("suffix", [])
            for lst in (prefix, suffix):
                if not isinstance(lst, list) or not all(isinstance(x, str) and x for x in lst):
                    raise PacketError(f"unit {code!r} surfaces must be non-empty strings")
            units[code] = (list(prefix), list(suffix))
            raw_units[code] = {"prefix": list(prefix), "suffix": list(suffix)}
        raw = {"fields": {n: f._raw for n, f in fields.items()}, "units": raw_units}
        return cls(fields=fields, units=units, _raw=raw)

    def to_dict(self) -> dict[str, Any]:
        """The schema with defaults filled in: the object ``schema_sha256`` covers."""
        return self._raw


@dataclass(frozen=True)
class JudgePolicy:
    """The one judge whose recorded judgments a decision reads, and its thresholds (SPEC §2.4)."""

    id: str
    digest: str
    clear_key: float | None = None  # clear.KEY_NOT_AT_VALUE
    doubt_field: float | None = None  # doubt.field_match

    @classmethod
    def from_dict(cls, d: object) -> JudgePolicy:
        if not isinstance(d, dict):
            raise PacketError("policy judge must be an object or null")
        unknown = set(d) - {"id", "digest", "clear", "doubt"}
        if unknown:
            raise PacketError(f"policy judge has unknown keys {sorted(unknown)}")
        for k in ("id", "digest"):
            if not isinstance(d.get(k), str) or not d[k].strip():
                raise PacketError(f"policy judge {k} must be a non-blank string")
        found: dict[str, float | None] = {}
        for k, name in (("clear", "KEY_NOT_AT_VALUE"), ("doubt", "field_match")):
            block = d.get(k, {})
            if not isinstance(block, dict) or set(block) - {name}:
                raise PacketError(f"policy judge {k} can hold only {name}")
            t = block.get(name)
            if name in block and not _probability(t):
                raise PacketError(f"policy judge {k}.{name} must be a number in [0, 1]")
            found[k] = t
        return cls(d["id"], d["digest"], found["clear"], found["doubt"])

    def to_dict(self) -> dict[str, Any]:
        clear = {} if self.clear_key is None else {"KEY_NOT_AT_VALUE": self.clear_key}
        doubt = {} if self.doubt_field is None else {"field_match": self.doubt_field}
        return {"id": self.id, "digest": self.digest, "clear": clear, "doubt": doubt}


def _probability(x: object) -> bool:
    return not isinstance(x, bool) and isinstance(x, (int, float)) and 0 <= x <= 1


@dataclass(frozen=True)
class Sources:
    """What happens to a candidate that only outside evidence supports (SPEC §2.4)."""

    allow: tuple[str, ...] = ()  # external.allow
    other: Action = "review"  # external.other
    knowledge: Action = "review"

    @classmethod
    def from_dict(cls, d: object) -> Sources:
        if not isinstance(d, dict) or set(d) - {"external", "knowledge"}:
            raise PacketError("policy sources can hold only external and knowledge")
        ext = d.get("external", {})
        if not isinstance(ext, dict) or set(ext) - {"allow", "other"}:
            raise PacketError("policy sources.external can hold only allow and other")
        allow = ext.get("allow", [])
        if not isinstance(allow, list) or not all(isinstance(a, str) and a.strip() for a in allow):
            raise PacketError("policy sources.external.allow must be a list of non-blank strings")
        other = ext.get("other", "review")
        if other not in ("review", "reject"):
            raise PacketError("policy sources.external.other must be review or reject")
        knowledge = d.get("knowledge", "review")
        if knowledge not in ("admit", "review", "reject"):
            raise PacketError("policy sources.knowledge must be admit, review or reject")
        return cls(tuple(allow), other, knowledge)

    def to_dict(self) -> dict[str, Any]:
        return {
            "external": {"allow": list(self.allow), "other": self.other},
            "knowledge": self.knowledge,
        }


@dataclass(frozen=True)
class Policy:
    min_confidence: float | None = None
    unit_window: int = 24
    reanchor: bool = True
    judge: JudgePolicy | None = None
    sources: Sources = Sources()

    @classmethod
    def from_dict(cls, d: object) -> Policy:
        if not isinstance(d, dict):
            raise PacketError("policy must be an object")
        unknown = set(d) - {"min_confidence", "unit_window", "reanchor", "judge", "sources"}
        if unknown:
            raise PacketError(f"policy has unknown keys {sorted(unknown)}")
        mc = d.get("min_confidence")
        if mc is not None and (
            isinstance(mc, bool) or not isinstance(mc, (int, float)) or not 0 <= mc <= 1
        ):
            raise PacketError("policy min_confidence must be a number in [0, 1] or null")
        uw = d.get("unit_window", 24)
        if isinstance(uw, bool) or not isinstance(uw, int) or uw < 0:
            raise PacketError("policy unit_window must be a non-negative integer")
        ra = d.get("reanchor", True)
        if not isinstance(ra, bool):
            raise PacketError("policy reanchor must be a boolean")
        judge = d.get("judge")
        jp = None if judge is None else JudgePolicy.from_dict(judge)
        sources = Sources.from_dict(d.get("sources", {}))
        return cls(min_confidence=mc, unit_window=uw, reanchor=ra, judge=jp, sources=sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_confidence": self.min_confidence,
            "unit_window": self.unit_window,
            "reanchor": self.reanchor,
            "judge": None if self.judge is None else self.judge.to_dict(),
            "sources": self.sources.to_dict(),
        }


@dataclass(frozen=True)
class Decision:
    candidate_id: object
    candidate_sha256: str
    field: str | None
    outcome: Outcome
    codes: tuple[str, ...]
    value: str | None
    unit: str | None
    evidence: tuple[int, int] | None  # UTF-8 byte span in the value item's text
    key: str | None = None
    source: str | None = None  # the kind of the item the decision rests on
    ref: str | None = None
    url: str | None = None
    parts: tuple[Part, ...] = ()
    missing: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_sha256": self.candidate_sha256,
            "field": self.field,
            "key": self.key,
            "outcome": self.outcome,
            "codes": list(self.codes),
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "ref": self.ref,
            "url": self.url,
            "evidence": None
            if self.evidence is None
            else {"start": self.evidence[0], "end": self.evidence[1]},
            "parts": [p.to_dict() for p in self.parts],
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class Part:
    """A role item that reached the role checks (SPEC §5)."""

    role: str
    span: tuple[int, int] | None  # UTF-8 byte span, None when the item was not found
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        start, end = (None, None) if self.span is None else self.span
        return {"role": self.role, "start": start, "end": end, "passed": self.passed}


@dataclass(frozen=True)
class Judgment:
    """A recorded judgment that applied to a decision (SPEC §5)."""

    candidate_sha256: str
    question: str
    answer: str | None
    p: float

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"candidate_sha256": self.candidate_sha256, "question": self.question}
        if self.question == "key":
            out["answer"] = self.answer
        return {**out, "p": self.p}


@dataclass(frozen=True)
class Receipt:
    document_id: str | None
    document_sha256: str
    schema_sha256: str
    policy_sha256: str
    decisions: tuple[Decision, ...]
    coverage: tuple[tuple[str, str], ...]  # (field, code)
    receipt_sha256: str
    judgments: tuple[Judgment, ...] = ()  # the judgments that applied (SPEC §5)
    document_source: str | None = None
    references: tuple[tuple[str, str, str | None], ...] = ()  # (id, sha256, source)

    def body(self) -> dict[str, Any]:
        counts = {"admitted": 0, "needs_verification": 0, "rejected": 0}
        for d in self.decisions:
            counts[d.outcome] += 1
        return {
            "groundgate": SPEC_VERSION,
            "document": {
                "id": self.document_id,
                "sha256": self.document_sha256,
                "source": self.document_source,
            },
            "references": [{"id": i, "sha256": h, "source": s} for i, h, s in self.references],
            "schema_sha256": self.schema_sha256,
            "policy_sha256": self.policy_sha256,
            "decisions": [d.to_dict() for d in self.decisions],
            "coverage": [{"field": f, "code": c} for f, c in self.coverage],
            "judgments": [j.to_dict() for j in self.judgments],
            "summary": counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "receipt_sha256": self.receipt_sha256}


def candidate_schema() -> dict[str, Any]:
    """The JSON Schema of one candidate (SPEC §2.5). Step 1 of SPEC §3 is the definition."""
    raw = resources.files(__package__).joinpath("candidate.schema.json").read_text("utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


_ROLE_HELP = (
    "What the quote supports. value: the number itself. sign: brackets or a loss word that make "
    "it negative. scale: words such as 'in thousands'. unit: a unit or $ sign that is not next "
    "to the number. field: words that name the field, such as a row label. key: words that name "
    "the key, such as a column heading."
)


def _closed(props: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    """An object with every member required and no other members."""
    out: dict[str, Any] = {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }
    if description:
        out["description"] = description
    return out


def extractor_schema(
    schema: Schema | dict[str, Any], reference_ids: list[str] | None = None
) -> dict[str, Any]:
    """A JSON Schema for an extractor's structured output: {"candidates": [...]} for one schema.

    It uses only the JSON Schema subset of the strict structured-output modes, and every
    candidate that it accepts passes step 1 of SPEC §3. Two step 1 rules stay outside it: two
    items with the same role, and a blank text, url or retrieved.
    """
    s = schema if isinstance(schema, Schema) else Schema.from_dict(schema)
    if not s.fields:
        raise PacketError("the schema has no fields, so an extractor can send no candidate")
    if reference_ids is not None and (
        not reference_ids
        or not all(isinstance(r, str) and r.strip() for r in reference_ids)
        or len(set(reference_ids)) != len(reference_ids)
    ):
        raise PacketError("reference_ids must be a non-empty list of unique non-blank strings")
    quote = {"type": "string", "description": "Copied verbatim from the text."}
    role = {"enum": ["value", "sign", "scale", "unit", "field", "key"], "description": _ROLE_HELP}
    kinds: dict[str, dict[str, Any]] = {
        "document": _closed(
            {"source": {"const": "document"}, "role": role, "text": quote},
            "A quote from the document.",
        )
    }
    if reference_ids:
        kinds["reference"] = _closed(
            {
                "source": {"const": "reference"},
                "ref": {"enum": list(reference_ids)},
                "role": role,
                "text": quote,
            },
            "A quote from a reference text that the app gave.",
        )
    kinds["external"] = _closed(
        {
            "source": {"const": "external"},
            "url": {"type": "string"},
            "retrieved": {"type": "string", "description": "The date that you read the page."},
            "text": {"type": "string", "description": "Copied verbatim from the page."},
        },
        "A quote from a web page that states the value.",
    )
    kinds["knowledge"] = _closed(
        {
            "source": {"const": "knowledge"},
            "text": {"type": "string", "description": "Your statement of the fact and its basis."},
        },
        "Your own knowledge, when no text states the value.",
    )
    # one evidence definition: strict modes count each anyOf against a limit per request
    evidence = {"type": "array", "items": {"anyOf": [{"$ref": f"#/$defs/{k}"} for k in kinds]}}
    cands = []
    for f in s.fields.values():
        if f.type == "string":
            value = {"type": "string", "description": "The value as the text states it."}
        else:
            value = {
                "type": "string",
                "description": "The number with its sign and scale, without $, commas or a unit.",
            }
        names = f"Names in the document: {', '.join(f.aliases)}." if f.aliases else None
        description = "\n".join(part for part in (f.description, names) if part is not None)
        cands.append(
            _closed(
                {
                    "field": {"const": f.name},
                    "value": value,
                    "unit": {"type": "null"} if f.unit is None else {"const": f.unit},
                    "key": {"type": "null"} if f.keys is None else {"enum": list(f.keys)},
                    "evidence": {"$ref": "#/$defs/evidence"},
                },
                description or None,
            )
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        **_closed(
            {
                "candidates": {
                    "type": "array",
                    "items": cands[0] if len(cands) == 1 else {"anyOf": cands},
                }
            }
        ),
        "$defs": {**kinds, "evidence": evidence},
    }
