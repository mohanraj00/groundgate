"""The store (docs/design/store.md): objects that never change and logs that only grow.

The key of an object is SHA-256 over ``groundgate-object/1:``, the kind, a zero byte and the
exact bytes (§4). A store has five operations: ``put``, ``get``, ``append``, ``read`` and
``forget`` (§6). ``FolderStore`` keeps the data in a folder (§7). The core (``admit``,
``verify``) does not import this package.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import unicodedata
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..canonical import jcs

__all__ = [
    "LOGS",
    "MAX_BYTES",
    "FolderStore",
    "Locked",
    "NotFound",
    "Store",
    "StoreError",
    "Torn",
    "key",
    "reviewer_key",
    "set_key",
]

PREFIX = b"groundgate-object/1:"
MAX_BYTES = 2**30
KEY = re.compile(r"sha256:[0-9a-f]{64}")
KIND = re.compile(r"[a-z][a-z0-9-]{0,62}@[1-9][0-9]{0,8}")
# The log kinds and the number of keys in each log name (§6, §7.1).
LOGS = {"answers": 2, "splits": 1, "deleted": 0}
CHAIN = ("sequence", "previous", "entry_sha256")
_UTF8 = frozenset({"text@1", "prompt@1", "reply@1"})
_RUN = re.compile(r"run@[1-9][0-9]{0,8}")
_HEX2 = re.compile(r"[0-9a-f]{2}")
_HEX62 = re.compile(r"[0-9a-f]{62}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_VIEW = re.compile(r"[a-z][a-z0-9-]{0,62}\.json")

LogName = tuple[str, ...]
Record = dict[str, Any]


class StoreError(Exception):
    """The store cannot do the operation. The message names the object, log or file."""


class NotFound(StoreError):
    """The object or the log is not in the store."""


class Locked(StoreError):
    """Another writer has the log. The message names the lock."""


class Torn(StoreError):
    """The last line of a log has no line break. ``groundgate store check --repair`` cuts it."""


class Store(Protocol):
    """The five operations of a store (§6). Bad input raises ``ValueError``, an absent object
    raises ``NotFound``, and data that does not match its key or chain raises ``StoreError``."""

    def put(self, kind: str, data: bytes) -> str: ...

    def get(self, kind: str, key: str) -> bytes: ...

    def append(self, log: LogName, record: Record) -> str: ...

    def read(self, log: LogName) -> list[Record]: ...

    def forget(self, key: str, reason: str) -> None: ...


def key(kind: str, data: bytes) -> str:
    """The store key of ``data`` as ``kind`` (§4)."""
    return _object_key(kind, data)


def _object_key(kind: str, data: bytes) -> str:
    _check_kind(kind)
    if not isinstance(data, bytes):
        raise TypeError("the data must be bytes")
    digest = hashlib.sha256(PREFIX + kind.encode("ascii") + b"\0" + data)
    return "sha256:" + digest.hexdigest()


def reviewer_key(name: str) -> str:
    """The store key of a reviewer name: the kind ``reviewer@1`` over its UTF-8. An answer log
    is filed under this digest, never under the name."""
    return key("reviewer@1", name.encode("utf-8"))


def set_key(name: str) -> str:
    """The store key of a set name: the kind ``set@1`` over its UTF-8. A splits log is filed
    under this digest, never under the name."""
    return key("set@1", name.encode("utf-8"))


def check_bytes(kind: str, data: bytes) -> None:
    """Raise ``ValueError`` if ``data`` is not a valid object of ``kind``. ``source@1`` takes
    any bytes. ``text@1`` is NFC UTF-8, and ``prompt@1`` and ``reply@1`` are UTF-8. ``run@N`` is
    one canonical JSON object on each line. All other kinds are canonical JSON, so one object has
    one key."""
    _check_kind(kind)
    if not isinstance(data, bytes):
        raise TypeError("the data must be bytes")
    if kind == "source@1":
        return
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"a {kind} object is not UTF-8") from exc
    if kind in _UTF8:
        if kind == "text@1" and not unicodedata.is_normalized("NFC", text):
            raise ValueError("a text@1 object is not NFC")
        return
    if _RUN.fullmatch(kind):
        if not text.endswith("\n"):
            raise ValueError(f"a {kind} object must end with a line break")
        for n, line in enumerate(text[:-1].split("\n"), 1):
            if not isinstance(_canonical(line, f"line {n} of the {kind} object"), dict):
                raise ValueError(f"line {n} of the {kind} object is not a JSON object")
        return
    _canonical(text, f"the {kind} object")


def _check_kind(kind: object) -> None:
    if not isinstance(kind, str) or not KIND.fullmatch(kind):
        raise ValueError(f"{_short(kind)} is not a kind such as text@1")


def _check_key(k: object) -> str:
    """The 64 hex digits of a key that matches ``sha256:[0-9a-f]{64}`` (§8 rule 1)."""
    if not isinstance(k, str) or not KEY.fullmatch(k):
        raise ValueError(f"{_short(k)} is not a store key")
    return k[7:]


def _check_log(log: object) -> tuple[str, list[str]]:
    """The log kind and the hex digits of each key in a log name."""
    if not isinstance(log, tuple) or not log or not isinstance(log[0], str) or log[0] not in LOGS:
        raise ValueError(f"{_short(log)} is not a log name such as ('answers', packet, reviewer)")
    word = log[0]
    if len(log) != 1 + LOGS[word]:
        raise ValueError(f"a {word} log name has {LOGS[word]} keys")
    return word, [_check_key(k) for k in log[1:]]


def _short(value: object) -> str:
    text = repr(value)
    return text if len(text) <= 80 else text[:77] + "..."


def _canonical(raw: str, what: str) -> Any:
    """The value of canonical JSON ``raw``, or ``ValueError``."""

    def pairs(items: list[tuple[str, Any]]) -> Record:
        result: Record = {}
        for name, value in items:
            if name in result:
                raise ValueError("a duplicate member")
            result[name] = value
        return result

    def constant(value: str) -> Any:
        raise ValueError(f"{value} is not a JSON number")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        same = jcs(value) == raw
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"{what} is not canonical JSON: {exc}") from exc
    if not same:
        raise ValueError(f"{what} is not canonical JSON")
    return value


def _entry_key(word: str, entry: Record) -> str:
    return key(f"{word}-entry@1", jcs(entry).encode("utf-8"))


def _records(word: str, data: bytes, rel: str) -> list[Record]:
    """The records of a log file, with each link checked."""
    if not data:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StoreError(f"{rel} is not UTF-8") from exc
    if not text.endswith("\n"):
        raise Torn(f"{rel} has a torn last line: it has no line break")
    records: list[Record] = []
    previous: str | None = None
    for n, line in enumerate(text[:-1].split("\n"), 1):
        try:
            entry = _canonical(line, f"line {n}")
        except ValueError as exc:
            raise StoreError(f"{rel}: {exc}") from exc
        if not isinstance(entry, dict) or any(m not in entry for m in CHAIN):
            raise StoreError(f"{rel}: line {n} is not a log record")
        body = {m: v for m, v in entry.items() if m != "entry_sha256"}
        if (
            type(entry["sequence"]) is not int
            or entry["sequence"] != n
            or entry["previous"] != previous
            or entry["entry_sha256"] != _entry_key(word, body)
        ):
            raise StoreError(f"{rel}: line {n} does not continue the chain")
        previous = entry["entry_sha256"]
        records.append(entry)
    return records


def _check_record(record: object) -> Record:
    if not isinstance(record, dict):
        raise ValueError("a log record must be a dict")
    taken = [m for m in CHAIN if m in record]
    if taken:
        raise ValueError(f"the store sets {', '.join(taken)}: remove it from the record")
    try:
        jcs(record)  # a record must have a canonical JSON form
    except (TypeError, RecursionError) as exc:
        raise ValueError(f"a log record has no canonical JSON form: {exc}") from exc
    return dict(record)


class FolderStore:
    """A store in a folder (§7). Each path part is 64 hex digits or a fixed word, so a name from
    input never becomes a path. Each file and folder that the store makes has mode 0600 or 0700,
    or 0640 or 0750 with ``group_read``. A read takes only regular files of at most
    ``max_bytes`` bytes, and refuses a symlink or a FIFO before it reads. The first append to a
    log makes ``<log>.lock`` with the process id, and ``close`` in that process removes it. A
    crashed writer leaves its lock, and a person removes it: the message says if the process
    is not running on this host. The store trusts the processes that can write to its folder.
    The root and its parents can be symlinks on purpose: the symlink checks start below the
    root.

    ``read`` holds a log and its records in memory, so one read can use several times
    ``max_bytes``. Choose a smaller ``max_bytes`` if the memory is small. Each append checks
    the folders of the log again. Where ``os.O_NOFOLLOW`` is absent, the symlink refusal is
    only a check before the open, and on Windows the file modes have no effect."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_bytes: int = MAX_BYTES,
        group_read: bool = False,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(root)
        self.max_bytes = max_bytes
        self.file_mode = 0o640 if group_read else 0o600
        self.folder_mode = 0o750 if group_read else 0o700
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # For each log that this writer holds: the next sequence, the head and the size.
        self._heads: dict[LogName, tuple[int, str | None, int]] = {}
        # Each lock that this writer made: the process id, the path and the bytes of the lock.
        self._locks: dict[LogName, tuple[int, Path, bytes]] = {}
        self._broken: set[LogName] = set()  # logs with a partial line that could not be removed

    def __enter__(self) -> FolderStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Remove the locks of this writer. A child process after a fork keeps the locks of its
        parent in place. A lock that another writer made after a person removed this one stays,
        because its bytes differ."""
        for pid, lock, mark in self._locks.values():
            if pid == os.getpid():
                self._unlink_own(lock, mark)
        self._locks.clear()
        self._heads.clear()
        self._broken.clear()

    # Objects

    def put(self, kind: str, data: bytes) -> str:
        """Write an object, and return its key. Equal bytes give the same key and one file. If
        the file of the key is a symlink, not a regular file, too large or has other bytes,
        ``put`` puts a new file in its place. It never writes through a symlink. A file with the
        right bytes and another mode also gets a new file with the file mode."""
        _check_kind(kind)
        if not isinstance(data, bytes):
            raise TypeError("the data must be bytes")
        if len(data) > self.max_bytes:  # before the parse, so a large input uses no memory
            raise ValueError(f"the {kind} object is larger than max_bytes")
        check_bytes(kind, data)
        k = key(kind, data)
        hexes = k[7:]
        folder = self._folder(["objects", hexes[:2]], make=True)
        path = folder / hexes[2:]
        try:
            same = self._file(path, f"objects/{hexes[:2]}/{hexes[2:]}") == data
            if same and stat.S_IMODE(os.lstat(path).st_mode) == self.file_mode:
                return k
        except (StoreError, FileNotFoundError):
            pass  # absent, other bytes or another mode: write the object again
        try:
            self._replace(folder, path, data, prefix=f".tmp-{hexes[2:]}-")
        except OSError as exc:  # for example a folder in the place of the object
            raise StoreError(f"objects/{hexes[:2]}/{hexes[2:]} cannot be written: {exc}") from exc
        return k

    def get(self, kind: str, key: str) -> bytes:
        """Read an object. The key is calculated again, and a difference raises
        ``StoreError``."""
        _check_kind(kind)
        hexes = _check_key(key)
        rel = f"objects/{hexes[:2]}/{hexes[2:]}"
        try:
            folder = self._folder(["objects", hexes[:2]], make=False)
        except NotFound as exc:
            raise NotFound(f"object {key} is not in the store") from exc
        data = self._file(folder / hexes[2:], rel)
        if _object_key(kind, data) != key:
            raise StoreError(f"{rel} does not match its key as {kind}")
        return data

    def forget(self, key: str, reason: str, *, run_keys: Sequence[str] = ()) -> None:
        """Remove an object, and record the key, the time and the reason in the deleted log.
        ``run_keys`` names the keys of a prompt, reply or admission in the run records of the
        store, and the record holds them sorted (§7.1). ``forget`` does not find them itself:
        ``groundgate store forget`` (``maintain.forget_packet``) gives them. With no run keys,
        the record has no ``run_keys`` member. The record comes first. After a crash between
        the two steps, the object is still there, and a second ``forget`` adds a second record
        for the key.

        ``forget`` also removes the ``.tmp-<key>-`` files that a killed ``put`` of this object
        left in its folder, also when the object is absent and ``forget`` raises ``NotFound``.
        Then ``forget`` writes no record in the deleted log. If the clean-up fails, for example
        on a folder that this process cannot list, ``forget`` raises ``StoreError``. It
        removes no file of another object, and no file outside that folder. A ``put`` of the
        same object at the same time can fail with ``StoreError``.
        A ``.tmp-`` file of an earlier version has no key in its name, so it stays. Where
        ``os.unlink`` takes no ``dir_fd``, for example on Windows, all ``.tmp-`` files stay."""
        hexes = _check_key(key)
        if not isinstance(reason, str) or not reason:
            raise ValueError("forget needs a reason")
        if isinstance(run_keys, str):
            raise ValueError("run_keys must be a sequence of keys, not one string")
        for r in run_keys:
            _check_key(r)
        runs = sorted(set(run_keys))
        rel = f"objects/{hexes[:2]}/{hexes[2:]}"
        try:
            folder = self._folder(["objects", hexes[:2]], make=False)
        except NotFound as exc:
            raise NotFound(f"object {key} is not in the store") from exc
        try:
            info = os.lstat(folder / hexes[2:])
        except FileNotFoundError as exc:
            self._unlink_parts(folder, hexes[2:], rel)  # a first put that was killed
            raise NotFound(f"object {key} is not in the store") from exc
        # Check that the unlink can work before the record says that it did.
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise StoreError(f"{rel} is not a file, so forget does not remove it")
        if not os.access(folder, os.W_OK | os.X_OK):
            raise StoreError(f"objects/{hexes[:2]} is not writable, so forget cannot remove {rel}")
        time = self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record: Record = {"key": key, "reason": reason, "time": time}
        if runs:
            record["run_keys"] = runs
        self._append(("deleted",), record)
        try:
            os.unlink(folder / hexes[2:])
        except OSError as exc:
            raise StoreError(f"{rel} is in the deleted log, but the unlink failed: {exc}") from exc
        self._unlink_parts(folder, hexes[2:], rel)

    def _unlink_parts(self, folder: Path, rest: str, rel: str) -> None:
        """Remove each regular file ``.tmp-<rest>-*`` in ``folder``. The names come from a
        listing of the open folder, and each unlink is relative to it, so a folder that becomes
        a symlink cannot send an unlink outside the store. A file that is gone already is not
        a problem. Each other failure raises ``StoreError``, so no caller thinks that the bytes
        are gone when they are not."""
        if not (os.unlink in os.supports_dir_fd and os.listdir in os.supports_fd):
            return  # pragma: no cover - Windows
        prefix = f".tmp-{rest}-"
        try:
            fd = os.open(folder, os.O_RDONLY | _NOFOLLOW | getattr(os, "O_DIRECTORY", 0))
        except OSError as exc:
            raise StoreError(
                f"the temporary files of {rel} cannot be removed: {exc.strerror}"
            ) from exc
        try:
            for name in os.listdir(fd):
                if not name.startswith(prefix):
                    continue
                try:  # a put that ends now removes its own file
                    if stat.S_ISREG(os.stat(name, dir_fd=fd, follow_symlinks=False).st_mode):
                        os.unlink(name, dir_fd=fd)
                except FileNotFoundError:
                    continue
        except OSError as exc:
            raise StoreError(
                f"the temporary files of {rel} cannot be removed: {exc.strerror}"
            ) from exc
        finally:
            os.close(fd)

    # Logs

    def append(self, log: LogName, record: Record) -> str:
        """Add a record to a log, and return the new head. The store sets ``sequence``,
        ``previous`` and ``entry_sha256``. Only ``forget`` writes the deleted log."""
        word, _ = _check_log(log)
        if word == "deleted":
            raise ValueError("only forget writes the deleted log")
        return self._append(log, record)

    def take(self, log: LogName) -> None:
        """Take the lock of a log now, as the first append does, and keep it until ``close``. A
        writer that must read a log and then append to it takes the lock first, so no other
        writer can append between the read and the append. A second writer stops with
        ``Locked``. If this writer holds the log already, ``take`` does nothing."""
        word, _ = _check_log(log)
        if word == "deleted":
            raise ValueError("only forget writes the deleted log")
        if log not in self._heads:
            self._take(log)

    def read(self, log: LogName) -> list[Record]:
        """The records of a log in order, with each link checked. An absent log has none. A
        torn last line raises ``StoreError`` with the name of the log. A read takes no lock, so
        while a writer appends, it can see a line that is not complete yet. Then read again."""
        word, _ = _check_log(log)
        parts, name = self._log_parts(log)
        rel = "/".join([*parts, name + ".jsonl"])
        try:
            data = self._file(self._folder(parts, make=False) / f"{name}.jsonl", rel)
        except NotFound:
            return []
        return _records(word, data, rel)

    # Maintenance: the folder walks of `groundgate store check`, `rebuild` and `forget`

    def object_keys(self) -> tuple[list[str], list[str]]:
        """The key of each object file, in order, and a problem for each other entry under
        ``objects``. A ``.tmp-`` file of a killed ``put`` is not a problem."""
        keys: list[str] = []
        problems: list[str] = []
        try:
            top = self._folder(["objects"], make=False)
        except NotFound:
            return keys, problems
        for first in sorted(os.listdir(top)):
            rel = f"objects/{first}"
            if not (_HEX2.fullmatch(first) and stat.S_ISDIR(os.lstat(top / first).st_mode)):
                problems.append(f"{rel} is not an object folder")
                continue
            for rest in sorted(os.listdir(top / first)):
                if rest.startswith(".tmp-"):
                    continue
                if not _HEX62.fullmatch(rest):
                    problems.append(f"{rel}/{rest} is not an object file")
                    continue
                keys.append(f"sha256:{first}{rest}")
        return keys, problems

    def object_bytes(self, key: str) -> bytes:
        """The bytes of the object file of ``key``, with no check of the key. ``check`` uses
        this to find the kind of an object, because the key covers the kind."""
        hexes = _check_key(key)
        rel = f"objects/{hexes[:2]}/{hexes[2:]}"
        try:
            folder = self._folder(["objects", hexes[:2]], make=False)
        except NotFound as exc:
            raise NotFound(f"object {key} is not in the store") from exc
        return self._file(folder / hexes[2:], rel)

    def log_names(self) -> tuple[list[LogName], list[str]]:
        """The name of each log file, in order, and a problem for each other entry under
        ``logs``. A ``.lock`` file is not a problem."""
        names: list[LogName] = []
        problems: list[str] = []
        try:
            top = self._folder(["logs"], make=False)
        except NotFound:
            return names, problems

        def kind(path: Path) -> str:
            mode = os.lstat(path).st_mode
            return "dir" if stat.S_ISDIR(mode) else "file" if stat.S_ISREG(mode) else "other"

        def stem(entry: str) -> str | None:
            if entry.endswith(".jsonl") and _HEX64.fullmatch(entry[:-6]):
                return entry[:-6]
            return None

        for entry in sorted(os.listdir(top)):
            rel = f"logs/{entry}"
            if entry == "deleted.jsonl" and kind(top / entry) == "file":
                names.append(("deleted",))
            elif entry in ("deleted.lock", "answers", "splits"):
                continue
            else:
                problems.append(f"{rel} is not a log")
        for word in ("splits", "answers"):
            folder = top / word
            if not folder.exists() and not folder.is_symlink():
                continue
            if kind(folder) != "dir":
                problems.append(f"logs/{word} is not a folder")
                continue
            for entry in sorted(os.listdir(folder)):
                rel = f"logs/{word}/{entry}"
                if word == "splits":
                    found = stem(entry)
                    if found is not None and kind(folder / entry) == "file":
                        names.append(("splits", "sha256:" + found))
                    elif not (entry.endswith(".lock") and stem(entry[:-5] + ".jsonl")):
                        problems.append(f"{rel} is not a log")
                    continue
                if not (_HEX64.fullmatch(entry) and kind(folder / entry) == "dir"):
                    problems.append(f"{rel} is not a packet folder")
                    continue
                for name in sorted(os.listdir(folder / entry)):
                    found = stem(name)
                    if found is not None and kind(folder / entry / name) == "file":
                        names.append(("answers", "sha256:" + entry, "sha256:" + found))
                    elif not (name.endswith(".lock") and stem(name[:-5] + ".jsonl")):
                        problems.append(f"{rel}/{name} is not a log")
        return names, problems

    def repair(self, log: LogName) -> bytes | None:
        """Cut a torn last line from a log, and return the bytes that were cut, or ``None`` if
        the log has no torn line. ``repair`` takes the lock of the log for the cut."""
        _check_log(log)
        if log in self._heads:
            raise StoreError("this writer holds the log: close the store, then repair")
        parts, name = self._log_parts(log)
        rel = "/".join([*parts, name + ".jsonl"])
        folder = self._folder(parts, make=False)
        with self._hold(folder, name):
            data = self._file(folder / f"{name}.jsonl", rel)
            if not data or data.endswith(b"\n"):
                return None
            size = data.rfind(b"\n") + 1
            fd = os.open(folder / f"{name}.jsonl", os.O_WRONLY | _NOFOLLOW | _NONBLOCK)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise StoreError(f"{rel} is not a regular file")
                os.ftruncate(fd, size)
                os.fsync(fd)
            finally:
                os.close(fd)
            return data[size:]

    @contextlib.contextmanager
    def _hold(self, folder: Path, name: str) -> Iterator[None]:
        """Hold the lock of the log ``folder/<name>.jsonl`` for one change, then remove it."""
        lock = folder / f"{name}.lock"
        mark = f"{os.getpid()}\n{secrets.token_hex(16)}\n".encode("ascii")
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, self.file_mode)
        except FileExistsError as exc:
            raise Locked(f"{lock} exists: {self._holder(lock)}") from exc
        try:
            try:
                os.write(fd, mark)
            finally:
                os.close(fd)
            yield
        finally:
            self._unlink_own(lock, mark)

    def forget_log(self, log: LogName, reason: str) -> None:
        """Remove an answer log or a splits log, and record the log name, the time and the
        reason in the deleted log. ``forget_log`` holds the lock of the log for the change, so
        another writer of the log stops it with ``Locked``."""
        word, _ = _check_log(log)
        if word == "deleted":
            raise ValueError("forget_log does not remove the deleted log")
        if not isinstance(reason, str) or not reason:
            raise ValueError("forget needs a reason")
        if log in self._heads:
            raise StoreError("this writer holds the log: close the store, then forget it")
        parts, name = self._log_parts(log)
        rel = "/".join([*parts, name + ".jsonl"])
        try:
            folder = self._folder(parts, make=False)
            info = os.lstat(folder / f"{name}.jsonl")
        except (NotFound, FileNotFoundError) as exc:
            raise NotFound(f"{rel} is not in the store") from exc
        if not stat.S_ISREG(info.st_mode):
            raise StoreError(f"{rel} is not a regular file, so forget does not remove it")
        with contextlib.ExitStack() as stack:
            try:  # no writer can append while the log goes
                stack.enter_context(self._hold(folder, name))
            except FileNotFoundError as exc:  # another forget removed the folder
                raise NotFound(f"{rel} is not in the store") from exc
            if not os.path.lexists(folder / f"{name}.jsonl"):  # gone after the lstat
                raise NotFound(f"{rel} is not in the store")
            time = self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._append(("deleted",), {"log": list(log), "reason": reason, "time": time})
            try:
                os.unlink(folder / f"{name}.jsonl")
            except OSError as exc:
                raise StoreError(
                    f"{rel} is in the deleted log, but the unlink failed: {exc}"
                ) from exc
        if word == "answers":
            with contextlib.suppress(OSError):  # the packet folder, if it is now empty
                os.rmdir(folder)

    def write_view(self, name: str, data: bytes) -> str:
        """Write the view file ``views/<name>`` in place of the old one, and return its path in
        the store. ``name`` is a fixed word of the code, never a name from input."""
        if not _VIEW.fullmatch(name):
            raise ValueError(f"{_short(name)} is not a view name")
        folder = self._folder(["views"], make=True)
        self._replace(folder, folder / name, data)
        return f"views/{name}"

    def _append(self, log: LogName, record: Record) -> str:
        word, _ = _check_log(log)
        body = _check_record(record)
        parts, name = self._log_parts(log)
        rel = "/".join([*parts, name + ".jsonl"])
        if log in self._broken:
            raise StoreError(f"an earlier append to {rel} failed: check the log, then close")
        if log not in self._heads:
            self._take(log)
        pid, _, _ = self._locks[log]
        if pid != os.getpid():
            raise StoreError(f"process {pid} holds the lock of {rel}: a forked child cannot append")
        self._folder(parts, make=False)  # a folder of the log can become a symlink after the take
        sequence, previous, size = self._heads[log]
        entry = {**body, "sequence": sequence, "previous": previous}
        head = _entry_key(word, entry)
        line = (jcs({**entry, "entry_sha256": head}) + "\n").encode("utf-8")
        if size + len(line) > self.max_bytes:
            raise StoreError(f"{rel} would be larger than max_bytes")
        path = self.root.joinpath(*parts, name + ".jsonl")
        try:  # O_NONBLOCK: a FIFO with no reader fails, and does not block
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | _NOFOLLOW | _NONBLOCK)
        except OSError as exc:
            raise StoreError(f"{rel} cannot be opened: {exc.strerror}") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StoreError(f"{rel} is not a regular file")
            try:
                view = memoryview(line)
                while view:
                    view = view[os.write(fd, view) :]
                os.fsync(fd)
            except BaseException:
                try:  # remove the part of the line that was written
                    os.ftruncate(fd, size)
                except OSError:
                    self._broken.add(log)
                raise
        finally:
            os.close(fd)
        self._heads[log] = (sequence + 1, head, size + len(line))
        return head

    def _take(self, log: LogName) -> None:
        """Make the lock of a log, then read the log to find its head."""
        word, _ = _check_log(log)
        parts, name = self._log_parts(log)
        folder = self._folder(parts, make=True)
        lock = folder / f"{name}.lock"
        try:
            fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, self.file_mode)
        except FileExistsError as exc:
            raise Locked(f"{lock} exists: {self._holder(lock)}") from exc
        # The token tells this lock from a later lock at the same path. An inode can be reused.
        mark = f"{os.getpid()}\n{secrets.token_hex(16)}\n".encode("ascii")
        try:
            try:
                view = memoryview(mark)
                while view:
                    view = view[os.write(fd, view) :]
            finally:
                os.close(fd)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(lock)  # this writer made it a moment ago
            raise
        try:
            rel = "/".join([*parts, name + ".jsonl"])
            path = folder / f"{name}.jsonl"
            try:
                data = self._file(path, rel)
            except NotFound:
                data = b""
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, self.file_mode)
                try:
                    _chmod(fd, path, self.file_mode)
                finally:
                    os.close(fd)
            records = _records(word, data, rel)
            self._log_mode(path, rel)
        except BaseException:
            self._unlink_own(lock, mark)
            raise
        self._locks[log] = (os.getpid(), lock, mark)
        head = records[-1]["entry_sha256"] if records else None
        self._heads[log] = (len(records) + 1, head, len(data))

    def _log_mode(self, path: Path, rel: str) -> None:
        """Give a log that the store did not make, for example one from a backup, the file
        mode."""
        if stat.S_IMODE(os.lstat(path).st_mode) == self.file_mode:
            return
        try:
            fd = os.open(path, os.O_WRONLY | _NOFOLLOW | _NONBLOCK)
        except OSError as exc:
            raise StoreError(f"{rel} cannot be opened: {exc.strerror}") from exc
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise StoreError(f"{rel} is not a regular file")
            _chmod(fd, path, self.file_mode)
        finally:
            os.close(fd)

    def _unlink_own(self, lock: Path, mark: bytes) -> None:
        """Remove a lock only if it still holds the bytes that this writer wrote. The compare
        and the unlink are two steps, so they are not atomic. A lock of another writer can go
        only if a person removes this lock and that writer makes its lock between the two
        steps. A lock that is not a regular file, for example a symlink in the place of the
        lock, stays, and the next writer stops with ``Locked``. A person removes it."""
        try:
            if os.lstat(lock).st_size != len(mark) or self._file(lock, lock.name) != mark:
                return
        except (OSError, StoreError):
            return
        with contextlib.suppress(FileNotFoundError):
            os.unlink(lock)

    def _holder(self, lock: Path) -> str:
        """Who holds a lock, as far as the store can tell."""
        text = "another writer has this log."
        try:
            if os.lstat(lock).st_size > 64:  # a pid, a token and two line breaks are short
                raise ValueError("the lock is too large")
            line = self._file(lock, lock.name).decode("ascii").split("\n")[0]
            if not (line.isascii() and line.isdigit()):  # int() takes "1_0" and " 10"
                raise ValueError("not a process id")
            pid = int(line)
            if pid <= 0:
                raise ValueError("not a process id")
        except (OSError, StoreError, ValueError):
            return text + " If no writer runs, remove the lock."
        text = f"process {pid} made the lock."
        if os.name == "posix":  # on Windows, os.kill stops the process
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return text + " That process is not running on this host: remove the lock."
            except (OSError, OverflowError):  # OverflowError: a pid that no process can have
                pass
        return text + " If it does not run, remove the lock."

    @staticmethod
    def _log_parts(log: LogName) -> tuple[list[str], str]:
        """The folder parts and the file stem of a log: for example ``logs/answers/<packet>``
        and ``<reviewer>``, or ``logs`` and ``deleted``."""
        word, hexes = _check_log(log)
        if not hexes:
            return ["logs"], word
        return ["logs", word, *hexes[:-1]], hexes[-1]

    # Files

    def _folder(self, parts: list[str], *, make: bool) -> Path:
        """The folder ``root/parts``. Each part must be a folder, not a symlink. With ``make``,
        absent folders are made with the folder mode, else ``NotFound`` is raised. A root that
        is a file or a dangling symlink, or another failed folder call, raises ``StoreError``."""
        try:
            return self._walk(parts, make=make)
        except StoreError:
            raise
        except OSError as exc:
            where = "/".join(parts) or "the root"
            raise StoreError(f"{where} in {self.root} cannot be used: {exc.strerror}") from exc

    def _walk(self, parts: list[str], *, make: bool) -> Path:
        path = self.root
        if make and not path.exists():
            absent = [path, *(p for p in path.parents if not p.exists())]
            for folder in reversed(absent):  # each folder that the store makes gets its mode
                try:
                    os.mkdir(folder, self.folder_mode)
                except FileExistsError:
                    continue
                os.chmod(folder, self.folder_mode)
        for n, part in enumerate(parts):
            path = path / part
            try:
                info = os.lstat(path)
            except FileNotFoundError:
                if not make:
                    raise NotFound(f"{'/'.join(parts[: n + 1])} is not in the store") from None
                try:
                    os.mkdir(path, self.folder_mode)
                except FileExistsError:
                    pass
                else:
                    os.chmod(path, self.folder_mode)
                info = os.lstat(path)
            if not stat.S_ISDIR(info.st_mode):
                raise StoreError(f"{'/'.join(parts[: n + 1])} is not a folder")
        return path

    def _file(self, path: Path, rel: str) -> bytes:
        """The bytes of a regular file of at most ``max_bytes`` bytes. A symlink, a FIFO or a
        device is refused before any read."""
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            raise NotFound(f"{rel} is not in the store") from None
        if stat.S_ISLNK(info.st_mode):
            raise StoreError(f"{rel} is a symlink")
        if not stat.S_ISREG(info.st_mode):
            raise StoreError(f"{rel} is not a regular file")
        if info.st_size > self.max_bytes:
            raise StoreError(f"{rel} is larger than max_bytes")
        flags = os.O_RDONLY | _NOFOLLOW | _NONBLOCK | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(path, flags)
        except FileNotFoundError:
            raise NotFound(f"{rel} is not in the store") from None
        except OSError as exc:  # a symlink put in place after the check
            raise StoreError(f"{rel} cannot be opened: {exc.strerror}") from exc
        with open(fd, "rb") as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise StoreError(f"{rel} is not a regular file")
            if info.st_size > self.max_bytes:
                raise StoreError(f"{rel} is larger than max_bytes")
            # Read the size from fstat and one byte more, not max_bytes + 1: a read asks for a
            # buffer of its full size. A file that grew after fstat is read to its end in parts.
            parts = [f.read(info.st_size + 1)]
            size = len(parts[0])
            while size > info.st_size and size <= self.max_bytes:
                part = f.read(min(_PART, self.max_bytes + 1 - size))
                if not part:
                    break
                parts.append(part)
                size += len(part)
            data = b"".join(parts)
        if len(data) > self.max_bytes:
            raise StoreError(f"{rel} is larger than max_bytes")
        return data

    def _replace(self, folder: Path, path: Path, data: bytes, *, prefix: str = ".tmp-") -> None:
        """Write ``data`` to a temporary file in ``folder``, then rename it to ``path``. A crash
        never leaves half an object."""
        fd, name = tempfile.mkstemp(dir=folder, prefix=prefix)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                _chmod(out.fileno(), Path(name), self.file_mode)
                os.fsync(out.fileno())
            os.replace(name, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(name)
            raise


_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)
_PART = 1 << 20  # the bytes of each read after a file grew


def _chmod(fd: int, path: Path, mode: int) -> None:
    if hasattr(os, "fchmod"):
        os.fchmod(fd, mode)
    else:  # pragma: no cover - Windows
        os.chmod(path, mode)
