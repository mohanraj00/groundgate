"""Schema, policy, decision and receipt types (SPEC §2, §5)."""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from importlib import resources
from typing import Any, Literal

from .canonical import _SAFE_INT, SPEC_VERSION
from .fold import fold_text
from .pack import (
    BASE,
    BASE_ID,
    BUILT_IN,
    added_words,
    built_in_pack,
    checked_copy,
    combine,
    pack_digest,
)
from .pack import PacketError as PacketError
from .text import BASE_VOCABULARY, Vocabulary, normalize_ws, parse_value

FieldType = Literal["number", "integer", "string"]
Comparator = Literal["eq", "gt", "ge", "lt", "le", "approx", "range"]
Outcome = Literal["admitted", "needs_verification", "rejected"]
Action = Literal["admit", "review", "reject"]

_TYPES = ("number", "integer", "string")
_COMPARATORS = ("eq", "gt", "ge", "lt", "le", "approx", "range")


def _bound(name: str, raw: object, what: str = "field bound") -> Decimal | None:
    """A decimal string or an integer that reads as a number (SPEC §2.3, §4.1), or None."""
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise PacketError(f"{what} {name} must be a decimal string or integer")
    if isinstance(raw, int) and abs(raw) > _SAFE_INT:
        raise PacketError(f"{what} {name}: integer is outside [-(2^53-1), 2^53-1]")
    value = parse_value(str(raw))
    if value is None:
        raise PacketError(f"{what} {name}={raw!r} is not a decimal")
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
    template: str | None = None  # "<pack id>/<field name>" of a kind pack (SPEC §2.3, §4.9)

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
            "template",
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
        if "template" in d:
            if not isinstance(d["template"], str):
                raise PacketError(f"field {name!r} template must be a string (L10)")
            raw["template"] = d["template"]
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
            _words(name, member, raw[member])
            if raw[member] is not None:
                raw[member] = list(raw[member])
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
            template=raw.get("template"),
        )


@dataclass(frozen=True)
class Relation:
    """A relation between fields (SPEC §2.3): the total equals the sum of each part times its
    factor, within the tolerance and the places of the values (SPEC §3.4)."""

    id: str
    total: str
    parts: tuple[tuple[str, Decimal], ...]  # (field name, factor)
    tolerance: Decimal = Decimal(0)

    @property
    def fields(self) -> tuple[str, ...]:
        return (self.total, *(name for name, _ in self.parts))


def _relation_field(where: str, name: object, fields: dict[str, Field]) -> Field:
    if not isinstance(name, str) or name not in fields:
        raise PacketError(f"{where} names {name!r}, which is not a field of the schema")
    f = fields[name]
    if f.type == "string" or f.multiple:
        raise PacketError(f"{where}: field {name!r} is a string field or a multiple field")
    return f


def _relations(raw: object, fields: dict[str, Field]) -> tuple[tuple[Relation, ...], list[Any]]:
    """The schema's relations, and their form after defaults (SPEC §2.3, #321)."""
    if not isinstance(raw, list):
        raise PacketError("schema relations must be a list")
    out: list[Relation] = []
    filled: list[Any] = []
    for n, r in enumerate(raw):
        if not isinstance(r, dict) or set(r) - {"id", "total", "parts", "tolerance"}:
            raise PacketError(f"relation {n} must be an object with id, total, parts, tolerance")
        rid = r.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise PacketError(f"relation {n} id must be a non-blank string")
        where = f"relation {rid!r}"
        if any(x.id == rid for x in out):
            raise PacketError(f"{where}: another relation has the same id")
        total = _relation_field(where, r.get("total"), fields)
        parts_raw = r.get("parts")
        if not isinstance(parts_raw, list) or not parts_raw:
            raise PacketError(f"{where} parts must be a non-empty list")
        parts: list[tuple[str, Decimal]] = []
        parts_filled: list[dict[str, Any]] = []
        for part in parts_raw:
            if not isinstance(part, dict) or set(part) - {"field", "factor"}:
                raise PacketError(f"{where}: a part must be an object with only field and factor")
            f = _relation_field(where, part.get("field"), fields)
            given = part.get("factor", "1")
            factor = _bound("factor", given, where)
            if factor is None or factor == 0:
                raise PacketError(f"{where}: a factor must be a decimal that is not zero")
            if "factor" not in part and f.unit != total.unit:
                raise PacketError(f"{where}: part {f.name!r} has another unit and no factor")
            parts.append((f.name, factor))
            parts_filled.append({"field": f.name, "factor": given})
        names = [total.name, *(name for name, _ in parts)]
        if len(set(names)) != len(names):
            raise PacketError(f"{where} names one field twice")
        if len({fields[name].keys is None for name in names}) > 1:
            raise PacketError(f"{where}: some of its fields have keys, and others do not")
        given_tolerance = r.get("tolerance", "0")
        tolerance = _bound("tolerance", given_tolerance, where)
        if tolerance is None or tolerance < 0:
            raise PacketError(f"{where} tolerance must be a decimal that is not negative")
        out.append(Relation(rid, total.name, tuple(parts), tolerance))
        filled.append(
            {"id": rid, "total": total.name, "parts": parts_filled, "tolerance": given_tolerance}
        )
    return tuple(out), filled


