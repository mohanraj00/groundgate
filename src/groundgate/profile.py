"""Document-family profiles: the unit of calibration (SPEC §4.10, #639).

A profile holds the terms, the policy and the route status of one document family. It changes
no reading rule. The gate reads its schema, policy and packs as a packet gives them.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .canonical import digest, jcs
from .model import Policy, Schema
from .pack import (
    _ID,
    _VERSION,
    BUILT_IN_SHA256,
    MAX_WORD,
    RETIRED,
    PacketError,
    _no_twice,
    built_in_pack,
)

FORMAT = 1
PREFIX = "groundgate-profile/1:"  # names the profile format, not the spec version
MAX_FILE = 4 << 20  # bytes of a profile file, before it is parsed (P8)
MAX_CANONICAL = 4 << 20  # bytes of a profile as canonical JSON (P8)
MAX_ROUTES = 2000  # the rows of one route table (P8)
MAX_DEPTH = 32  # the JSON nesting depth: the profile object is depth 1 (P8)
ROUTES = ("checked", "cleared")
STATUSES = ("draft", "measured")
MEMBERS = frozenset(
    {
        "groundgate_profile",
        "id",
        "version",
        "description",
        "kind",
        "packs",
        "schema",
        "policy",
        "routes",
        "gold_sha256",
    }
)
_ROW = frozenset({"field", "route", "status", "date", "documents", "bound"})
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_BOUND = re.compile(r"(?:0(?:\.[0-9]+)?|1(?:\.0+)?)\Z")


@dataclass(frozen=True)
class Profile:
    """A checked profile. ``body`` is the object that the digest reads (SPEC §4.10)."""

    id: str
    version: str
    sha256: str
    schema: Schema
    policy: Policy
    body: dict[str, Any] = field(compare=False, repr=False)

    def entry(self) -> dict[str, str]:
        """The ``profile`` member of the receipt (SPEC §5)."""
        return {"id": self.id, "version": self.version, "sha256": self.sha256}


def _fail(msg: str) -> PacketError:
    return PacketError(f"profile: {msg}")


def _check_routes(rows: object, fields: Mapping[str, object]) -> list[dict[str, Any]]:
    """P6: the route table."""
    if not isinstance(rows, list):
        raise _fail("routes must be a list of rows (P6)")
    if len(rows) > MAX_ROUTES:
        raise _fail(f"routes has more than {MAX_ROUTES} rows (P8)")
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - _ROW:
            raise _fail("a route row is malformed (P6)")
        name, route, status = row.get("field"), row.get("route"), row.get("status")
        if not isinstance(name, str) or name not in fields:
            raise _fail(f"a route row names the field {name!r}, which the schema has not (P6)")
        if route not in ROUTES:
            raise _fail(f"a route row has the route {route!r} (P6)")
        if status not in STATUSES:
            raise _fail(f"a route row has the status {status!r} (P6)")
        if (name, route) in seen:
            raise _fail(f"two route rows for {name!r} {route!r} (P6)")
        seen.add((name, route))
        if "date" in row:
            date = row["date"]
            try:
                ok = isinstance(date, str) and bool(_DATE.match(date))
                ok = ok and datetime.date.fromisoformat(date).isoformat() == date
            except ValueError:
                ok = False
            if not ok:
                raise _fail("the date of a route row must be YYYY-MM-DD (P6)")
        if "documents" in row:
            n = row["documents"]
            if type(n) is not int or not 1 <= n <= 2**53:
                raise _fail("the documents of a route row must be a positive count (P6)")
        if "bound" in row and not (isinstance(row["bound"], str) and _BOUND.match(row["bound"])):
            raise _fail("the bound of a route row must be a decimal string in [0, 1] (P6)")
        if status == "measured" and not {"date", "documents", "bound"} <= set(row):
            raise _fail("a measured route row needs a date, documents and a bound (P6)")
    return sorted(rows, key=lambda r: (r["field"], r["route"]))


def _depth_ok(obj: object) -> bool:
    """True when no list or object is deeper than MAX_DEPTH. A loop, not recursion, so that a
    deep profile cannot exhaust the stack."""
    todo: list[tuple[object, int]] = [(obj, 1)]
    while todo:
        node, depth = todo.pop()
        if isinstance(node, (dict, list)):
            if depth > MAX_DEPTH:
                return False
            items = node.values() if isinstance(node, dict) else node
            todo.extend((v, depth + 1) for v in items)
    return True


def check_profile(profile: object) -> Profile:
    """Run the checks P1 to P8 on one profile (SPEC §4.10), and return the checked profile.
    Raises ``PacketError``. The digest is computed, never read from the profile."""
    if not isinstance(profile, dict):
        raise _fail("a profile must be a JSON object (P1)")
    if not _depth_ok(profile):
        raise _fail(f"the profile is nested deeper than {MAX_DEPTH} (P8)")
    try:
        size = len(jcs(profile).encode("utf-8", "surrogatepass"))
    except (TypeError, ValueError) as e:
        raise _fail(f"the profile is not JSON data: {e} (P1)") from None
    if size > MAX_CANONICAL:
        raise _fail(f"the profile is more than {MAX_CANONICAL} bytes as canonical JSON (P8)")
    fmt = profile.get("groundgate_profile")
    if isinstance(fmt, bool) or fmt != FORMAT:
        raise _fail(f"groundgate_profile must be {FORMAT} (P1)")
    unknown = set(profile) - MEMBERS
    if unknown:
        raise _fail(f"members that the format does not list: {sorted(unknown)} (P1)")
    if "schema" not in profile:
        raise _fail("a profile must give a schema (P1)")
    pid, version = profile.get("id"), profile.get("version")
    if not isinstance(pid, str) or len(pid) > MAX_WORD or not _ID.match(pid):
        raise _fail("the id must be lowercase letters and digits with single '-' (P2)")
    if not isinstance(version, str) or not _VERSION.match(version):
        raise _fail("the version must be MAJOR.MINOR.PATCH (P2)")
    description = profile.get("description", "")
    if not isinstance(description, str):
        raise _fail("description must be a text (P3)")
    packs = profile.get("packs", [])
    if not isinstance(packs, list):
        raise _fail("packs must be a list of pack objects (P4)")
    policy_raw = profile.get("policy", {})
    if not isinstance(policy_raw, dict):
        raise _fail("policy must be an object (P4)")
    try:  # P4: the checks of SPEC §2.3, §2.4, §4.8 and §4.9
        schema = Schema.from_dict(copy.deepcopy(profile["schema"]), copy.deepcopy(packs))
        policy = Policy.from_dict(copy.deepcopy(policy_raw))
    except PacketError as e:
        raise _fail(f"{e} (P4)") from None
    kind = profile.get("kind")
    if kind is not None:
        if not isinstance(kind, dict) or set(kind) != {"id", "version"}:
            raise _fail("kind must be null or an object with only id and version (P5)")
        if not any(
            p["type"] == "kind" and p["id"] == kind["id"] and p["version"] == kind["version"]
            for p in schema.packs
        ):
            raise _fail("kind must name a kind pack that the schema names (P5)")
    routes = _check_routes(profile.get("routes", []), schema.fields)
    gold = profile.get("gold_sha256")
    if gold is not None and not (isinstance(gold, str) and _SHA.match(gold)):
        raise _fail("gold_sha256 must be null or a sha256 digest (P7)")
    if gold is None and any(r["status"] == "measured" for r in routes):
        raise _fail("a measured route row needs the gold_sha256 of the profile (P7)")
    body = {
        "groundgate_profile": FORMAT,
        "id": pid,
        "version": version,
        "description": description,
        "kind": None if kind is None else {"id": kind["id"], "version": kind["version"]},
        "routes": [dict(r) for r in routes],
        "gold_sha256": gold,
        "schema_sha256": digest("schema", schema.to_dict()),
        "policy_sha256": digest("policy", policy.to_dict()),
    }
    sha = "sha256:" + hashlib.sha256((PREFIX + jcs(body)).encode("utf-8")).hexdigest()
    return Profile(pid, version, sha, schema, policy, body)


def profile_digest(profile: object) -> str:
    """The digest of a profile (SPEC §4.10). Raises ``PacketError`` for an invalid profile."""
    return check_profile(profile).sha256


def load_profile(path: str | Path) -> dict[str, Any]:
    """Read a profile file and run the checks of SPEC §4.10 on it. A file of more than 4 MiB is
    refused before it is parsed. Raises ``PacketError``."""
    if not Path(path).is_file():
        raise PacketError(f"profile file {str(path)!r} is not a file")
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FILE + 1)
    except OSError as e:
        raise PacketError(f"profile file {str(path)!r} cannot be read: {e}") from None
    if len(data) > MAX_FILE:
        raise PacketError(f"profile file {str(path)!r} is more than {MAX_FILE} bytes (P8)")
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_no_twice)
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        if isinstance(e, PacketError):
            raise PacketError(f"profile file {str(path)!r}: {e}") from None
        raise PacketError(f"profile file {str(path)!r} is not JSON: {e}") from None
    check_profile(obj)
    return obj  # type: ignore[no-any-return]


# ------------------------------------------------- the built-in kind packs as profiles (#648)


def built_in_kinds() -> list[tuple[str, str]]:
    """The id and version of each built-in kind pack that ``admit`` reads, sorted."""
    out = []
    for pid, version in sorted(BUILT_IN_SHA256):
        if (pid, version) in RETIRED:
            continue
        pack = built_in_pack(pid, version)
        if pack is not None and pack["type"] == "kind":
            out.append((pid, version))
    return out


def built_in_profile(pid: str, version: str | None = None) -> dict[str, Any]:
    """A built-in kind pack as an example profile: one field for each template, no route row,
    so each route is ``draft``. Raises ``KeyError`` when no such kind pack is built in."""
    kinds = dict(built_in_kinds())
    if pid not in kinds or (version is not None and version != kinds[pid]):
        raise KeyError(f"{pid!r} {version or ''} is not a built-in kind pack")
    v = kinds[pid]
    pack = built_in_pack(pid, v)
    assert pack is not None
    return {
        "groundgate_profile": FORMAT,
        "id": pid,
        "version": v,
        "description": (
            f"Example: the built-in kind pack {pid} {v} as a profile. No route is measured."
        ),
        "kind": {"id": pid, "version": v},
        "schema": {
            "packs": [{"id": pid, "version": v}],
            "fields": {name: {"template": f"{pid}/{name}"} for name in sorted(pack["fields"])},
        },
        "routes": [],
        "gold_sha256": None,
    }
