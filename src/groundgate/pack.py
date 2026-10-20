"""Vocabulary packs (SPEC §4.7, §4.8): the base pack ``en``, the loader checks and the union."""

from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import re
import stat
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from importlib import resources
from pathlib import Path
from typing import Any

from .canonical import jcs
from .fold import fold_text, folded_word, mark_fold


class PacketError(ValueError):
    """The inputs themselves are invalid (SPEC §2): no receipt can be produced."""


BASE_ID = "en"
BASE_VERSION = "1.1.0"
# the digest of the base pack that SPEC §4.7 gives for this spec version
BASE_SHA256 = "sha256:15fb3c027b33e5aa83561ef894053a54f7c7e469825960c50266c6d0f03e6f0c"
# each released version of a built-in pack other than the base, with the digest that SPEC §4.8
# gives. A schema names one by id and version, and the packet never gives it (#336). The kind
# packs and electronics hold the knowledge of the bench schemas (#337).
BUILT_IN_SHA256 = {
    ("finance", "1.0.0"): "sha256:822c91124cbd23f29e683873975d4f3f85f2207dbbb02ca3664f0ef74848162b",
    ("electronics", "1.0.0"): (
        "sha256:af8570f97b8e06fcceae56949a6e3b5ffab4992413cf8b6f474b6239989dbc5b"
    ),
    ("us-10k", "1.0.0"): "sha256:ea4115fd9215c89b78369cd1291cf8482cb185602e037c076a8c17c8edbab102",
    ("us-government-reports", "1.0.0"): (
        "sha256:604297bba0b9543fae9d3099eaa6a810f2bdb0fcd0cf5f527d6903b374e44974"
    ),
    ("annual-reports", "1.0.0"): (
        "sha256:ca2433ec6dd249581310c977b29a54b4c70aa65acd3561701285a2f4ccf150e7"
    ),
    ("component-datasheets", "1.0.0"): (
        "sha256:3b0ac7d8b1dff0f25a33078c668739086b027704e75b7d4deba9a6ebf9c27538"
    ),
    ("benefit-summaries", "1.0.0"): (
        "sha256:a01109e7c7a72e248012161d8fe16b1937a77e09c328a6cdcbfd0e9d41ebe3d2"
    ),
}
BUILT_IN = frozenset({BASE_ID, *(pid for pid, _ in BUILT_IN_SHA256)})  # (SPEC §4.8, L7)
# the released built-in versions that ``admit`` refuses. A retired version stays in
# BUILT_IN_SHA256 and in the wheel, and ``verify`` still loads it, so that an old receipt that
# names it still verifies (docs/design/packs.md §6, §11). No version is retired in 0.10.
RETIRED: frozenset[tuple[str, str]] = frozenset()

FORMAT = 1
MAX_FILE = 1 << 20  # bytes of a pack file, before the loader parses it (L4)
MAX_CANONICAL = 256 << 10  # bytes of a pack as canonical JSON (L4)
MAX_DEPTH = 8  # the JSON nesting depth: the pack object is depth 1 (L4)
MAX_ENTRIES = 2000  # the entries of one list or object (L4)
MAX_WORD = 64  # the code points of one word (L3)
MAX_INT = 2**53  # an integer of a pack is at most this, as in JSON (L2)
POWERS = frozenset({3, 5, 6, 7, 9, 12})  # the powers of ten of a scale (L6)
COMPARATORS = ("approx", "gt", "lt", "ge", "le", "range")

_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_HEADING_CODE = re.compile(r"[A-Z]{3}\Z")
# a field name, and the name of a field template (SPEC §2.3, spec 0.11, #359)
_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def is_field_name(name: object) -> bool:
    """True when ``name`` follows the rule of a field name (SPEC §2.3): 1 to 64 characters, each
    a lowercase ASCII letter, a digit or "_", and a letter first."""
    return type(name) is str and _FIELD_NAME.match(name) is not None


