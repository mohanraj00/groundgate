"""The contract tests of a store (docs/design/store.md §6).

An app with its own storage runs these checks against it. Each check takes a function that
returns a new, empty store, and raises ``AssertionError`` on a failure. With pytest::

    import pytest
    from groundgate.store import contract

    @pytest.mark.parametrize("check", contract.CHECKS, ids=lambda c: c.__name__)
    def test_my_store(check, tmp_path):
        check(lambda: MyStore(...))

``run(make)`` runs all the checks in order. The checks need only the standard library.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..canonical import jcs
from . import NotFound, Store, StoreError, key, reviewer_key

__all__ = ["CHECKS", "run"]

Make = Callable[[], Store]

_TEXT = b"The rent is 1,200 dollars."
_SCHEMA = b'{"fields":[{"name":"rent","type":"money"}]}'
_PACKET = key("packet@1", b'{"format":"packet@1"}')


def _fails(error: type[BaseException], what: str, call: Callable[..., object], *args: Any) -> None:
    try:
        call(*args)
    except error:
        return
    except Exception as exc:  # a different error
        raise AssertionError(f"{what}: {type(exc).__name__} instead of {error.__name__}") from exc
    raise AssertionError(f"{what}: no {error.__name__}")


def _same(got: Any, want: Any, what: str) -> None:
    if got != want:
        raise AssertionError(f"{what}: got {got!r}, want {want!r}")


def check_put_get(make: Make) -> None:
    """``put`` returns the store key, equal bytes give the same key, and ``get`` gives the
    bytes back."""
    store = make()
    for kind, data in (("text@1", _TEXT), ("schema@1", _SCHEMA), ("source@1", b"\xff\x00")):
        k = store.put(kind, data)
        _same(k, key(kind, data), f"put {kind}")
        _same(store.put(kind, data), k, f"put {kind} again")
        _same(store.get(kind, k), data, f"get {kind}")


def check_put_refuses(make: Make) -> None:
    """``put`` refuses JSON that is not canonical, text that is not NFC UTF-8, and bad
    kinds."""
    store = make()
    for data in (
        b'{"b":1,"a":2}',  # members not in order
        b'{"a": 1}',  # a space
        b'{"a":1,"a":1}',  # a duplicate member
        b'{"a":1.0}',  # not the shortest number
        b'{"a":NaN}',
        b'{"a":1}\n',
        b"\xff",
    ):
        _fails(ValueError, f"put schema@1 {data!r}", store.put, "schema@1", data)
    _fails(ValueError, "put text that is not NFC", store.put, "text@1", "e\u0301".encode())
    _fails(ValueError, "put text that is not UTF-8", store.put, "text@1", b"\xff")
    _fails(ValueError, "put a run with a torn line", store.put, "run@3", b'{"a":1}')
    for kind in ("Text@1", "text", "../text@1", "text@1/x", "text@0", ""):
        _fails(ValueError, f"put kind {kind!r}", store.put, kind, b"x")


def check_get_missing(make: Make) -> None:
    """``get`` of an absent key raises ``NotFound``, and ``get`` with another kind fails."""
    store = make()
    _fails(NotFound, "get an absent key", store.get, "text@1", key("text@1", _TEXT))
    k = store.put("text@1", _TEXT)
    _fails(StoreError, "get with another kind", store.get, "prompt@1", k)


def check_bad_keys(make: Make) -> None:
    """A key that does not match ``sha256:[0-9a-f]{64}`` raises ``ValueError``."""
    store = make()
    for bad in (
        "sha256:../../etc/passwd",
        "sha256:" + "A" * 64,
        "sha256:" + "a" * 63,
        "sha256:" + "a" * 64 + "\n",
        "../" + "a" * 64,
        "a" * 64,
        "",
    ):
        _fails(ValueError, f"get {bad!r}", store.get, "text@1", bad)
        _fails(ValueError, f"forget {bad!r}", store.forget, bad, "test")


def check_bad_logs(make: Make) -> None:
    """A log name that is not a fixed word and its keys raises ``ValueError``."""
    store = make()
    good = reviewer_key("ana")
    for bad in (
        (),
        ("answers",),
        ("answers", _PACKET),
        ("answers", _PACKET, "ana"),
        ("answers", "../x", good),
        ("splits", "requested4"),
        ("../answers", _PACKET, good),
        ("deleted", good),
        ["answers", _PACKET, good],
        (["answers"], _PACKET, good),
        "answers",
    ):
        _fails(ValueError, f"read {bad!r}", store.read, bad)
        _fails(ValueError, f"append {bad!r}", store.append, bad, {"a": 1})


def check_chain(make: Make) -> None:
    """``append`` sets ``sequence``, ``previous`` and ``entry_sha256``, and ``read`` gives the
    records in order. Two reviewers write two logs."""
    store = make()
    ana = ("answers", _PACKET, reviewer_key("ana"))
    ben = ("answers", _PACKET, reviewer_key("ben"))
    _same(store.read(ana), [], "read an absent log")
    heads = [store.append(ana, {"answer": "yes"}), store.append(ana, {"answer": "no"})]
    store.append(ben, {"answer": "yes"})
    records = store.read(ana)
    _same(len(records), 2, "the records of a log")
    previous = None
    for n, (record, head) in enumerate(zip(records, heads, strict=True), 1):
        body = {m: v for m, v in record.items() if m != "entry_sha256"}
        _same(record["sequence"], n, "sequence")
        _same(record["previous"], previous, "previous")
        _same(record["entry_sha256"], head, "the head that append returned")
        _same(head, key("answers-entry@1", jcs(body).encode()), "entry_sha256")
        previous = head
    _same([r["answer"] for r in records], ["yes", "no"], "the records in order")
    _same([r["sequence"] for r in store.read(ben)], [1], "the log of a second reviewer")


def check_append_refuses(make: Make) -> None:
    """``append`` refuses a record with a chain member, a record that is not a dict, and the
    deleted log."""
    store = make()
    log = ("splits", key("set@1", b"requested4"))
    for member in ("sequence", "previous", "entry_sha256"):
        _fails(ValueError, f"append with {member}", store.append, log, {member: 1})
    _fails(ValueError, "append a list", store.append, log, [1])
    _fails(ValueError, "append a member that is not a string", store.append, log, {1: "x"})
    _fails(ValueError, "append deleted", store.append, ("deleted",), {"key": _PACKET})
    _same(store.read(log), [], "a log after refused appends")


def check_forget(make: Make) -> None:
    """``forget`` removes an object and records the key, the time and the reason."""
    store = make()
    k = store.put("text@1", _TEXT)
    kept = store.put("schema@1", _SCHEMA)
    store.forget(k, "the tenant asked")
    _fails(NotFound, "get after forget", store.get, "text@1", k)
    _same(store.get("schema@1", kept), _SCHEMA, "get of another object after forget")
    records = store.read(("deleted",))
    _same([(r["key"], r["reason"]) for r in records], [(k, "the tenant asked")], "deleted log")
    if not isinstance(records[0]["time"], str):
        raise AssertionError("the deleted log has no time")
    _fails(NotFound, "forget an absent object", store.forget, k, "again")


CHECKS: tuple[Callable[[Make], None], ...] = (
    check_put_get,
    check_put_refuses,
    check_get_missing,
    check_bad_keys,
    check_bad_logs,
    check_chain,
    check_append_refuses,
    check_forget,
)


def run(make: Make) -> None:
    """Run each check against new stores from ``make``."""
    for check in CHECKS:
        check(make)
