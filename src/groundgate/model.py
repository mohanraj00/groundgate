"""Schema, policy, decision and receipt types (SPEC §2, §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from .canonical import SPEC_VERSION
from .text import builtin_units, normalize_ws, parse_value

FieldType = Literal["number", "integer", "string"]
Comparator = Literal["eq", "gt", "ge", "lt", "le", "approx", "range"]
Outcome = Literal["admitted", "needs_verification", "rejected"]

_TYPES = ("number", "integer", "string")
_COMPARATORS = ("eq", "gt", "ge", "lt", "le", "approx", "range")


class PacketError(ValueError):
    """The inputs themselves are invalid (SPEC §2): no receipt can be produced."""


def _bound(name: str, raw: object) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise PacketError(f"field bound {name} must be a decimal string or integer")
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
        }
        if raw["type"] not in _TYPES:
            raise PacketError(f"field {name!r} has unknown type {raw['type']!r}")
        if raw["comparator"] not in _COMPARATORS:
            raise PacketError(f"field {name!r} has unknown comparator {raw['comparator']!r}")
        if raw["unit"] is not None and not isinstance(raw["unit"], str):
            raise PacketError(f"field {name!r} unit must be a string or null")
        for flag in ("required", "multiple"):
            if not isinstance(raw[flag], bool):
                raise PacketError(f"field {name!r} {flag} must be a boolean")
        keys = raw["keys"]
        if keys is not None:
            if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
                raise PacketError(f"field {name!r} keys must be null or a list of strings")
            seen = [normalize_ws(k).lower() for k in keys]
            if "" in seen or len(set(seen)) != len(seen):
                raise PacketError(f"field {name!r} keys must be distinct, non-blank text")
            raw["keys"] = list(keys)
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
class Policy:
    min_confidence: float | None = None
    unit_window: int = 24
    reanchor: bool = True
    judge: JudgePolicy | None = None

    @classmethod
    def from_dict(cls, d: object) -> Policy:
        if not isinstance(d, dict):
            raise PacketError("policy must be an object")
        unknown = set(d) - {"min_confidence", "unit_window", "reanchor", "judge"}
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
        return cls(min_confidence=mc, unit_window=uw, reanchor=ra, judge=jp)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_confidence": self.min_confidence,
            "unit_window": self.unit_window,
            "reanchor": self.reanchor,
            "judge": None if self.judge is None else self.judge.to_dict(),
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
    evidence: tuple[int, int] | None  # UTF-8 byte span
    key: str | None = None
    key_evidence: tuple[int, int] | None = None  # UTF-8 byte span cited for the key

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
            "evidence": None
            if self.evidence is None
            else {"start": self.evidence[0], "end": self.evidence[1]},
            "key_evidence": None
            if self.key_evidence is None
            else {"start": self.key_evidence[0], "end": self.key_evidence[1]},
        }


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

    def body(self) -> dict[str, Any]:
        counts = {"admitted": 0, "needs_verification": 0, "rejected": 0}
        for d in self.decisions:
            counts[d.outcome] += 1
        return {
            "groundgate": SPEC_VERSION,
            "document": {"id": self.document_id, "sha256": self.document_sha256},
            "schema_sha256": self.schema_sha256,
            "policy_sha256": self.policy_sha256,
            "decisions": [d.to_dict() for d in self.decisions],
            "coverage": [{"field": f, "code": c} for f, c in self.coverage],
            "judgments": [j.to_dict() for j in self.judgments],
            "summary": counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body(), "receipt_sha256": self.receipt_sha256}