@dataclass(frozen=True)
class Schema:
    fields: dict[str, Field]
    units: dict[str, tuple[list[str], list[str]]]
    _raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)
    relations: tuple[Relation, ...] = ()
    # the packs that apply, as the receipt names them (SPEC §2.3, §5), sorted by id
    packs: tuple[dict[str, str], ...] = ()
    vocabulary: Vocabulary = field(default=BASE_VOCABULARY, compare=False, repr=False)
    # each pack id with the words that it adds to the base (SPEC §5, decision packs)
    marks: tuple[tuple[str, frozenset[str]], ...] = field(default=(), compare=False, repr=False)
    # the checked copy of each given pack, sorted by id, so that ``copy`` can rebuild the schema
    given: tuple[dict[str, Any], ...] = field(default=(), compare=False, repr=False)

    @classmethod
    def from_dict(cls, d: object, packs: Sequence[object] = ()) -> Schema:
        """The schema, with the vocabulary packs that ``packs`` gives (SPEC §2.3, §4.8). The
        schema names each pack in its member ``packs``, and the caller gives each one."""
        if not isinstance(d, dict) or not isinstance(d.get("fields"), dict):
            raise PacketError("schema must be an object with a 'fields' object")
        members = {"fields", "units", "relations", "packs"}
        if set(d) - members:
            raise PacketError(f"schema has unknown keys {sorted(set(d) - members)}")
        resolved, vocabulary, marks, kinds, given = _resolve_packs(d.get("packs", []), packs)
        fields = {name: _field(name, f, kinds) for name, f in d["fields"].items()}
        user_units = d.get("units", {})
        if not isinstance(user_units, dict):
            raise PacketError("schema units must be an object")
        units = {code: (list(p), list(s)) for code, (p, s) in vocabulary.units.items()}
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
        raw: dict[str, Any] = {"fields": {n: f._raw for n, f in fields.items()}, "units": raw_units}
        relations, filled = _relations(d.get("relations", []), fields)
        if filled:  # a schema without relations keeps its digest (SPEC §2.3)
            raw["relations"] = filled
        if resolved:
            raw["packs"] = [{k: e[k] for k in ("id", "version", "sha256")} for e in resolved]
        return cls(
            fields=fields,
            units=units,
            _raw=raw,
            relations=relations,
            packs=tuple(resolved),
            vocabulary=vocabulary,
            marks=marks,
            given=given,
        )

    def to_dict(self) -> dict[str, Any]:
        """The schema with defaults filled in: the object ``schema_sha256`` covers."""
        return self._raw

    def copy(self) -> Schema:
        """A new schema from a deep copy of this one and of its packs. A later change of this
        schema, of its fields or of its packs has no effect on the copy."""
        return Schema.from_dict(copy.deepcopy(self._raw), copy.deepcopy(list(self.given)))


_PIN = re.compile(r"sha256:[0-9a-f]{64}\Z")
_VOCABULARIES: dict[tuple[str, ...], Vocabulary] = {}  # by the digests of the packs
_MAX_VOCABULARIES = 64


