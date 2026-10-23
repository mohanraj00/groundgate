"""The store of docs/design/store.md: the contract on the folder store, and the folder rules."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
import tempfile
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


def test_take_holds_the_lock_before_the_first_append(root: Path) -> None:
    first = FolderStore(root)
    first.take(ANA)
    first.take(ANA)  # a second take of a held log does nothing
    with pytest.raises(Locked), FolderStore(root) as second:
        second.append(ANA, {"answer": "no"})
    first.append(ANA, {"answer": "yes"})
    first.close()
    assert [r["answer"] for r in FolderStore(root).read(ANA)] == ["yes"]
    with pytest.raises(ValueError, match="only forget writes the deleted log"):
        FolderStore(root).take(("deleted",))


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


# The security review of #415


def test_put_checks_the_size_before_it_parses(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import groundgate.store as module

    def parse(kind: str, data: bytes) -> None:
        raise AssertionError("put parsed an input over the limit")

    monkeypatch.setattr(module, "check_bytes", parse)
    with pytest.raises(ValueError, match="larger than max_bytes"):
        FolderStore(root, max_bytes=16).put("schema@1", b"[" + b"1," * 20 + b"1]")


def test_a_failed_pid_write_leaves_no_lock(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(fd: int, data: object) -> int:
        raise OSError(28, "No space left on device")

    store = FolderStore(root)
    monkeypatch.setattr(os, "write", fail)
    with pytest.raises(OSError, match="No space"):
        store.append(ANA, {"answer": "yes"})
    monkeypatch.undo()
    assert not (root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")).exists()
    store.append(ANA, {"answer": "yes"})
    store.close()


def test_each_append_checks_the_folders_again(root: Path, tmp_path: Path) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
        folder = root / "logs" / "answers" / PACKET[7:]
        outside = tmp_path / "outside"
        folder.rename(outside)
        folder.symlink_to(outside)
        with pytest.raises(StoreError, match="is not a folder"):
            store.append(ANA, {"answer": "no"})
        assert len((outside / (ANA[2][7:] + ".jsonl")).read_text().splitlines()) == 1
        folder.unlink()
        outside.rename(folder)


def test_a_symlink_is_refused_without_o_nofollow(
    root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import groundgate.store as module

    monkeypatch.setattr(module, "_NOFOLLOW", 0)
    store = FolderStore(root)
    k = store.put("text@1", TEXT)
    secret = tmp_path / "secret"
    secret.write_bytes(TEXT)
    _object(root, k).unlink()
    _object(root, k).symlink_to(secret)
    with pytest.raises(StoreError, match="is a symlink"):
        store.get("text@1", k)


def test_put_repairs_the_mode_of_a_file(root: Path) -> None:
    store = FolderStore(root)
    path = _object(root, store.put("text@1", TEXT))
    path.chmod(0o644)
    store.put("text@1", TEXT)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_forked_child_keeps_the_locks_of_its_parent(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FolderStore(root)
    store.append(ANA, {"answer": "yes"})
    lock = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")
    parent = os.getpid()
    monkeypatch.setattr(os, "getpid", lambda: parent + 1)  # the view of a child
    with pytest.raises(StoreError, match="a forked child cannot append"):
        store.append(ANA, {"answer": "no"})
    store.close()
    assert lock.exists()
    monkeypatch.undo()
    lock.unlink()


@pytest.mark.skipif(os.name != "posix", reason="the check of a process is for POSIX")
def test_a_stale_lock_names_a_process_that_is_not_running(root: Path) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    lock = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")
    lock.write_text(f"{child.pid}\n")
    with pytest.raises(Locked, match=f"process {child.pid} made the lock. That process is not"):
        FolderStore(root).append(ANA, {"answer": "no"})
    lock.write_text(f"{os.getpid()}\n")
    with pytest.raises(Locked, match="If it does not run, remove the lock"):
        FolderStore(root).append(ANA, {"answer": "no"})


# The reviews of cff0ac0


def test_a_lock_with_a_pid_too_large_for_a_process(root: Path) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
    lock = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")
    lock.write_text("99999999999999999999\n")
    with pytest.raises(Locked, match="process 99999999999999999999 made the lock"):
        FolderStore(root).append(ANA, {"answer": "no"})


def test_put_over_a_folder_raises_a_store_error(root: Path) -> None:
    store = FolderStore(root)
    path = _object(root, key("text@1", TEXT))
    path.mkdir(parents=True)
    (path / "x").write_text("x")
    with pytest.raises(StoreError, match="cannot be written"):
        store.put("text@1", TEXT)


def test_a_read_does_not_ask_for_max_bytes_of_memory(root: Path) -> None:
    store = FolderStore(root, max_bytes=2**62)  # a buffer of this size cannot exist
    k = store.put("text@1", TEXT)
    assert store.get("text@1", k) == TEXT


def test_forget_writes_no_record_when_it_cannot_remove(root: Path) -> None:
    store = FolderStore(root)
    k = key("text@1", TEXT)
    _object(root, k).mkdir(parents=True)
    with pytest.raises(StoreError, match="is not a file"):
        store.forget(k, "test")
    _object(root, k).rmdir()
    k = store.put("text@1", TEXT)
    if os.geteuid() == 0:
        pytest.skip("root can write to any folder")
    _object(root, k).parent.chmod(0o500)
    try:
        with pytest.raises(StoreError, match="is not writable"):
            store.forget(k, "test")
    finally:
        _object(root, k).parent.chmod(0o700)
    assert store.read(("deleted",)) == []
    assert store.get("text@1", k) == TEXT


def test_a_read_takes_the_bytes_that_a_writer_adds_after_fstat(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import groundgate.store as module

    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
        fstat = os.fstat

        def grow(fd: int) -> os.stat_result:
            info = fstat(fd)
            monkeypatch.setattr(os, "fstat", fstat)
            store.append(ANA, {"answer": "x" * 200})  # a writer between fstat and read
            return info

        monkeypatch.setattr(module, "_PART", 7)  # read the new bytes in small parts
        monkeypatch.setattr(os, "fstat", grow)
        assert [r["sequence"] for r in FolderStore(root).read(ANA)] == [1, 2]


def test_a_log_from_a_backup_gets_the_file_mode(root: Path) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
    log = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".jsonl")
    log.chmod(0o644)
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "no"})
    assert stat.S_IMODE(log.stat().st_mode) == 0o600


def test_put_checks_the_kind_before_the_size(root: Path) -> None:
    with pytest.raises(ValueError, match="is not a kind"):
        FolderStore(root, max_bytes=4).put("x" * 1000, b"too large")


def test_close_keeps_a_lock_that_another_writer_made(root: Path) -> None:
    first = FolderStore(root)
    first.append(ANA, {"answer": "yes"})
    lock = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")
    lock.unlink()  # a person removes what looks like a stale lock
    second = FolderStore(root)
    second.append(ANA, {"answer": "no"})
    first.close()
    assert lock.exists()
    with pytest.raises(Locked):
        FolderStore(root).append(ANA, {"answer": "maybe"})
    second.close()
    assert not lock.exists()


# The review of #415 (#417)


def test_forget_removes_the_temporary_files_of_its_object_only(root: Path, tmp_path: Path) -> None:
    store = FolderStore(root)
    k = store.put("text@1", TEXT)
    other = store.put("text@1", b"The deposit is 600 dollars.")
    folder = _object(root, k).parent
    mine = folder / f".tmp-{k[9:]}-abc123"
    mine.write_bytes(b"half")
    # The same first two hex digits: a temporary file of another object in the same folder.
    near = folder / f".tmp-{k[9:-1]}{'0' if k[-1] != '0' else '1'}-abc123"
    near.write_bytes(b"other")
    old = folder / ".tmp-1"  # an earlier version: no key in the name
    old.write_bytes(b"old")
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    link = folder / f".tmp-{k[9:]}-link"
    link.symlink_to(outside)
    sub = folder / f".tmp-{k[9:]}-folder"
    sub.mkdir()
    other_folder = _object(root, other).parent
    theirs = other_folder / f".tmp-{k[9:]}-xyz"  # the name of this object in another folder
    if other_folder != folder:
        theirs.write_bytes(b"theirs")
    store.forget(k, "the tenant asked")
    assert not _object(root, k).exists()
    assert not mine.exists()
    assert near.read_bytes() == b"other"
    assert old.read_bytes() == b"old"
    assert link.is_symlink() and outside.read_bytes() == b"keep"
    assert sub.is_dir()
    assert _object(root, other).exists()
    if other_folder != folder:
        assert theirs.read_bytes() == b"theirs"
    assert store.object_keys() == ([other], [])


def test_a_put_names_its_object_in_the_temporary_file(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names: list[str] = []
    real = tempfile.mkstemp

    def keep(**kwargs: str) -> tuple[int, str]:
        fd, name = real(**kwargs)
        names.append(name)
        return fd, name

    monkeypatch.setattr(tempfile, "mkstemp", keep)
    k = FolderStore(root).put("text@1", TEXT)
    assert Path(names[0]).name.startswith(f".tmp-{k[9:]}-")


@pytest.mark.parametrize("make", ["file", "dangling"])
def test_a_root_that_is_not_a_folder_raises_a_store_error(tmp_path: Path, make: str) -> None:
    root = tmp_path / "store"
    if make == "file":
        root.write_text("x")
    else:
        root.symlink_to(tmp_path / "absent")
    store = FolderStore(root)
    with pytest.raises(StoreError, match="cannot be used"):
        store.put("text@1", TEXT)
    with pytest.raises(StoreError, match="cannot be used"):
        store.append(ANA, {"answer": "yes"})
    if make == "file":
        with pytest.raises(StoreError, match="cannot be used"):
            store.read(ANA)
    else:
        assert store.read(ANA) == []


@pytest.mark.parametrize("text", ["1_0", " 10", "+10", "\u0661\u0660"])
def test_a_lock_with_a_pid_that_is_not_only_digits(root: Path, text: str) -> None:
    with FolderStore(root) as store:
        store.append(ANA, {"answer": "yes"})
    lock = root / "logs" / "answers" / PACKET[7:] / (ANA[2][7:] + ".lock")
    lock.write_bytes(f"{text}\n".encode())
    with pytest.raises(Locked, match="another writer has this log") as info:
        FolderStore(root).append(ANA, {"answer": "no"})
    assert "process 10" not in str(info.value)
