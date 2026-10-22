"""The ``splits`` log of #383 (docs/design/store.md §10).

A set has one ``splits`` log, filed under the store key of its name (``set_key``). Each record
is ``{"set": NAME, "document": KEY, "split": NAME}``, where ``document`` is the source key, or
the text key when there is no source. A record is written one time, before any label or model
output for the document.

``read_split`` is the view of the log: the split of each document. If two records give one
document two splits, the view fails, and each tool that reads it stops. ``write_split`` adds
only the records that the log does not have, and it adds none if the log already gives one of
the documents another split. The log is untrusted input, so a message shows its values with
no control character.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import KEY, FolderStore, Store, set_key
from .packets import printable

__all__ = ["read_split", "split_view", "write_split"]


def split_view(records: Sequence[Mapping[str, Any]], log_key: str) -> dict[str, str]:
    """The split of each document in the records of the splits log ``log_key``. A record of
    another set, a record that is not a split record, or a second split for one document
    raises ``ValueError``."""
    out: dict[str, str] = {}
    for r in records:
        name, document, split = r.get("set"), r.get("document"), r.get("split")
        where = f"splits record {printable(r.get('sequence'))}"
        if not isinstance(name, str) or set_key(name) != log_key:
            raise ValueError(f"{where} names another set")
        if not isinstance(document, str) or not KEY.fullmatch(document):
            raise ValueError(f"{where} has no document key")
        if not isinstance(split, str) or not split:
            raise ValueError(f"{where} has no split")
        if out.setdefault(document, split) != split:
            raise ValueError(f"the splits log gives the document {document} two splits")
    return out


def read_split(store: Store, set_name: str) -> dict[str, str]:
    """The split of each document of the set ``set_name``, from its splits log. An absent log
    gives no document. A bad record or a second split for one document raises
    ``ValueError``."""
    log_key = set_key(set_name)
    return split_view(store.read(("splits", log_key)), log_key)


def write_split(store: Store, set_name: str, splits: Mapping[str, str]) -> int:
    """Add a record to the splits log of ``set_name`` for each document of ``splits`` (a
    document key to its split) that the log does not name, in key order. Return the number
    of records added. If the log already gives a document another split, raise
    ``ValueError`` and add no record.

    With a ``FolderStore``, the call takes the lock of the log before it reads the log, so a
    second writer stops with ``Locked`` before it appends. The lock stays until the store
    closes. Another store has no lock operation (§6): there the check comes before the lock,
    and if another writer appends another split for a document at the same time, both records
    go in. Then the view fails, and this call raises ``ValueError`` after its records are
    added."""
    if not isinstance(set_name, str) or not set_name.strip():
        raise ValueError("a set name must have a character that is not a space")
    for document, split in splits.items():
        if not isinstance(document, str) or not KEY.fullmatch(document):
            raise ValueError(f"{printable(document)} is not a document key")
        if not isinstance(split, str) or not split:
            raise ValueError(f"the split of {document} is not a name")
    if splits and isinstance(store, FolderStore):
        store.take(("splits", set_key(set_name)))
    known = read_split(store, set_name)
    for document in sorted(splits):
        if known.get(document, splits[document]) != splits[document]:
            raise ValueError(
                f"the splits log of {printable(set_name)} gives the document {document} the "
                f"split {printable(known[document])}, not {printable(splits[document])}"
            )
    added = 0
    for document in sorted(splits):
        if document not in known:
            record = {"set": set_name, "document": document, "split": splits[document]}
            store.append(("splits", set_key(set_name)), record)
            added += 1
    if added:
        # A store with no lock takes it at the first append. A writer that appended before it
        # can have given a document another split: then the view fails here.
        read_split(store, set_name)
    return added
