"""The store contract vectors (conformance/store/): the JSON file, the runner and two stores."""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

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
    assert got["vectors_sha256"] == __import__("hashlib").sha256(FILE.read_bytes()).hexdigest()
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
    assert set(failed) == {"chain/two-reviewers"}
    assert failed["chain/two-reviewers"]["step"] == 2
    assert got["failed"] == 1


def test_a_check_finds_a_store_that_breaks_it() -> None:
    with pytest.raises(contract.VectorFailed, match="put-refuses/schema-members-not-in-order"):
        contract.check_put_refuses(_Lax)


def test_the_python_only_cases_stay() -> None:
    class ListLog(MemoryStore):
        def read(self, log: Any) -> list[dict[str, Any]]:
            return super().read(tuple(log))

    with pytest.raises(AssertionError, match="read"):
        contract.check_bad_logs(ListLog)
