"""The store contract vectors (conformance/store/): the JSON file, the runner and two stores."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from groundgate.canonical import jcs
from groundgate.store import (
    FolderStore,
    NotFound,
    StoreError,
    _check_key,
    _check_log,
    _check_record,
    _entry_key,
    check_bytes,
    contract,
    key,
)

HERE = Path(__file__).parent.parent / "conformance" / "store"
FILE = HERE / "vectors.json"


class MemoryStore:
    """A store in memory with the five operations, for the contract only."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.logs: dict[tuple[str, ...], list[dict[str, Any]]] = {}

    def put(self, kind: str, data: bytes) -> str:
        check_bytes(kind, data)
        k = key(kind, data)
        self.objects.setdefault(k, data)
        return k

    def get(self, kind: str, k: str) -> bytes:
        _check_key(k)
        if k not in self.objects:
            raise NotFound(f"object {k} is not in the store")
        if key(kind, self.objects[k]) != k:
            raise StoreError(f"object {k} is not a {kind} object")
        return self.objects[k]

    def append(self, log: Any, record: Any) -> str:
        word, _ = _check_log(log)
        if word == "deleted":
            raise ValueError("the store writes the deleted log")
        return self._append(log, _check_record(record))

    def _append(self, log: Any, record: dict[str, Any]) -> str:
        records = self.logs.setdefault(tuple(log), [])
        body = {
            **record,
            "sequence": len(records) + 1,
            "previous": records[-1]["entry_sha256"] if records else None,
        }
        head = _entry_key(log[0], body)
        records.append({**body, "entry_sha256": head})
        return head

    def read(self, log: Any) -> list[dict[str, Any]]:
        _check_log(log)
        return [dict(r) for r in self.logs.get(tuple(log), [])]

    def forget(self, k: str, reason: str) -> None:
        _check_key(k)
        if not reason:
            raise ValueError("forget needs a reason")
        if k not in self.objects:
            raise NotFound(f"object {k} is not in the store")
        self._append(("deleted",), {"key": k, "reason": reason, "time": "2026-11-12T00:00:00Z"})
        del self.objects[k]


def _folder(tmp_path: Path) -> Callable[[], FolderStore]:
    stores = iter(range(1000))
    return lambda: FolderStore(tmp_path / str(next(stores)))


