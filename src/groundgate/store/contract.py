"""The contract tests of a store (docs/design/store.md §6).

The contract is a list of language-agnostic vectors. ``conformance/store/vectors.json`` holds
them as JSON, and ``conformance/store/README.md`` tells a backend in another language how to run
them. This module is the Python runner. The vectors are written by hand in ``vectors`` below, so
an installed package has them too.

An app with its own storage runs these checks against it. Each check takes a function that
returns a new, empty store, runs its vectors, and raises ``AssertionError`` on a failure. With
pytest::

    import pytest
    from groundgate.store import contract

    @pytest.mark.parametrize("check", contract.CHECKS, ids=lambda c: c.__name__)
    def test_my_store(check, tmp_path):
        check(lambda: MyStore(...))

``run(make)`` runs all the checks in order. ``report(make, backend)`` runs each vector and gives
the report object of the runner contract. The checks need only the standard library.

``python -m groundgate.store.contract`` writes the vectors of the installed version to stdout.
The bytes are equal to ``conformance/store/vectors.json`` of the same version.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from collections.abc import Callable, Iterable
from typing import Any

from ..canonical import jcs
from . import NotFound, Store, StoreError, key

__all__ = [
    "ANY_STRING",
    "ANY_TIME",
    "CHECKS",
    "FORMAT",
    "VectorFailed",
    "dump",
    "load",
    "report",
    "run",
    "run_vector",
    "vectors",
]

Make = Callable[[], Store]
Vector = dict[str, Any]
KeyOf = Callable[[str, bytes], str]
JcsOf = Callable[[Any], str]

FORMAT = "groundgate-store-vectors@1"
REPORT = "store-report@1"
ANY_STRING: dict[str, str] = {"$": "string"}  # in a read result, it matches any string
ANY_TIME: dict[str, str] = {"$": "time"}  # it matches a UTC time such as 2026-10-20T09:30:00Z
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
ERRORS: dict[str, type[Exception]] = {
    "invalid": ValueError,
    "not-found": NotFound,
    "store-error": StoreError,
}

_TEXT = b"The rent is 1,200 dollars."
_SCHEMA = b'{"fields":[{"name":"rent","type":"money"}]}'
_PACKET_JSON = b'{"format":"packet@1"}'


def vectors(key_of: KeyOf = key, jcs_of: JcsOf = jcs) -> list[Vector]:
    """The store contract as vectors. ``key_of`` gives the store key of bytes as a kind, and
    ``jcs_of`` gives the canonical JSON of a value. ``conformance/store/build.py`` gives its own
    standard-library forms of both, so the keys in the JSON file do not come from the store."""
    packet = key_of("packet@1", _PACKET_JSON)
    ana = key_of("reviewer@1", b"ana")
    ben = key_of("reviewer@1", b"ben")
    out: list[Vector] = []

    def add(check: str, name: str, about: str, *steps: dict[str, Any]) -> None:
        out.append(
            {
                "id": f"{check[6:].replace('_', '-')}/{name}",
                "check": check,
                "about": about,
                "steps": list(steps),
            }
        )

    def put(kind: str, data: bytes, **want: Any) -> dict[str, Any]:
        return {"op": "put", "kind": kind, "data": data, **want}

    def get(kind: str, k: str, **want: Any) -> dict[str, Any]:
        return {"op": "get", "kind": kind, "key": k, **want}

    def append(log: Any, record: Any, **want: Any) -> dict[str, Any]:
        return {"op": "append", "log": log, "record": record, **want}

    def read(log: Any, **want: Any) -> dict[str, Any]:
        return {"op": "read", "log": log, **want}

    def forget(k: Any, reason: str, **want: Any) -> dict[str, Any]:
        return {"op": "forget", "key": k, "reason": reason, **want}

    def chain(word: str, bodies: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        previous: str | None = None
        for n, body in enumerate(bodies, 1):
            entry = {**body, "sequence": n, "previous": previous}
            previous = key_of(f"{word}-entry@1", jcs_of(entry).encode("utf-8"))
            records.append({**entry, "entry_sha256": previous})
        return records

    # check_put_get
    steps = []
    for kind, data in (("text@1", _TEXT), ("schema@1", _SCHEMA), ("source@1", b"\xff\x00")):
        k = key_of(kind, data)
        steps += [put(kind, data, result=k), put(kind, data, result=k), get(kind, k, result=data)]
    add(
        "check_put_get",
        "three-kinds",
        "put returns the store key, equal bytes give the same key, and get gives the bytes back",
        *steps,
    )

    # check_put_refuses
    for name, data in (
        ("members-not-in-order", b'{"b":1,"a":2}'),
        ("a-space", b'{"a": 1}'),
        ("a-duplicate-member", b'{"a":1,"a":1}'),
        ("not-the-shortest-number", b'{"a":1.0}'),
        ("nan", b'{"a":NaN}'),
        ("a-line-break-at-the-end", b'{"a":1}\n'),
        ("not-utf-8", b"\xff"),
    ):
        add(
            "check_put_refuses",
            f"schema-{name}",
            "put refuses JSON that is not canonical",
            put("schema@1", data, error="invalid"),
        )
    add(
        "check_put_refuses",
        "text-not-nfc",
        "put refuses text that is not NFC",
        put("text@1", "é".encode(), error="invalid"),
    )
    add(
        "check_put_refuses",
        "text-not-utf-8",
        "put refuses text that is not UTF-8",
        put("text@1", b"\xff", error="invalid"),
    )
    add(
        "check_put_refuses",
        "run-torn-line",
        "put refuses a run with no line break at the end",
        put("run@3", b'{"a":1}', error="invalid"),
    )
    for name, kind in (
        ("upper-case", "Text@1"),
        ("no-version", "text"),
        ("a-parent-path", "../text@1"),
        ("a-slash", "text@1/x"),
        ("version-0", "text@0"),
        ("empty", ""),
    ):
        add(
            "check_put_refuses",
            f"kind-{name}",
            "put refuses a kind that is not such as text@1",
            put(kind, b"x", error="invalid"),
        )

    # check_get_missing
    add(
        "check_get_missing",
        "absent",
        "get of an absent key raises not-found",
        get("text@1", key_of("text@1", _TEXT), error="not-found"),
    )
    k = key_of("text@1", _TEXT)
    add(
        "check_get_missing",
        "another-kind",
        "get with another kind fails",
        put("text@1", _TEXT, result=k),
        get("prompt@1", k, error="store-error"),
    )

    # check_bad_keys
    for name, bad in (
        ("a-path", "sha256:../../etc/passwd"),
        ("upper-case", "sha256:" + "A" * 64),
        ("63-digits", "sha256:" + "a" * 63),
        ("a-line-break", "sha256:" + "a" * 64 + "\n"),
        ("a-parent-path", "../" + "a" * 64),
        ("no-prefix", "a" * 64),
        ("empty", ""),
    ):
        add(
            "check_bad_keys",
            name,
            "a key that does not match sha256:[0-9a-f]{64} is invalid",
            get("text@1", bad, error="invalid"),
            forget(bad, "test", error="invalid"),
        )

    # check_bad_logs
    bad_logs: tuple[tuple[str, Any], ...] = (
        ("empty", []),
        ("answers-no-keys", ["answers"]),
        ("answers-one-key", ["answers", packet]),
        ("answers-a-name", ["answers", packet, "ana"]),
        ("answers-a-path", ["answers", "../x", ana]),
        ("splits-a-name", ["splits", "requested4"]),
        ("a-parent-path", ["../answers", packet, ana]),
        ("deleted-a-key", ["deleted", ana]),
        ("a-nested-word", [["answers"], packet, ana]),
        ("a-string", "answers"),
    )
    for name, bad in bad_logs:
        add(
            "check_bad_logs",
            name,
            "a log name that is not a fixed word and its keys is invalid",
            read(bad, error="invalid"),
            append(bad, {"a": 1}, error="invalid"),
        )

    # check_chain
    log_a = ["answers", packet, ana]
    log_b = ["answers", packet, ben]
    a = chain("answers", [{"answer": "yes"}, {"answer": "no"}])
    b = chain("answers", [{"answer": "yes"}])
    add(
        "check_chain",
        "two-reviewers",
        "append sets sequence, previous and entry_sha256, read gives the records in order, the "
        "log only grows, and two reviewers write two logs",
        read(log_a, result=[]),
        append(log_a, {"answer": "yes"}, result=a[0]["entry_sha256"]),
        read(log_a, result=a[:1]),
        append(log_a, {"answer": "no"}, result=a[1]["entry_sha256"]),
        append(log_b, {"answer": "yes"}, result=b[0]["entry_sha256"]),
        read(log_a, result=a),
        read(log_b, result=b),
    )

    # check_append_refuses
    splits = ["splits", key_of("set@1", b"requested4")]
    for member in ("sequence", "previous", "entry_sha256"):
        add(
            "check_append_refuses",
            f"with-{member.replace('_', '-')}",
            "append refuses a record with a chain member",
            append(splits, {member: 1}, error="invalid"),
            read(splits, result=[]),
        )
    add(
        "check_append_refuses",
        "a-list",
        "append refuses a record that is not an object",
        append(splits, [1], error="invalid"),
        read(splits, result=[]),
    )
    add(
        "check_append_refuses",
        "deleted",
        "append refuses the deleted log",
        append(["deleted"], {"key": packet}, error="invalid"),
        read(["deleted"], result=[]),
    )

    # check_forget
    k = key_of("text@1", _TEXT)
    kept = key_of("schema@1", _SCHEMA)
    gone = {
        "key": k,
        "reason": "the tenant asked",
        "time": ANY_TIME,
        "sequence": 1,
        "previous": None,
        "entry_sha256": ANY_STRING,
    }
    add(
        "check_forget",
        "one-object",
        "forget removes an object and records the key, the time and the reason",
        put("text@1", _TEXT, result=k),
        put("schema@1", _SCHEMA, result=kept),
        forget(k, "the tenant asked", result=None),
        get("text@1", k, error="not-found"),
        get("schema@1", kept, result=_SCHEMA),
        read(["deleted"], result=[gone]),
        forget(k, "again", error="not-found"),
    )
    add(
        "check_forget",
        "empty-reason",
        "forget refuses an empty reason, and the object and the deleted log do not change",
        put("text@1", _TEXT, result=k),
        forget(k, "", error="invalid"),
        get("text@1", k, result=_TEXT),
        read(["deleted"], result=[]),
    )
    add(
        "check_forget",
        "twice",
        "a second forget of a key is not-found and adds no deletion record",
        put("text@1", _TEXT, result=k),
        forget(k, "the tenant asked", result=None),
        forget(k, "the tenant asked", error="not-found"),
        read(["deleted"], result=[gone]),
    )
    again = {**gone, "sequence": 2, "previous": ANY_STRING}
    add(
        "check_forget",
        "put-again",
        "put accepts an object after forget, get gives it, and the deletion record stays",
        put("text@1", _TEXT, result=k),
        forget(k, "the tenant asked", result=None),
        put("text@1", _TEXT, result=k),
        get("text@1", k, result=_TEXT),
        read(["deleted"], result=[gone]),
        forget(k, "the tenant asked", result=None),
        get("text@1", k, error="not-found"),
        read(["deleted"], result=[gone, again]),
    )
    return out


def _data(data: bytes) -> dict[str, str]:
    try:
        return {"utf8": data.decode("utf-8")}
    except UnicodeDecodeError:
        return {"hex": data.hex()}


def dump(vecs: list[Vector] | None = None) -> str:
    """The JSON text of ``conformance/store/vectors.json``."""

    def encode(value: Any) -> Any:
        if isinstance(value, bytes):
            return _data(value)
        if isinstance(value, dict):
            return {m: encode(v) for m, v in value.items()}
        if isinstance(value, list):
            return [encode(v) for v in value]
        return value

    body = {"format": FORMAT, "vectors": encode(vectors() if vecs is None else vecs)}
    return json.dumps(body, indent=1, ensure_ascii=True) + "\n"


def load(text: str) -> list[Vector]:
    """The vectors of a ``vectors.json`` text, with each data object as bytes."""
    body = json.loads(text)
    if not isinstance(body, dict) or body.get("format") != FORMAT:
        raise ValueError(f"the vectors are not {FORMAT}")
    out: list[Vector] = body["vectors"]
    for vector in out:
        for step in vector["steps"]:
            if "data" in step:
                step["data"] = _bytes(step["data"])
            if step["op"] == "get" and "result" in step:
                step["result"] = _bytes(step["result"])
    return out


def _bytes(data: dict[str, str]) -> bytes:
    if set(data) == {"utf8"}:
        return data["utf8"].encode("utf-8")
    if set(data) == {"hex"}:
        return bytes.fromhex(data["hex"])
    raise ValueError(f"{data!r} is not a data object")


def _match(got: Any, want: Any) -> bool:
    if want == ANY_STRING:
        return isinstance(got, str)
    if want == ANY_TIME:
        return isinstance(got, str) and _TIME.fullmatch(got) is not None
    if isinstance(want, dict):
        return (
            isinstance(got, dict)
            and set(got) == set(want)
            and all(_match(got[m], v) for m, v in want.items())
        )
    if isinstance(want, list):
        return (
            isinstance(got, list)
            and len(got) == len(want)
            and all(_match(g, w) for g, w in zip(got, want, strict=True))
        )
    return type(got) is type(want) and bool(got == want)


def _call(store: Store, step: dict[str, Any]) -> Any:
    op = step["op"]
    log: Any = tuple(step["log"]) if isinstance(step.get("log"), list) else step.get("log")
    if op == "put":
        return store.put(step["kind"], step["data"])
    if op == "get":
        return store.get(step["kind"], step["key"])
    if op == "append":
        return store.append(log, copy.deepcopy(step["record"]))  # the vector does not change
    if op == "read":
        return store.read(log)
    if op == "forget":
        return store.forget(step["key"], step["reason"])
    raise ValueError(f"{op!r} is not a store operation")


def _class(exc: BaseException) -> str:
    if isinstance(exc, NotFound):
        return "not-found"
    if isinstance(exc, StoreError):
        return "store-error"
    if isinstance(exc, ValueError):
        return "invalid"
    return type(exc).__name__


class VectorFailed(AssertionError):
    """A vector failed at ``step`` (1 is the first step, 0 is the new store)."""

    def __init__(self, text: str, step: int) -> None:
        super().__init__(text)
        self.step = step


def run_vector(make: Make, vector: Vector) -> None:
    """Run one vector on a new store from ``make``. A failure raises ``AssertionError`` with the
    vector id and the step number."""
    try:
        store = make()
    except Exception as exc:
        raise VectorFailed(f"{vector['id']}: no new store: {exc}", 0) from exc
    for n, step in enumerate(vector["steps"], 1):
        what = f"{vector['id']} step {n}: {step['op']} {step.get('kind', step.get('log', ''))}"
        want = step.get("error")
        try:
            got = _call(store, step)
        except Exception as exc:
            if want is None:
                raise VectorFailed(f"{what}: {_class(exc)} ({exc}), want a result", n) from exc
            if not isinstance(exc, ERRORS[want]):
                raise VectorFailed(f"{what}: {_class(exc)} instead of {want}", n) from exc
            continue
        if want is not None:
            raise VectorFailed(f"{what}: no {want}", n)
        if not _match(got, step["result"]):
            raise VectorFailed(f"{what}: got {got!r}, want {step['result']!r}", n)


def _vectors_of(check: str, vecs: list[Vector] | None) -> list[Vector]:
    return [v for v in (vectors() if vecs is None else vecs) if v["check"] == check]


def _run_check(check: str, make: Make, vecs: list[Vector] | None) -> None:
    for vector in _vectors_of(check, vecs):
        run_vector(make, vector)


def _fails(error: type[BaseException], what: str, call: Callable[..., object], *args: Any) -> None:
    try:
        call(*args)
    except error:
        return
    except Exception as exc:  # a different error
        raise AssertionError(f"{what}: {type(exc).__name__} instead of {error.__name__}") from exc
    raise AssertionError(f"{what}: no {error.__name__}")


def check_put_get(make: Make, vecs: list[Vector] | None = None) -> None:
    """``put`` returns the store key, equal bytes give the same key, and ``get`` gives the
    bytes back."""
    _run_check("check_put_get", make, vecs)


def check_put_refuses(make: Make, vecs: list[Vector] | None = None) -> None:
    """``put`` refuses JSON that is not canonical, text that is not NFC UTF-8, and bad
    kinds."""
    _run_check("check_put_refuses", make, vecs)


def check_get_missing(make: Make, vecs: list[Vector] | None = None) -> None:
    """``get`` of an absent key raises ``NotFound``, and ``get`` with another kind fails."""
    _run_check("check_get_missing", make, vecs)


def check_bad_keys(make: Make, vecs: list[Vector] | None = None) -> None:
    """A key that does not match ``sha256:[0-9a-f]{64}`` raises ``ValueError``."""
    _run_check("check_bad_keys", make, vecs)


def check_bad_logs(make: Make, vecs: list[Vector] | None = None) -> None:
    """A log name that is not a fixed word and its keys raises ``ValueError``. In Python, a log
    name is a tuple, so a list is invalid too. JSON has no tuple, so no vector has this case."""
    _run_check("check_bad_logs", make, vecs)
    store = make()
    bad = ["answers", key("packet@1", _PACKET_JSON), key("reviewer@1", b"ana")]
    _fails(ValueError, f"read {bad!r}", store.read, bad)
    _fails(ValueError, f"append {bad!r}", store.append, bad, {"a": 1})


def check_chain(make: Make, vecs: list[Vector] | None = None) -> None:
    """``append`` sets ``sequence``, ``previous`` and ``entry_sha256``, and ``read`` gives the
    records in order. Two reviewers write two logs."""
    _run_check("check_chain", make, vecs)


def check_append_refuses(make: Make, vecs: list[Vector] | None = None) -> None:
    """``append`` refuses a record with a chain member, a record that is not a dict, and the
    deleted log. In Python, a record member can be a value that is not a string. JSON has no
    such member, so no vector has this case."""
    _run_check("check_append_refuses", make, vecs)
    store = make()
    log = ("splits", key("set@1", b"requested4"))
    _fails(ValueError, "append a member that is not a string", store.append, log, {1: "x"})
    if store.read(log) != []:
        raise AssertionError("a log after a refused append is not empty")


def check_forget(make: Make, vecs: list[Vector] | None = None) -> None:
    """``forget`` removes an object and records the key, the time and the reason."""
    _run_check("check_forget", make, vecs)


CHECKS: tuple[Callable[..., None], ...] = (
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


def report(make: Make, backend: str, vecs: list[Vector] | None = None) -> dict[str, Any]:
    """Run each vector on a new store from ``make``, and give the report object of the runner
    contract (``conformance/store/README.md``). A failed vector does not stop the others."""
    vecs = vectors() if vecs is None else vecs
    digest = hashlib.sha256(dump(vecs).encode("ascii")).hexdigest()  # before the backend runs
    results: list[dict[str, Any]] = []
    for vector in vecs:
        try:
            run_vector(make, vector)
        except VectorFailed as exc:
            results.append(
                {"id": vector["id"], "passed": False, "step": exc.step, "detail": str(exc)}
            )
        else:
            results.append({"id": vector["id"], "passed": True})
    passed = sum(r["passed"] for r in results)
    return {
        "format": REPORT,
        "vectors_sha256": digest,
        "backend": backend,
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


if __name__ == "__main__":
    sys.stdout.buffer.write(dump().encode("ascii"))