# format 1 of a vocabulary pack: each group and its lists (SPEC §4.8). "words" is a list of
# words, "powers" an object from a word to a power of ten, "comparators" an object from a
# comparator to a list of phrases.
_GROUPS: dict[str, dict[str, str]] = {
    "scale": {"words": "powers", "suffixes": "powers", "currency": "powers"},
    "qualifiers": {"before": "comparators", "after": "comparators", "negations": "words"},
    "ranges": {"connectors": "words", "pair": "words"},
    "changes": {"words": "words", "determiners": "words", "stop_words": "words"},
    "sentence": {"abbreviations": "words", "join_always": "words", "join_before_code": "words"},
    "sign": {"loss": "words", "gain": "words", "negations": "words"},
}
_TOP_LISTS = {
    "currency_signs": "words",
    "units": "units",
    "per_units": "words",
    "null_literals": "words",
    "heading_units": "headings",
}
_HEAD = ("groundgate_pack", "type", "id", "version", "description", "status")
# format 1 of a kind pack (SPEC §4.9): the head, the vocabulary packs that it needs, and the
# field templates. A template holds only these members of a field (SPEC §2.3).
_KIND = ("needs", "fields")
TEMPLATE_MEMBERS = ("type", "unit", "comparator", "aliases", "description")
MAX_TEMPLATES = 200  # the field templates of one kind pack (L4)
MAX_DIR_FILES = 256  # the .json files that verify reads from one pack folder
# the lists that only the base pack gives: a word there cancels a flag (SPEC §4.8, L5)
BASE_ONLY = frozenset(
    {
        ("qualifiers", "negations"),
        ("ranges", "pair"),
        ("changes", "words"),
        ("changes", "determiners"),
        ("sentence", "join_always"),
        ("sentence", "join_before_code"),
    }
)
_STATUS_ROW = {"kind", "field", "code", "status", "documents", "bound", "limit", "results"}


def with_defaults(pack: dict[str, Any]) -> dict[str, Any]:
    """The pack with each absent list empty and each absent text empty (SPEC §4.8). The digest
    and the union read this form."""
    out: dict[str, Any] = {k: pack[k] for k in ("groundgate_pack", "type", "id", "version")}
    out["description"] = pack.get("description", "")
    out["status"] = pack.get("status", [])
    if pack["type"] == "kind":
        out["needs"] = pack.get("needs", [])
        out["fields"] = pack.get("fields", {})
        return out
    for group, lists in _GROUPS.items():
        given = pack.get(group, {})
        out[group] = {
            name: given.get(name, [] if kind == "words" else {}) for name, kind in lists.items()
        }
    for name, kind in _TOP_LISTS.items():
        out[name] = pack.get(name, [] if kind == "words" else {})
    out["units"] = {
        code: {"prefixes": u.get("prefixes", []), "suffixes": u.get("suffixes", [])}
        for code, u in out["units"].items()
    }
    out["heading_units"] = {
        code: {"names": u.get("names", []), "sign": u.get("sign")}
        for code, u in out["heading_units"].items()
    }
    return out


def pack_digest(pack: dict[str, Any]) -> str:
    """The digest of a pack after defaults (SPEC §4.7). The prefix names the pack format, not
    the spec version, so one pack has one digest under each spec version."""
    prefix = f"groundgate-pack/1:{pack['type']}\0".encode("ascii")
    payload = jcs(with_defaults(pack)).encode("utf-8", "surrogatepass")
    return "sha256:" + hashlib.sha256(prefix + payload).hexdigest()


# ------------------------------------------------------------------- the checks


def _fail(pack: object, msg: str) -> PacketError:
    name = pack.get("id") if isinstance(pack, dict) else None
    return PacketError(f"pack {name!r}: {msg}" if isinstance(name, str) else f"pack: {msg}")


def _check_data(pack: object) -> None:
    """L2, and the depth and entry limits of L4, with no recursion: only strings, integers,
    null, lists and objects with string keys. Each type must be exact: a subclass can give
    another answer when it is read again (#334). JSON cannot give one list or object at two
    places, so a container that occurs twice is not data: the walk stays linear."""
    stack: list[tuple[object, int]] = [(pack, 1)]
    seen: set[int] = set()
    while stack:
        obj, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise _fail(pack, f"the JSON nesting depth is more than {MAX_DEPTH} (L4)")
        kind = type(obj)
        if kind is dict or kind is list:
            if id(obj) in seen:
                raise _fail(pack, "a list or an object occurs at two places (L2)")
            seen.add(id(obj))
        if kind is dict:
            assert isinstance(obj, dict)
            if len(obj) > MAX_ENTRIES:
                raise _fail(pack, f"an object has more than {MAX_ENTRIES} entries (L4)")
            for k, v in obj.items():
                if type(k) is not str:
                    raise _fail(pack, "an object key is not a string (L2)")
                stack.append((v, depth + 1))
        elif kind is list:
            assert isinstance(obj, list)
            if len(obj) > MAX_ENTRIES:
                raise _fail(pack, f"a list has more than {MAX_ENTRIES} entries (L4)")
            stack.extend((v, depth + 1) for v in obj)
        elif not (obj is None or kind is str or kind is int):
            raise _fail(pack, f"a value of type {kind.__name__} is not data (L2)")
        elif kind is int and abs(obj) > MAX_INT:  # type: ignore[arg-type]
            raise _fail(pack, "an integer is out of the range of JSON (L2)")


