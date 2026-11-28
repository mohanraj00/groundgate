# groundgate.store.FolderStore

Release: main, before 1.0.0 (spec 0.13).

`FolderStore` keeps the objects and the logs of groundgate in a folder: documents, packets,
receipts, review answers and deletions. An object never changes, and a log only grows.

## Call

```text
FolderStore(root, *, max_bytes=2**30, group_read=False, clock=None)
```

- `root`: the folder. The store makes it at the first write.
- `max_bytes`: the largest object or log that the store writes or reads, 1 GiB by default.
- `group_read`: `True` gives files mode 0640 and folders 0750. The default is 0600 and 0700.
- `clock`: a function that gives the time of a deletion record. The default is the UTC time now.

The five operations of the `Store` protocol:

| Operation | What it does |
|---|---|
| `put(kind, data)` | Writes the bytes as an object of `kind`, such as `text@1`, and returns its key. |
| `get(kind, key)` | Reads an object, and calculates its key again. |
| `append(log, record)` | Adds a record to a log, and returns the new head. |
| `read(log)` | Gives the records of a log in order, with each link checked. |
| `forget(key, reason)` | Removes an object, and records the key, the time and the reason. |

A log name is a tuple, such as `("answers", packet, reviewer)` or `("deleted",)`. Use the store
in a `with` block, or call `close()`: it removes the log locks of this writer.

## Example

```python
import tempfile

from groundgate.store import FolderStore, NotFound, key

data = "The IRA contribution limit is $7,000.\n".encode("utf-8")
with tempfile.TemporaryDirectory() as root, FolderStore(root) as store:
    k = store.put("text@1", data)
    print(k == key("text@1", data), store.get("text@1", k) == data)
    store.forget(k, "the owner asked")
    print([r["reason"] for r in store.read(("deleted",))])
    try:
        store.get("text@1", k)
    except NotFound as error:
        print(type(error).__name__, str(error).endswith("is not in the store"))
```

```text
True True
['the owner asked']
NotFound True
```

## Result

`put` and `append` return a store key, `sha256:` and 64 hex digits. The key of an object is
SHA-256 over `groundgate-object/1:`, the kind, a zero byte and the bytes. Equal bytes give the
same key and one file. `read` gives a list of dicts. The store adds `sequence`, `previous` and
`entry_sha256` to each record. An absent log has no records.

## Errors

- `NotFound` (a `StoreError`): `objects/0f/4a16... is not in the store`.
- `ValueError`: `put` of an object larger than `max_bytes`.
- `StoreError`: a file that does not match its key, a symlink, a file that is not regular, or a
  file larger than `max_bytes`.
- `Locked` (a `StoreError`): another writer holds the log. The message names the lock file.
- `Torn` (a `StoreError`): the last line of a log has no line break. Run
  `groundgate store check --repair`.
- `ValueError`: a bad kind (`'Text' is not a kind such as text@1`), bad bytes for the kind
  (`a text@1 object is not UTF-8`), a bad log name, or `forget needs a reason`.
- `TypeError`: `the data must be bytes`.

## See also

- [Guide: Store](../guide.md#store)
- [SPEC §9: the store contract](../../SPEC.md#9-the-store-contract)
- [admit_packet()](admit-packet.md) and [load_packet()](load-packet.md)
- [Run groundgate under a job runner](../howto/job-runner.md)
