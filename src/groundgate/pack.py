"""Vocabulary packs (SPEC §4.7, §4.8): the base pack ``en``, the loader checks and the union."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Iterator, Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from .canonical import jcs


class PacketError(ValueError):
    """The inputs themselves are invalid (SPEC §2): no receipt can be produced."""


BASE_ID = "en"
BASE_VERSION = "1.0.0"
# the digest of the base pack that SPEC §4.7 gives for this spec version
BASE_SHA256 = "sha256:8ee2f5c367baa29969759e3ed3ec5acf39f412a8b4b6afbda6477c1cde7fdeae"
BUILT_IN = frozenset({BASE_ID})  # the ids of the built-in packs (SPEC §4.8, L7)

FORMAT = 1
MAX_FILE = 1 << 20  # bytes of a pack file, before the loader parses it (L4)
MAX_CANONICAL = 256 << 10  # bytes of a pack as canonical JSON (L4)
MAX_DEPTH = 8  # the JSON nesting depth: the pack object is depth 1 (L4)
MAX_ENTRIES = 2000  # the entries of one list or object (L4)
MAX_WORD = 64  # the code points of one word (L3)
MAX_INT = 2**53  # an integer of a pack is at most this, as in JSON (L2)
POWERS = frozenset({3, 5, 6, 7, 9, 12})  # the powers of ten of a scale (L6)
COMPARATORS = ("approx", "gt", "lt", "ge", "le", "range")
# the loss words that stay in the code until the `finance` pack takes them (#336)
CODE_LOSS = ("loss", "losses", "deficit", "deficits")

_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_HEADING_CODE = re.compile(r"[A-Z]{3}\Z")

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
    from .model import Field  # the rules of a field (SPEC §2.3); model imports this module

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
        if e["id"] in BUILT_IN:
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
        if type(t) is not dict or set(t) - set(TEMPLATE_MEMBERS):
            raise _fail(pack, f"template {name!r} holds another member than the five (L9)")
        try:
            Field.from_dict(name, t)
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
    if len(data) > MAX_FILE:
        raise PacketError(f"pack file {str(path)!r} is more than {MAX_FILE} bytes (L4)")
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_twice)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        if isinstance(e, PacketError):
            raise
        raise PacketError(f"pack file {str(path)!r} is not JSON: {e}") from None
    return check_pack(obj)


# -------------------------------------------------------------------- the union


def _key(w: str) -> str:
    """A word as the conflict checks compare it: casefolded, each whitespace run one space."""
    return " ".join(w.casefold().split())


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
    """A qualifier phrase as SPEC §4.2 matches it."""
    body = r"\s+".join(re.escape(w) for w in p.split())
    return re.compile(body if not p[0].isalnum() else rf"\b{body}\b", re.I)


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
    loss = {_key(w) for w in (*CODE_LOSS, *m["sign"]["loss"])}
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
    """The words that a pack adds to the base, casefolded with each whitespace run as one
    space. A word that the base gives in the same list is not added (SPEC §5, decision packs)."""
    have = set(_entries(with_defaults(base)))
    return frozenset(_key(w) for path, w in _entries(with_defaults(pack)) if (path, w) not in have)


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