def _word(pack: dict[str, Any], w: object, where: str) -> str:
    """L3: one word of a list."""
    if not isinstance(w, str):
        raise _fail(pack, f"{where}: a word must be a string (L2)")
    if not w.strip():
        raise _fail(pack, f"{where}: a word is blank (L3)")
    if w != w.strip() or any(ch in w for ch in "\n\r\t"):
        raise _fail(pack, f"{where}: {w!r} has whitespace at an end, a line break or a tab (L3)")
    if unicodedata.normalize("NFC", w) != w:
        raise _fail(pack, f"{where}: {w!r} is not NFC (L3)")
    if len(w) > MAX_WORD:
        raise _fail(pack, f"{where}: a word has more than {MAX_WORD} code points (L3)")
    return w


def _words(pack: dict[str, Any], v: object, where: str) -> list[str]:
    if not isinstance(v, list):
        raise _fail(pack, f"{where} must be a list of words (L1)")
    return [_word(pack, w, where) for w in v]


def _object(pack: dict[str, Any], v: object, keys: Iterable[str], where: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise _fail(pack, f"{where} must be an object (L1)")
    unknown = set(v) - set(keys)
    if unknown:
        raise _fail(pack, f"{where} has members that the format does not list: {sorted(unknown)}")
    return v


def _lowercase(pack: dict[str, Any], words: Iterable[str], where: str) -> None:
    for w in words:
        if w != w.lower():
            raise _fail(pack, f"{where}: {w!r} must be in lowercase (L3)")


def _sign(s: object) -> bool:
    """One code point that is not a letter, a number, a separator or a control character."""
    return isinstance(s, str) and len(s) == 1 and unicodedata.category(s)[0] not in "LNZC"


def _check_list(pack: dict[str, Any], where: str, kind: str, v: object) -> None:
    if kind == "words":
        _words(pack, v, where)
    elif kind == "powers":
        if not isinstance(v, dict):
            raise _fail(pack, f"{where} must be an object from a word to a power (L1)")
        for w, p in v.items():
            _word(pack, w, where)
            if not isinstance(p, int) or isinstance(p, bool):
                raise _fail(pack, f"{where}: the power of {w!r} must be an integer (L2)")
        _lowercase(pack, v, where)
    elif kind == "comparators":
        for c, phrases in _object(pack, v, COMPARATORS, where).items():
            _words(pack, phrases, f"{where}.{c}")
    elif kind == "units":
        if not isinstance(v, dict):
            raise _fail(pack, f"{where} must be an object from a unit code to its forms (L1)")
        for code, forms in v.items():
            _word(pack, code, where)
            sides = _object(pack, forms, ("prefixes", "suffixes"), f"{where}.{code}")
            for side, words in sides.items():
                _words(pack, words, f"{where}.{code}.{side}")
    else:  # headings
        if not isinstance(v, dict):
            raise _fail(pack, f"{where} must be an object from a currency code (L1)")
        for code, u in v.items():
            if not _HEADING_CODE.match(code):
                raise _fail(pack, f"{where}: {code!r} is not a code of three capitals (L3)")
            u = _object(pack, u, ("names", "sign"), f"{where}.{code}")
            _words(pack, u.get("names", []), f"{where}.{code}.names")
            sign = u.get("sign")
            if sign is not None and not _sign(sign):
                raise _fail(pack, f"{where}.{code}: the sign must be one currency sign or null")


def _check_status(pack: dict[str, Any], rows: object, built_in: bool) -> None:
    """L8: the status table of the pack."""
    if not isinstance(rows, list):
        raise _fail(pack, "status must be a list of rows (L8)")
    for row in rows:
        if not isinstance(row, dict) or set(row) - _STATUS_ROW:
            raise _fail(pack, "a status row is malformed (L8)")
        for k in ("kind", "field", "code", "status"):
            if not isinstance(row.get(k), str) or not row[k]:
                raise _fail(pack, f"a status row has no {k} (L8)")
        for k in ("bound", "limit", "results"):
            if k in row and not isinstance(row[k], str):
                raise _fail(pack, f"the {k} of a status row must be a string (L8)")
        if "documents" in row and (type(row["documents"]) is not int or row["documents"] < 0):
            raise _fail(pack, "the documents of a status row must be a count (L8)")
        if row["status"] not in ("draft", "measured"):
            raise _fail(pack, f"a status row has the status {row['status']!r} (L8)")
        if row["status"] == "measured" and not built_in:
            raise _fail(pack, "a pack that is not built in has a measured row (L8)")
        if row["status"] == "measured" and not ("results" in row and "bound" in row):
            raise _fail(pack, "a measured row has no results file or no bound (L8)")


def check_pack(pack: object, *, built_in: bool = False) -> dict[str, Any]:
    """Run the checks L1 to L5, L7 to L9 and L12 on one pack (SPEC §4.8, §4.9), and return
    the pack. L6 runs on the union, in ``combine``, and L10 on the schema. L11: the digest is
    computed, never read from a pack."""
    _check_data(pack)
    if not isinstance(pack, dict):
        raise PacketError("pack: a pack must be a JSON object (L1)")
    if len(jcs(pack).encode("utf-8", "surrogatepass")) > MAX_CANONICAL:
        raise _fail(pack, f"the pack is more than {MAX_CANONICAL} bytes as canonical JSON (L4)")
    fmt = pack.get("groundgate_pack")
    if isinstance(fmt, bool) or fmt != FORMAT:
        raise _fail(pack, f"groundgate_pack must be {FORMAT} (L1)")
    if pack.get("type") not in ("vocabulary", "kind"):
        raise _fail(pack, "type must be 'vocabulary' or 'kind' (L1)")
    members = {*_HEAD, *_KIND} if pack["type"] == "kind" else {*_HEAD, *_GROUPS, *_TOP_LISTS}
    unknown = set(pack) - members
    if unknown:
        raise _fail(pack, f"members that the format does not list: {sorted(unknown)} (L1, L12)")
    pid, version = pack.get("id"), pack.get("version")
    if not isinstance(pid, str) or len(pid) > MAX_WORD or not _ID.match(pid):
        raise _fail(pack, "the id must be lowercase letters and digits with single '-' (L7)")
    if not isinstance(version, str) or not _VERSION.match(version):
        raise _fail(pack, "the version must be MAJOR.MINOR.PATCH (L7)")
    if not built_in and pid in BUILT_IN:
        raise _fail(pack, "a given pack has the id of a built-in pack (L7)")
    if not built_in and "-x-" not in pid:
        raise _fail(pack, "the id of an app's own pack must hold an '-x-' name (L7)")
    if not isinstance(pack.get("description", ""), str):
        raise _fail(pack, "description must be a text (L1)")
    _check_status(pack, pack.get("status", []), built_in)
    if pack["type"] == "kind":
        _check_kind(pack)
        return pack
    for group, lists in _GROUPS.items():
        for name, v in _object(pack, pack.get(group, {}), lists, group).items():
            if not built_in and (group, name) in BASE_ONLY:
                raise _fail(pack, f"{group}.{name} is a list that only the base pack gives (L5)")
            _check_list(pack, f"{group}.{name}", lists[name], v)
    for name, kind in _TOP_LISTS.items():
        if name in pack:
            _check_list(pack, name, kind, pack[name])
    for sign in pack.get("currency_signs", []):
        if not _sign(sign):
            raise _fail(pack, f"currency_signs: {sign!r} is not one currency sign (L3)")
    _lowercase(pack, pack.get("null_literals", []), "null_literals")
    sentence = pack.get("sentence", {})
    for name in ("abbreviations", "join_always", "join_before_code"):
        _lowercase(pack, sentence.get(name, []), f"sentence.{name}")
        for w in sentence.get(name, []):
            if not w.endswith("."):
                raise _fail(pack, f"sentence.{name}: {w!r} must end with a dot (L3)")
    return pack


def _check_kind(pack: dict[str, Any]) -> None:
    """L4 and L9: the needs and the field templates of a kind pack (SPEC §4.9)."""
    from .model import check_template  # the rules of a field (SPEC §2.3); model imports this

    needs = pack.get("needs", [])
    if type(needs) is not list:
        raise _fail(pack, "needs must be a list (L9)")
    seen: set[str] = set()
    for e in needs:
        if type(e) is not dict or set(e) != {"id", "version"}:
            raise _fail(pack, "a needs entry is an object with only id and version (L9)")
        if type(e["id"]) is not str or not _ID.match(e["id"]):
            raise _fail(pack, "a needs entry has an id of the wrong form (L7)")
        if type(e["version"]) is not str or not _VERSION.match(e["version"]):
            raise _fail(pack, "a needs entry has a version that is not MAJOR.MINOR.PATCH (L7)")
        if e["id"] == BASE_ID:
            raise _fail(pack, f"needs names {e['id']!r}, the base pack, which always applies (L9)")
        if e["id"] in seen or e["id"] == pack["id"]:
            raise _fail(pack, f"needs names {e['id']!r} twice, or names the pack itself (L9)")
        seen.add(e["id"])
    fields = pack.get("fields", {})
    if type(fields) is not dict:
        raise _fail(pack, "fields must be an object of field templates (L9)")
    if len(fields) > MAX_TEMPLATES:
        raise _fail(pack, f"a kind pack has more than {MAX_TEMPLATES} field templates (L4)")
    for name, t in fields.items():
        if not is_field_name(name):
            raise _fail(pack, f"template name {name!r} breaks the field name rule of §2.3 (L9)")
        if type(t) is not dict or set(t) - set(TEMPLATE_MEMBERS):
            raise _fail(pack, f"template {name!r} holds another member than the five (L9)")
        try:
            check_template(name, t)
        except PacketError as e:
            raise _fail(pack, f"template {name!r} breaks the rules of a field: {e} (L9)") from None


def checked_copy(pack: object) -> dict[str, Any]:
    """A copy of a given pack, after the checks. The copy is made from exact JSON types, and
    the checks run on the copy, so a change of ``pack`` after this call has no effect."""
    _check_data(pack)
    return check_pack(copy.deepcopy(pack))


def _no_twice(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(set(keys)) != len(keys):
        raise PacketError("pack: an object has one key twice (L1)")
    return dict(pairs)


def load_pack(path: str | Path) -> dict[str, Any]:
    """Read a pack file and run the checks of SPEC §4.8 on it. A file of more than 1 MiB is
    refused before it is parsed. Raises ``PacketError``."""
    if not Path(path).is_file():
        raise PacketError(f"pack file {str(path)!r} is not a file")
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE + 1)
    except OSError as e:
        raise PacketError(f"pack file {str(path)!r} cannot be read: {e}") from None
    return _parse(data, str(path))


def _parse(data: bytes, name: str) -> dict[str, Any]:
    """The bytes of one pack file, after the checks of SPEC §4.8 (L4 size first)."""
    if len(data) > MAX_FILE:
        raise PacketError(f"pack file {name!r} is more than {MAX_FILE} bytes (L4)")
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_twice)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        if isinstance(e, PacketError):
            raise
        raise PacketError(f"pack file {name!r} is not JSON: {e}") from None
    try:
        return check_pack(obj)
    except PacketError as e:
        raise PacketError(f"pack file {name!r}: {e}") from None


