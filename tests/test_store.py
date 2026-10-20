"""The store of docs/design/store.md: the contract on the folder store, and the folder rules."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

import pytest

from groundgate.canonical import jcs
from groundgate.store import (
    FolderStore,
    Locked,
    StoreError,
    contract,
    key,
    reviewer_key,
    set_key,
)

PACKET = key("packet@1", b'{"format":"packet@1"}')
ANA = ("answers", PACKET, reviewer_key("ana"))
TEXT = b"The rent is 1,200 dollars."


@pytest.fixture
def root(tmp_path: Path) -> Iterator[Path]:
    old = os.umask(0o022)
    try:
        yield tmp_path / "store"
    finally:
        os.umask(old)


def _object(root: Path, k: str) -> Path:
    return root / "objects" / k[7:9] / k[9:]


@pytest.mark.parametrize("check", contract.CHECKS, ids=lambda c: c.__name__)
def test_contract_on_the_folder_store(check: Callable[..., None], tmp_path: Path) -> None:
    stores = iter(range(100))
    check(lambda: FolderStore(tmp_path / str(next(stores))))


def test_contract_run(tmp_path: Path) -> None:
    stores = iter(range(100))
    contract.run(lambda: FolderStore(tmp_path / str(next(stores))))


def test_the_key_formula() -> None:
    want = hashlib.sha256(b"groundgate-object/1:text@1\x00" + TEXT).hexdigest()
    assert key("text@1", TEXT) == "sha256:" + want
    assert reviewer_key("ana") == key("reviewer@1", b"ana")
    assert set_key("requested4") == key("set@1", b"requested4")


def test_the_layout_and_modes(root: Path) -> None:
    with FolderStore(root) as store:
        k = store.put("text@1", TEXT)
        store.append(ANA, {"answer": "yes"})
        store.append(("splits", set_key("requested4")), {"split": "development"})
        path = _object(root, k)
        log = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".jsonl")
        assert path.read_bytes() == TEXT
        assert log.is_file()
        assert (root / "logs" / "splits" / (set_key("requested4")[7:] + ".jsonl")).is_file()
        assert (log.parent / (ANA[2][7:] + ".lock")).is_file()
        for file in (path, log):
            assert stat.S_IMODE(file.stat().st_mode) == 0o600
        for folder in (root, path.parent, root / "objects", log.parent, root / "logs"):
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert not (log.parent / (ANA[2][7:] + ".lock")).exists()


def test_each_folder_that_the_store_makes_is_private(root: Path) -> None:
    deep = root / "a" / "b"
    FolderStore(deep).put("text@1", TEXT)
    for folder in (root, root / "a", deep):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_a_failed_append_removes_its_partial_line(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})

        def fail(fd: int) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "fsync", fail)
        with pytest.raises(OSError, match="No space"):
            store.append(ANA, {"answer": "no"})
        monkeypatch.undo()
        store.append(ANA, {"answer": "maybe"})
        assert [r["answer"] for r in store.read(ANA)] == ["yes", "maybe"]


def test_group_read(root: Path) -> None:
    os.umask(0o077)
    with FolderStore(root, group_read=True) as store:
        path = _object(root, store.put("text@1", TEXT))
        store.append(ANA, {"answer": "yes"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o750


def test_get_stops_on_changed_bytes_and_put_writes_again(root: Path) -> None:
    store = FolderStore(root)
    k = store.put("text@1", TEXT)
    _object(root, k).write_bytes(b"The rent is 9,999 dollars.")
    with pytest.raises(StoreError, match="does not match its key"):
        store.get("text@1", k)
    assert store.put("text@1", TEXT) == k
    assert store.get("text@1", k) == TEXT


def test_symlink_fifo_and_size_fail_before_a_read(root: Path, tmp_path: Path) -> None:
    store = FolderStore(root, max_bytes=64)
    k = store.put("text@1", TEXT)
    path = _object(root, k)
    secret = tmp_path / "secret"
    secret.write_bytes(TEXT)
    path.unlink()
    path.symlink_to(secret)
    with pytest.raises(StoreError, match="is a symlink"):
        store.get("text@1", k)
    path.unlink()
    os.mkfifo(path)  # a read of a FIFO with no writer blocks: the check must come first
    with pytest.raises(StoreError, match="not a regular file"):
        store.get("text@1", k)
    path.unlink()
    path.write_bytes(b"x" * 65)
    with pytest.raises(StoreError, match="larger than max_bytes"):
        store.get("text@1", k)
    with pytest.raises(ValueError, match="larger than max_bytes"):
        store.put("source@1", b"x" * 65)
    assert store.put("text@1", TEXT) == k  # put replaces the bad file


def test_a_log_that_is_a_symlink_or_a_fifo(root: Path, tmp_path: Path) -> None:
    store = FolderStore(root)
    store.append(ANA, {"answer": "yes"})
    store.close()
    log = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".jsonl")
    log.rename(tmp_path / "moved.jsonl")
    log.symlink_to(tmp_path / "moved.jsonl")
    with pytest.raises(StoreError, match="is a symlink"):
        store.read(ANA)
    with pytest.raises(StoreError, match="is a symlink"):
        store.append(ANA, {"answer": "no"})
    log.unlink()
    os.mkfifo(log)
    with pytest.raises(StoreError, match="not a regular file"):
        store.read(ANA)


def test_append_refuses_a_fifo_put_in_place_after_the_lock(root: Path) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
        log = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".jsonl")
        log.unlink()
        os.mkfifo(log)  # an open for write of a FIFO with no reader blocks without O_NONBLOCK
        with pytest.raises(StoreError, match="cannot be opened"):
            store.append(ANA, {"answer": "no"})


class _LaxStore(FolderStore):
    """A store that does not check the bytes of an object."""

    def put(self, kind: str, data: bytes) -> str:
        return key(kind, data)


def test_the_contract_finds_a_store_that_breaks_it(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="put schema@1"):
        contract.check_put_refuses(lambda: _LaxStore(tmp_path))


def test_a_symlinked_folder_is_refused(root: Path, tmp_path: Path) -> None:
    store = FolderStore(root)
    k = store.put("text@1", TEXT)
    outside = tmp_path / "outside"
    _object(root, k).parent.rename(outside)
    _object(root, k).parent.symlink_to(outside)
    with pytest.raises(StoreError, match="is not a folder"):
        store.get("text@1", k)


def test_read_refuses_a_torn_last_line_and_names_the_log(root: Path) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
    log = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".jsonl")
    with log.open("ab") as f:
        f.write(b'{"answer":"n')
    name = f"logs/answers/{PACKET[7:]}/{ANA[2][7:]}.jsonl"
    with pytest.raises(StoreError, match=f"{name} has a torn last line"):
        FolderStore(root).read(ANA)
    with pytest.raises(StoreError, match="torn last line"):
        FolderStore(root).append(ANA, {"answer": "no"})
    assert not (log.parent / (ANA[2][7:] + ".lock")).exists()  # a failed take keeps no lock


@pytest.mark.parametrize(
    "change",
    [
        lambda r: {**r, "answer": "no"},
        lambda r: {**r, "sequence": 3},
        lambda r: {**r, "previous": PACKET},
    ],
)
def test_read_checks_each_link(root: Path, change: Callable[[dict[str, object]], object]) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
        store.append(ANA, {"answer": "yes"})
        records = store.read(ANA)
    log = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".jsonl")
    log.write_text(jcs(records[0]) + "\n" + jcs(change(records[1])) + "\n")
    with pytest.raises(StoreError, match="line 2 does not continue the chain"):
        FolderStore(root).read(ANA)


def test_a_second_writer_stops_on_the_lock(root: Path) -> None:
    first = FolderStore(root)
    first.append(ANA, {"answer": "yes"})
    second = FolderStore(root)
    lock = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")
    with pytest.raises(Locked, match=str(lock)):
        second.append(ANA, {"answer": "no"})
    second.append(("answers", PACKET, reviewer_key("ben")), {"answer": "no"})  # another log
    assert [r["sequence"] for r in second.read(ANA)] == [1]  # a reader needs no lock
    first.append(ANA, {"answer": "no"})
    first.close()
    second.append(ANA, {"answer": "maybe"})
    assert [r["answer"] for r in second.read(ANA)] == ["yes", "no", "maybe"]
    assert [r["sequence"] for r in second.read(ANA)] == [1, 2, 3]
    second.close()


def test_forget_records_the_time(root: Path) -> None:
    moment = datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)
    with FolderStore(root, clock=lambda: moment) as store:
        k = store.put("text@1", TEXT)
        store.forget(k, "the tenant asked")
        (record,) = store.read(("deleted",))
    assert record["time"] == "2026-10-20T09:30:00Z"
    assert not _object(root, k).exists()
    assert (root / "logs" / "deleted.jsonl").is_file()


def test_a_log_over_the_byte_limit(root: Path) -> None:
    with FolderStore(root, max_bytes=300) as store:
        store.append(ANA, {"answer": "yes"})
        with pytest.raises(StoreError, match="would be larger than max_bytes"):
            store.append(ANA, {"answer": "x" * 200})
        assert len(store.read(ANA)) == 1


def test_a_bad_name_never_becomes_a_path(root: Path, tmp_path: Path) -> None:
    store = FolderStore(root)
    for bad in ("sha256:../../" + "a" * 57, "sha256:" + "a" * 62 + "/x"):
        with pytest.raises(ValueError):
            store.get("text@1", bad)
        with pytest.raises(ValueError):
            store.append(("answers", bad, PACKET), {"a": 1})
    assert list(tmp_path.iterdir()) == []


def test_the_core_does_not_import_the_store() -> None:
    code = "import sys, groundgate, groundgate.cli; print('groundgate.store' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