def _build() -> Any:
    spec = importlib.util.spec_from_file_location("store_build", HERE / "build.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_file_is_the_build() -> None:
    build = _build()
    assert FILE.read_text("ascii") == contract.dump(contract.vectors(build.key_of, build.jcs_of))


def test_the_file_has_the_keys_of_the_store() -> None:
    """The build keys come from hashlib alone. They are equal to the keys of groundgate."""
    assert contract.load(FILE.read_text("ascii")) == contract.load(contract.dump())


def test_each_check_runs_a_vector_and_each_vector_names_a_check() -> None:
    names = {c.__name__ for c in contract.CHECKS}
    vecs = contract.load(FILE.read_text("ascii"))
    assert {v["check"] for v in vecs} == names
    assert len({v["id"] for v in vecs}) == len(vecs)
    for v in vecs:
        for step in v["steps"]:
            assert ("result" in step) != ("error" in step), v["id"]
            assert step.get("error", "invalid") in contract.ERRORS, v["id"]


@pytest.mark.parametrize("check", contract.CHECKS, ids=lambda c: c.__name__)
def test_the_file_on_the_folder_store(check: Callable[..., None], tmp_path: Path) -> None:
    check(_folder(tmp_path), contract.load(FILE.read_text("ascii")))


@pytest.mark.parametrize("check", contract.CHECKS, ids=lambda c: c.__name__)
def test_the_file_on_the_memory_store(check: Callable[..., None]) -> None:
    check(MemoryStore, contract.load(FILE.read_text("ascii")))


def test_run_on_the_memory_store() -> None:
    contract.run(MemoryStore)


def test_the_report_of_the_folder_store(tmp_path: Path) -> None:
    got = contract.report(_folder(tmp_path), "folder")
    assert got["format"] == "store-report@1"
    assert got["failed"] == 0
    assert got["passed"] == len(contract.vectors()) == len(got["results"])
    assert got["vectors_sha256"] == hashlib.sha256(FILE.read_bytes()).hexdigest()
    json.dumps(got)


class _NoChain(MemoryStore):
    """A store that does not link its records."""

    def _append(self, log: Any, record: dict[str, Any]) -> str:
        records = self.logs.setdefault(tuple(log), [])
        records.append({**record, "sequence": 1, "previous": None, "entry_sha256": "x"})
        return "x"


class _Lax(MemoryStore):
    """A store that does not check the bytes of an object."""

    def put(self, kind: str, data: bytes) -> str:
        k = key(kind, data)
        self.objects[k] = data
        return k


def test_the_report_names_the_failed_vectors() -> None:
    got = contract.report(_NoChain, "no chain")
    failed = {r["id"]: r for r in got["results"] if not r["passed"]}
    assert set(failed) == {"chain/two-reviewers", "chain/events", "forget/put-again"}
    assert failed["chain/two-reviewers"]["step"] == 2
    assert failed["forget/put-again"]["step"] == 8  # the sequence of the second record
    assert failed["chain/events"]["step"] == 2
    assert got["failed"] == 3


class _Changes(MemoryStore):
    """A store that adds members to the record that it gets."""

    def append(self, log: Any, record: Any) -> str:
        head = super().append(log, record)
        record["sequence"] = 99
        return head


def test_the_report_digest_is_of_the_vectors_before_the_run() -> None:
    got = contract.report(_Changes, "changes the input")
    assert got["failed"] == 0
    assert got["vectors_sha256"] == hashlib.sha256(FILE.read_bytes()).hexdigest()


class _LocalTime(MemoryStore):
    """A store that writes the time with an offset, not in UTC with Z."""

    def _append(self, log: Any, record: dict[str, Any]) -> str:
        if "time" in record:
            record = {**record, "time": "2026-11-12T01:00:00+01:00"}
        return super()._append(log, record)


def test_the_time_of_a_deletion_record_has_one_form() -> None:
    got = contract.report(_LocalTime, "local time")
    assert {r["id"] for r in got["results"] if not r["passed"]} == {
        "forget/one-object",
        "forget/twice",
        "forget/put-again",
    }


def test_the_module_writes_the_file() -> None:
    out = subprocess.run(
        [sys.executable, "-m", "groundgate.store.contract"], capture_output=True, check=True
    ).stdout
    assert out == FILE.read_bytes()


def test_a_check_finds_a_store_that_breaks_it() -> None:
    with pytest.raises(contract.VectorFailed, match="put-refuses/schema-members-not-in-order"):
        contract.check_put_refuses(_Lax)


def test_the_python_only_cases_stay() -> None:
    class ListLog(MemoryStore):
        def read(self, log: Any) -> list[dict[str, Any]]:
            return super().read(tuple(log))

    with pytest.raises(AssertionError, match="read"):
        contract.check_bad_logs(ListLog)


# ------------------------------------------------- the lock of the vectors (SPEC §9.7, #719)
LOCK = HERE / "vectors.lock"


def _steps_digest(steps: object) -> str:
    """The SHA-256 of the UTF-8 of the canonical JSON of the steps of one vector."""
    return hashlib.sha256(jcs(steps).encode("utf-8")).hexdigest()


def _lock_problems(lock: str, vectors: list[dict[str, Any]]) -> list[str]:
    """Compare the vectors with ``vectors.lock``: a vector whose steps changed, a vector that
    is removed, a vector that the list does not name, with the line to add for it, and an
    ``id`` that two vectors or two lines have."""
    problems = []
    locked: dict[str, str] = {}
    for line in lock.splitlines():
        digest, name = line.split("  ", 1)
        if name in locked:
            problems.append(f"{name} has two lines in vectors.lock")
        locked[name] = digest
    current: dict[str, str] = {}
    for v in vectors:
        if v["id"] in current:
            problems.append(f"two vectors have the id {v['id']}")
        current[v["id"]] = _steps_digest(v["steps"])
    for name, digest in locked.items():
        if name not in current:
            problems.append(f"{name} is removed")
        elif current[name] != digest:
            problems.append(f"the steps of {name} changed")
    for name, digest in current.items():
        if name not in locked:
            problems.append(f"{name} is not in vectors.lock: add the line '{digest}  {name}'")
    return problems


def _file_vectors() -> list[dict[str, Any]]:
    vectors: list[dict[str, Any]] = json.loads(FILE.read_text("ascii"))["vectors"]
    return vectors


def test_the_steps_of_a_vector_do_not_change() -> None:
    """A release only adds store vectors (SPEC §9.7). A new vector gets a line in
    ``conformance/store/vectors.lock``, and a line never changes."""
    lock = LOCK.read_text("ascii")
    assert len(lock.splitlines()) >= 49
    assert _lock_problems(lock, _file_vectors()) == []


def test_the_lock_finds_a_changed_a_removed_and_a_new_vector() -> None:
    lock, vectors = LOCK.read_text("ascii"), _file_vectors()
    first, second = vectors[0], vectors[1]
    step = {**first["steps"][0], "kind": "prompt@1"}
    changed = [{**first, "steps": [step, *first["steps"][1:]]}, *vectors[1:]]
    assert _lock_problems(lock, changed) == [f"the steps of {first['id']} changed"]
    result = {**first, "steps": [*first["steps"][:-1], {**first["steps"][-1], "result": None}]}
    assert _lock_problems(lock, [result, *vectors[1:]]) == [f"the steps of {first['id']} changed"]
    removed = [v for v in vectors if v is not second]
    assert _lock_problems(lock, removed) == [f"{second['id']} is removed"]
    new = {"id": "put-get/new", "check": "check_put_get", "about": "new", "steps": []}
    digest = _steps_digest([])
    assert _lock_problems(lock, [*vectors, new]) == [
        f"put-get/new is not in vectors.lock: add the line '{digest}  put-get/new'"
    ]
    twice = [*vectors, {**first, "steps": []}]
    assert _lock_problems(lock, twice) == [
        f"two vectors have the id {first['id']}",
        f"the steps of {first['id']} changed",
    ]
    line = lock.splitlines()[0]
    assert _lock_problems(lock + line + "\n", vectors) == [
        f"{line.split('  ', 1)[1]} has two lines in vectors.lock"
    ]


def test_the_lock_ignores_the_text_of_a_vector() -> None:
    """``about`` and ``check`` are not steps: a clearer sentence changes no line."""
    lock, vectors = LOCK.read_text("ascii"), _file_vectors()
    reworded = [{**v, "about": v["about"] + " More words.", "check": "other"} for v in vectors]
    assert _lock_problems(lock, reworded) == []