# -------------------------------------------------------------------- the union


def _key(w: str) -> str:
    """A word as the conflict checks compare it (L6): each letter folded (SPEC §4), each
    whitespace run one space."""
    return " ".join(fold_text(w).split())


def _added(base: Sequence[str], words: Iterable[str]) -> list[str]:
    """``base`` in its order, then each new word longest first, then by code point. So the
    order of the packs never changes a match (SPEC §4.8)."""
    seen = set(base)
    new = sorted({w for w in words if w not in seen}, key=lambda w: (-len(w), w))
    return [*base, *new]


def _powers(base: dict[str, int], more: Iterable[dict[str, int]], where: str) -> dict[str, int]:
    out = dict(base)
    for m in more:
        for w, p in m.items():
            if out.setdefault(w, p) != p:
                raise PacketError(f"packs: {where}: {w!r} has two powers of ten (L6)")
    return {w: out[w] for w in _added(list(base), out)}


def _phrase_re(p: str) -> re.Pattern[str]:
    """A qualifier phrase as SPEC §4.2 matches it: each letter by its fold (SPEC §4)."""
    body = r"\s+".join(folded_word(w) for w in p.split())
    return re.compile(body if not p[0].isalnum() else rf"\b{body}\b")


def _qualifier_conflicts(base: dict[str, Any], merged: dict[str, Any]) -> None:
    """L6 for the qualifiers: a phrase in two comparator lists, or a phrase from a pack that
    holds a phrase of another comparator or is held in one."""
    for side in ("before", "after"):
        lists: dict[str, list[str]] = merged["qualifiers"][side]
        owner: dict[str, str] = {}
        for c, phrases in lists.items():
            for p in phrases:
                if owner.setdefault(_key(p), c) != c:
                    raise PacketError(f"packs: {p!r} is in two comparator lists (L6)")
        own = {c: set(ps) for c, ps in base["qualifiers"][side].items()}
        for c, phrases in lists.items():
            for p in (p for p in phrases if p not in own.get(c, set())):
                for d, others in lists.items():
                    for q in others if d != c else ():
                        if _phrase_re(q).search(p) or _phrase_re(p).search(q):
                            raise PacketError(
                                f"packs: the {c} phrase {p!r} overlaps the {d} phrase {q!r} (L6)"
                            )