def _pack_entries(entries: object) -> dict[str, dict[str, str]]:
    """The schema member ``packs``: each pack by id and version, with an optional pin."""
    if not isinstance(entries, list):
        raise PacketError("schema packs must be a list")
    out: dict[str, dict[str, str]] = {}
    for e in entries:
        if not isinstance(e, dict) or set(e) - {"id", "version", "sha256"}:
            raise PacketError("a schema packs entry is an object with id, version and sha256")
        if not all(isinstance(e.get(k), str) for k in ("id", "version")):
            raise PacketError("a schema packs entry needs an id and a version")
        if "sha256" in e and not (isinstance(e["sha256"], str) and _PIN.match(e["sha256"])):
            raise PacketError(f"schema packs: the sha256 of {e['id']!r} is not a digest")
        if e["id"] == BASE_ID:
            raise PacketError(f"schema packs: {e['id']!r} is the base pack, which always applies")
        if e["id"] in out and out[e["id"]] != e:
            raise PacketError(f"schema packs: {e['id']!r} is named twice (L7)")
        out[e["id"]] = dict(e)
    return out


def check_template(name: str, t: dict[str, Any]) -> None:
    """Check each member that a template gives, with the rules of a field (SPEC §2.3, §4.9).
    A template has no defaults of its own, so an absent member is not checked."""
    if "type" in t and t["type"] not in _TYPES:
        raise PacketError(f"field {name!r} has unknown type {t['type']!r}")
    if "comparator" in t and t["comparator"] not in _COMPARATORS:
        raise PacketError(f"field {name!r} has unknown comparator {t['comparator']!r}")
    if "unit" in t and t["unit"] is not None and not isinstance(t["unit"], str):
        raise PacketError(f"field {name!r} unit must be a string or null")
    if "description" in t and (
        not isinstance(t["description"], str) or not t["description"].strip()
    ):
        raise PacketError(f"field {name!r} description must be a non-blank string")
    if "aliases" in t:
        _words(name, "aliases", t["aliases"])


def _words(name: str, member: str, words: object) -> None:
    """The rule of keys and aliases: null or a non-empty list of distinct, non-blank strings."""
    if words is None:
        return
    if not isinstance(words, list) or not words or not all(isinstance(k, str) for k in words):
        raise PacketError(f"field {name!r} {member} must be null or a list of strings")
    seen = [fold_text(normalize_ws(k)) for k in words]  # the fold of SPEC §4 (#356)
    if "" in seen or len(set(seen)) != len(seen):
        raise PacketError(f"field {name!r} {member} must be distinct, non-blank text")


def _with_template(name: str, f: object, kinds: dict[str, dict[str, Any]]) -> object:
    """The field with each member that it does not give filled from its template (SPEC §2.3,
    L10). A member that the field gives wins, but a type or a unit must not differ."""
    if not isinstance(f, dict) or "template" not in f:
        return f
    ref = f["template"]
    if not isinstance(ref, str) or "/" not in ref:
        raise PacketError(f"field {name!r}: the template must be '<pack id>/<field>' (L10)")
    pid, tname = ref.split("/", 1)
    if pid not in kinds:
        raise PacketError(f"field {name!r}: {pid!r} is not a kind pack in the schema packs (L10)")
    template = kinds[pid].get("fields", {}).get(tname)
    if template is None:
        raise PacketError(f"field {name!r}: the kind pack {pid!r} has no template {tname!r} (L10)")
    for k in ("type", "unit"):
        if k in f and k in template and f[k] != template[k]:
            raise PacketError(f"field {name!r}: its {k} differs from the template's (L10)")
    return {**copy.deepcopy(template), **f}


def _field(name: str, f: object, kinds: dict[str, dict[str, Any]]) -> Field:
    """A field of the schema. A field that takes a template and then breaks a rule of a field
    makes the packet invalid under L10 (SPEC §2.3)."""
    merged = _with_template(name, f, kinds)
    if merged is f:
        return Field.from_dict(name, f)
    try:
        return Field.from_dict(name, merged)
    except PacketError as e:
        raise PacketError(f"{e}, after the field takes its template (L10)") from None