def _cased(suffix: str) -> list[str]:
    """A scale suffix as the core matches it: "bn", "Bn", "BN" (SPEC §4.1)."""
    return list(dict.fromkeys([suffix, suffix.capitalize(), suffix.upper()]))


def combine(base: dict[str, Any], packs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The union of the base pack and the given packs, after the check L6 (SPEC §4.8). With no
    pack, the result is the base pack after defaults."""
    b = with_defaults(base)
    ps = [with_defaults(p) for p in packs]
    out = dict(b)
    for group, lists in _GROUPS.items():
        out[group] = {}
        for name, kind in lists.items():
            if kind == "words":
                out[group][name] = _added(b[group][name], (w for p in ps for w in p[group][name]))
            elif kind == "powers":
                more = [p[group][name] for p in ps]
                out[group][name] = _powers(b[group][name], more, f"{group}.{name}")
            else:
                sides = {c: list(v) for c, v in b[group][name].items()}
                for c in COMPARATORS:
                    added = [w for p in ps for w in p[group][name].get(c, [])]
                    if added or c in sides:
                        sides[c] = _added(sides.get(c, []), added)
                out[group][name] = sides
    for name in ("currency_signs", "per_units", "null_literals"):
        out[name] = _added(b[name], (w for p in ps for w in p[name]))
    codes = _added(list(b["units"]), (c for p in ps for c in p["units"]))
    out["units"] = {
        code: {
            side: _added(
                b["units"].get(code, {}).get(side, []),
                (w for p in ps for w in p["units"].get(code, {}).get(side, [])),
            )
            for side in ("prefixes", "suffixes")
        }
        for code in codes
    }
    out["heading_units"] = {}
    for code in _added(list(b["heading_units"]), (c for p in ps for c in p["heading_units"])):
        given = [x["heading_units"][code] for x in (b, *ps) if code in x["heading_units"]]
        signs = {g["sign"] for g in given if g["sign"] is not None}
        if len(signs) > 1:
            raise PacketError(f"packs: the currency {code} has two signs (L6)")
        out["heading_units"][code] = {
            "names": _added(given[0]["names"], (n for g in given[1:] for n in g["names"])),
            "sign": next(iter(signs), None),
        }
    if ps:
        _conflicts(b, out)
    return out


def _conflicts(base: dict[str, Any], m: dict[str, Any]) -> None:
    """L6 after the union."""
    scale = m["scale"]
    for name in ("words", "suffixes", "currency"):
        for w, p in scale[name].items():
            if p not in POWERS:
                raise PacketError(
                    f"packs: scale.{name}: {w!r} has the power {p}, not 3, 5, 6, 7, 9 or 12 (L6)"
                )
    for w in set(scale["suffixes"]) & set(scale["currency"]):
        if scale["suffixes"][w] != scale["currency"][w]:
            raise PacketError(f"packs: the scale form {w!r} has two powers of ten (L6)")
    form_code: dict[str, str] = {}
    for code, forms in m["units"].items():
        for w in dict.fromkeys([*forms["prefixes"], *forms["suffixes"]]):
            if form_code.setdefault(w, code) != code:
                raise PacketError(
                    f"packs: the unit form {w!r} is under {form_code[w]} and {code} (L6)"
                )
    unit_suffixes = {w for forms in m["units"].values() for w in forms["suffixes"]}
    for s in scale["suffixes"]:
        if set(_cased(s)) & unit_suffixes:
            raise PacketError(f"packs: the scale suffix {s!r} is also a unit suffix (L6)")
    loss = {_key(w) for w in m["sign"]["loss"]}
    both = loss & {_key(w) for w in m["sign"]["gain"]}
    if both:
        raise PacketError(f"packs: {sorted(both)} are loss words and gain words (L6)")
    name_code: dict[str, str] = {}
    for code, u in m["heading_units"].items():
        for n in u["names"]:
            if name_code.setdefault(_key(n), code) != code:
                raise PacketError(f"packs: the currency name {n!r} is under two codes (L6)")
    _qualifier_conflicts(base, m)


def _entries(pack: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """Each word of a pack after defaults, with the list that holds it."""
    for group, lists in _GROUPS.items():
        for name, kind in lists.items():
            v = pack[group][name]
            if kind == "comparators":
                yield from ((f"{group}.{name}.{c}", w) for c, ws in v.items() for w in ws)
            else:
                yield from ((f"{group}.{name}", w) for w in v)
    for name in ("currency_signs", "per_units", "null_literals"):
        yield from ((name, w) for w in pack[name])
    for code, u in pack["units"].items():
        for side in ("prefixes", "suffixes"):
            yield from ((f"units.{code}.{side}", w) for w in u[side])
    for code, u in pack["heading_units"].items():
        yield f"heading_units.{code}", code
        yield from ((f"heading_units.{code}.names", w) for w in u["names"])
        if u["sign"] is not None:
            yield f"heading_units.{code}.sign", u["sign"]


def added_words(base: dict[str, Any], pack: dict[str, Any]) -> frozenset[str]:
    """The words that a pack adds to the base, as ``mark_fold`` gives them. A word that the base
    gives in the same list is not added (SPEC §5, decision packs)."""
    have = set(_entries(with_defaults(base)))
    return frozenset(
        mark_fold(w) for path, w in _entries(with_defaults(pack)) if (path, w) not in have
    )


def _load_base() -> dict[str, Any]:
    """The base pack. A file with another digest stops the import, because then the text rules
    are not the rules of this spec version."""
    path = resources.files("groundgate") / "packs" / BASE_ID / f"{BASE_VERSION}.json"
    pack: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    found = pack_digest(pack)
    if found != BASE_SHA256:
        raise RuntimeError(
            f"base pack {BASE_ID} {BASE_VERSION} has digest {found}, not {BASE_SHA256}"
        )
    return check_pack(pack, built_in=True)


BASE = _load_base()
_LOADED: dict[tuple[str, str], dict[str, Any]] = {}


def built_in_pack(pid: str, version: str) -> dict[str, Any] | None:
    """A built-in pack other than the base, or None when this version is not built in. A file
    with another digest than the released one stops the call (SPEC §4.8)."""
    want = BUILT_IN_SHA256.get((pid, version))
    if want is None:
        return None
    if (pid, version) not in _LOADED:
        path = resources.files("groundgate") / "packs" / pid / f"{version}.json"
        pack: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        found = pack_digest(pack)
        if found != want:
            raise RuntimeError(f"built-in pack {pid} {version} has digest {found}, not {want}")
        _LOADED[(pid, version)] = check_pack(pack, built_in=True)
    return copy.deepcopy(_LOADED[(pid, version)])  # a caller cannot change the cached pack


# ------------------------------------------------------- verify: the packs of a receipt

_VERIFYING: ContextVar[bool] = ContextVar("groundgate_verifying", default=False)
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")


@contextmanager
def reading_retired() -> Iterator[None]:
    """In this block, a schema can name a retired built-in version. Only ``verify`` uses it, to
    re-derive an old receipt (docs/design/packs.md §11)."""
    token = _VERIFYING.set(True)
    try:
        yield
    finally:
        _VERIFYING.reset(token)


def check_retired(pid: str, version: str) -> None:
    """``admit`` refuses a retired built-in version. ``verify`` still reads it."""
    if (pid, version) in RETIRED and not _VERIFYING.get():
        raise PacketError(f"packs: {pid!r} {version} is a retired built-in version")


def _read_in(dfd: int, name: str) -> bytes | str:
    """The bytes of the file ``name`` in the open folder ``dfd``, or the reason why it is not
    read. The open never follows a link, so a link cannot point out of the folder."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(name, flags, dir_fd=dfd)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.EMLINK):  # EMLINK: O_NOFOLLOW on a link in BSD
            return "is a link, and verify does not follow links"
        return f"cannot be opened ({e.strerror})"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            return "is not a regular file"
        if st.st_size > MAX_FILE:
            return f"is more than {MAX_FILE} bytes (L4)"
        chunks: list[bytes] = []
        size = 0
        while size <= MAX_FILE:  # the file can grow after fstat: read at most MAX_FILE + 1
            chunk = os.read(fd, MAX_FILE + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    except OSError as e:
        return f"cannot be read ({e.strerror})"
    finally:
        os.close(fd)


def _read_dir(
    path: str | os.PathLike[str], wanted: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str], set[str]], list[str]]:
    """Read each ``.json`` file directly in the folder ``path``, which is untrusted. Return the
    packs whose digest is in ``wanted``, the digests of each id and version, and each file that
    is not a valid pack with the reason. A file is checked as ``load_pack`` checks it."""
    if not (os.open in os.supports_dir_fd and os.listdir in os.supports_fd):
        raise PacketError("this system cannot read a pack folder safely: give each pack file")
    try:
        dfd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError as e:
        raise PacketError(f"pack folder {str(path)!r} cannot be opened ({e.strerror})") from None
    by_sha: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str], set[str]] = {}
    skipped: list[str] = []
    try:
        if not stat.S_ISDIR(os.fstat(dfd).st_mode):
            raise PacketError(f"pack folder {str(path)!r} is not a folder")
        names = sorted(n for n in os.listdir(dfd) if n.endswith(".json"))
        if len(names) > MAX_DIR_FILES:
            raise PacketError(
                f"pack folder {str(path)!r} holds more than {MAX_DIR_FILES} .json files"
            )
        for name in names:
            data = _read_in(dfd, name)
            if isinstance(data, str):
                skipped.append(f"{name!r} {data}")
                continue
            try:
                p = _parse(data, name)
            except PacketError as e:
                skipped.append(str(e))
                continue
            sha = pack_digest(p)  # the digest is computed here, never read from the file (L11)
            by_key.setdefault((p["id"], p["version"]), set()).add(sha)
            if sha in wanted:
                by_sha.setdefault(sha, p)
    finally:
        os.close(dfd)
    return by_sha, by_key, skipped