def _resolve_packs(
    entries: object, given: Sequence[object]
) -> tuple[
    list[dict[str, str]],
    Vocabulary,
    tuple[tuple[str, frozenset[str]], ...],
    dict[str, dict[str, Any]],
    tuple[dict[str, Any], ...],
]:
    """Check each given pack and the union (SPEC §4.8, §4.9). Return the receipt entries, the
    vocabulary, the words of each vocabulary pack and the kind packs that the schema names."""
    if isinstance(given, (str, bytes, dict)) or not isinstance(given, Sequence):
        raise PacketError("packs must be a list of pack objects")
    by_id: dict[str, tuple[dict[str, Any], str]] = {}
    for obj in given:
        p = checked_copy(obj)
        sha = pack_digest(p)
        if p["id"] in by_id:
            other, other_sha = by_id[p["id"]]
            if other["version"] != p["version"]:
                raise PacketError(f"packs: {p['id']!r} is given in two versions (L7)")
            if other_sha != sha:
                raise PacketError(f"packs: two copies of {p['id']!r} have two digests (L7)")
        by_id[p["id"]] = (p, sha)
    built: set[str] = set()

    def load(pid: str, version: str) -> None:
        """A built-in pack that the schema or a kind pack names; the packet never gives it."""
        if pid in BUILT_IN and pid not in by_id:
            p = built_in_pack(pid, version)
            if p is None:
                raise PacketError(f"packs: {pid!r} {version} is not a built-in version")
            by_id[pid] = (p, pack_digest(p))
            built.add(pid)

    named = _pack_entries(entries)
    for pid, e in named.items():
        load(pid, e["version"])
    for pid, e in named.items():
        if pid not in by_id or by_id[pid][0]["version"] != e["version"]:
            raise PacketError(f"schema packs: {pid!r} {e['version']} is not given")
        if "sha256" in e and e["sha256"] != by_id[pid][1]:
            raise PacketError(f"schema packs: {pid!r} has the digest {by_id[pid][1]}, not the pin")
    kinds = {pid: by_id[pid][0] for pid in named if by_id[pid][0]["type"] == "kind"}
    needed: set[str] = set()
    for kid, k in kinds.items():
        for e in k.get("needs", []):
            load(e["id"], e["version"])
            p = by_id.get(e["id"], ({}, ""))[0]
            if not p:
                raise PacketError(f"packs: {kid!r} needs {e['id']!r}, which is not given (L9)")
            if p["type"] != "vocabulary":
                raise PacketError(f"packs: {kid!r} needs {e['id']!r}, a kind pack (L9)")
            if p["version"] != e["version"]:
                raise PacketError(f"packs: {e['id']!r} is named in two versions (L7)")
            needed.add(e["id"])
    for pid in by_id:
        if pid not in named and pid not in needed:
            raise PacketError(f"packs: {pid!r} is given, but the schema does not name it")
    if not by_id:
        return [], BASE_VOCABULARY, (), {}, ()
    ids = sorted(by_id)
    copies = tuple(by_id[i][0] for i in ids if i not in built)
    resolved = [
        {"id": i, "type": by_id[i][0]["type"], "version": by_id[i][0]["version"], "sha256": s}
        for i in ids
        for s in (by_id[i][1],)
    ]
    ids = [i for i in ids if by_id[i][0]["type"] == "vocabulary"]
    if not ids:
        return resolved, BASE_VOCABULARY, (), kinds, copies
    key = tuple(by_id[i][1] for i in ids)
    vocabulary = _VOCABULARIES.get(key)
    if vocabulary is None:
        vocabulary = Vocabulary(combine(BASE, [by_id[i][0] for i in ids]))
        if len(_VOCABULARIES) >= _MAX_VOCABULARIES:
            _VOCABULARIES.clear()
        _VOCABULARIES[key] = vocabulary
    marks = tuple((i, added_words(BASE, by_id[i][0])) for i in ids)
    return resolved, vocabulary, marks, kinds, copies


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
    packs: tuple[str, ...] = ()  # the ids of the packs that the decision read (SPEC §5)

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
            "packs": list(self.packs),
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
class RelationResult:
    """A relation that applied at one relation key (SPEC §3.4, §5)."""

    id: str
    key: str | None
    holds: bool
    difference: str  # canonical decimal
    allowance: str  # canonical decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "holds": self.holds,
            "difference": self.difference,
            "allowance": self.allowance,
        }


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
    relations: tuple[RelationResult, ...] | None = None  # None when the schema has no relations
    packs: tuple[dict[str, str], ...] = ()  # the packs that applied, sorted by id (SPEC §5)

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
            "packs": [dict(p) for p in self.packs],
            "schema_sha256": self.schema_sha256,
            "policy_sha256": self.policy_sha256,
            "decisions": [d.to_dict() for d in self.decisions],
            "coverage": [{"field": f, "code": c} for f, c in self.coverage],
            "judgments": [j.to_dict() for j in self.judgments],
            **(
                {}
                if self.relations is None
                else {"relations": [r.to_dict() for r in self.relations]}
            ),
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
    "to the number. field: words that name the field, such as a row label."
)
_KEY_HELP = " key: words that name the key, such as a column heading."


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
    schema: Schema | dict[str, Any],
    reference_ids: list[str] | None = None,
    packs: Sequence[object] = (),
) -> dict[str, Any]:
    """A JSON Schema for an extractor's structured output: {"candidates": [...]} for one schema.

    It uses only the JSON Schema subset of the strict structured-output modes, and every
    candidate that it accepts passes step 1 of SPEC §3. Three step 1 rules stay outside it: two
    items with the same role other than field, more than 8 field items, and a blank text, url or
    retrieved. A field with
    no keys gets no role "key", because a key item on it always fails (SPEC §4.6). ``packs``
    are the vocabulary packs that the schema names (SPEC §4.8).
    """
    s = schema if isinstance(schema, Schema) else Schema.from_dict(schema, packs)
    if not s.fields:
        raise PacketError("the schema has no fields, so an extractor can send no candidate")
    if reference_ids is not None and (
        not reference_ids
        or not all(isinstance(r, str) and r.strip() for r in reference_ids)
        or len(set(reference_ids)) != len(reference_ids)
    ):
        raise PacketError("reference_ids must be a non-empty list of unique non-blank strings")
    quote = {"type": "string", "description": "Copied verbatim from the text."}
    # a field with no keys gets no role "key": a key item on it always fails (SPEC 4.6, #256).
    # When the schema has both kinds of field, the evidence of a field with no keys is a second
    # definition, with the suffix "_no_key".
    keyed = sorted({f.keys is not None for f in s.fields.values()}, reverse=True)
    suffix = {k: "" if k == keyed[0] else "_no_key" for k in keyed}
    kinds: dict[str, dict[str, Any]] = {}
    for k in keyed:
        role = {
            "enum": ["value", "sign", "scale", "unit", "field", *(["key"] if k else [])],
            "description": _ROLE_HELP + (_KEY_HELP if k else ""),
        }
        kinds["document" + suffix[k]] = _closed(
            {"source": {"const": "document"}, "role": role, "text": quote},
            "A quote from the document.",
        )
        if reference_ids:
            kinds["reference" + suffix[k]] = _closed(
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
    # one evidence definition for each kind of field: strict modes count each anyOf against a
    # limit per request
    shared = ("external", "knowledge")
    evidence = {
        "evidence" + suffix[k]: {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": f"#/$defs/{n}"}
                    for n in kinds
                    if n in shared or n in ("document" + suffix[k], "reference" + suffix[k])
                ]
            },
        }
        for k in keyed
    }
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
                    "evidence": {"$ref": f"#/$defs/evidence{suffix[f.keys is not None]}"},
                },
                description or None,
            )
        )
    # no "$schema" member: the Claude CLI's --json-schema check does not load draft 2020-12 (#197)
    return {
        **_closed(
            {
                "candidates": {
                    "type": "array",
                    "items": cands[0] if len(cands) == 1 else {"anyOf": cands},
                }
            }
        ),
        "$defs": {**kinds, **evidence},
    }