def _entry(e: object) -> bool:
    """An entry of the receipt member ``packs`` (SPEC §5) with each member of the right form."""
    return (
        isinstance(e, Mapping)
        and set(e) == {"id", "type", "version", "sha256"}
        and all(isinstance(e[k], str) for k in e)
        and len(e["id"]) <= MAX_WORD
        and _ID.match(e["id"]) is not None
        and _VERSION.match(e["version"]) is not None
        and e["type"] in ("vocabulary", "kind")
        and _SHA.match(e["sha256"]) is not None
    )


def receipt_packs(
    entries: object,
    given: Sequence[dict[str, Any]],
    pack_dir: str | os.PathLike[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Steps 1 to 3 of docs/design/packs.md §11: find each pack that a receipt names, by id,
    version and digest. ``given`` holds the checked given packs. Return the packs from
    ``pack_dir`` that the receipt names, and the problems. A pack from the folder is returned
    only when its computed digest is the digest in the receipt."""
    if not isinstance(entries, list) or not all(_entry(e) for e in entries):
        return [], ["the receipt member packs is not a list of pack entries"]
    have = {(p["id"], p["version"]): pack_digest(p) for p in given}
    problems: list[str] = []
    missing: list[Mapping[str, str]] = []
    for e in entries:
        key = (e["id"], e["version"])
        where = "built-in" if key in BUILT_IN_SHA256 else "given"
        other = BUILT_IN_SHA256.get(key) or have.get(key)
        if other is None:
            missing.append(e)
        elif other != e["sha256"]:
            problems.append(
                f"pack {e['id']!r} {e['version']}: the receipt names the digest {e['sha256']}, "
                f"and the {where} pack has the digest {other}"
            )
    by_sha: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str], set[str]] = {}
    skipped: list[str] = []
    if missing and pack_dir is not None:
        by_sha, by_key, skipped = _read_dir(pack_dir, {e["sha256"] for e in missing})
    found: list[dict[str, Any]] = []
    lost = False
    for e in missing:
        key, sha = (e["id"], e["version"]), e["sha256"]
        p = by_sha.get(sha)
        if p is not None and (p["id"], p["version"]) == key:
            found.append(p)
            continue
        lost = True
        if by_key.get(key):
            problems.append(
                f"pack {e['id']!r} {e['version']}: the receipt names the digest {sha}, and the "
                f"pack folder has only the digest {', '.join(sorted(by_key[key]))}"
            )
            continue
        place = ", not given and not in the pack folder" if pack_dir is not None else " or given"
        problems.append(
            f"pack {e['id']!r} {e['version']} with the digest {sha} is not built in{place}"
        )
    if lost and skipped:
        shown = "; ".join(skipped[:3]) + ("; ..." if len(skipped) > 3 else "")
        problems.append(
            f"the pack folder has {len(skipped)} files that are not valid packs: {shown}"
        )
    return found, problems


def schema_named(entries: object, packs: Sequence[dict[str, Any]]) -> set[tuple[str, str]]:
    """The id and version of each pack that the schema member ``packs`` names, and of each pack
    in the ``needs`` of a named kind pack in ``packs`` or built in. ``verify`` gives ``admit`` a
    pack from the folder only when this set holds it, so that a pack that the receipt names and
    the schema does not name is a difference, not an invalid packet."""
    if not isinstance(entries, list):
        return set()
    out = {
        (e["id"], e["version"])
        for e in entries
        if isinstance(e, Mapping)
        and isinstance(e.get("id"), str)
        and isinstance(e.get("version"), str)
    }
    kinds = [p for p in packs if p["type"] == "kind" and (p["id"], p["version"]) in out]
    for key in out & set(BUILT_IN_SHA256):
        p = built_in_pack(*key)
        if p is not None and p["type"] == "kind":
            kinds.append(p)
    for k in kinds:
        out |= {(e["id"], e["version"]) for e in k.get("needs", [])}
    return out
