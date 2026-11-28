# groundgate.store.packets.load_packet()

Release: main, before 1.0.0 (spec 0.13).

`load_packet` gets a packet and each input that it names back from a store. Then `verify` and
`render` can decide again from the packet key alone.

## Call

```text
load_packet(store, k, *, layout=False) -> Packet
```

- `store`: the store that holds the packet.
- `k`: the packet key that [admit_packet()](admit-packet.md) or `RunResult.save` gave.
- `layout`: `True` also gets the layout of the reading of a PDF.

The store data is untrusted. `load_packet` calculates each key again, parses each object as
canonical JSON, and checks the members of the packet before it gets an object.

## Example

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg
from groundgate.store import FolderStore, StoreError, key
from groundgate.store.packets import admit_packet, load_packet

quick = Path("docs/quickstart")
text = (quick / "doc.txt").read_text(encoding="utf-8")
schema = json.loads((quick / "schema.json").read_text())
candidates = json.loads((quick / "candidates.json").read_text())
with tempfile.TemporaryDirectory() as root, FolderStore(root) as store:
    packet, _ = admit_packet(store, text, schema, candidates, document_id="irs-590a")
    found = load_packet(store, packet)
    check = gg.verify(found.receipt, found.text, found.schema, found.candidates, **found.inputs())
    print(check.ok, found.receipt["document"]["id"], found.run)
    store.forget(key("text@1", text.encode("utf-8")), "the owner asked")
    try:
        load_packet(store, packet)
    except StoreError as gone:
        print(type(gone).__name__, str(gone).split(" sha256:")[0])
```

```text
True irs-590a None
InputGone input deleted: the text@1 object
```

## Result

A `Packet` with the members `key`, `receipt` (a dict), `text`, `schema`, `candidates`,
`policy`, `judgments`, `references`, `document_source`, `packs`, `reading`, `layout`, `run`,
`doubt`, `pin`, `places`, `completeness` and `outline`. `run` is the key of the run record of
`RunResult.save`, or `None`. `packet.inputs()` gives the keyword arguments of `verify` and
`render` after the first four.

## Errors

- `ValueError`: `x is not a store key`.
- `InputGone` (a `StoreError`): an object that the packet names is not in the store. The message
  is `input deleted: ...` with the time and the reason of the deletion, or `input missing: ...`
  when the deleted log has no record of the key. This is not a mismatch.
- `StoreError`: an object that does not match its key or its format, for example
  `the packet and its receipt name different document ids`.

## See also

- [Review flagged facts and keep receipts, section 8](../howto/review.md#8-keep-the-inputs-in-a-store)
- [Guide: Store](../guide.md#store)
- [FolderStore](folder-store.md)
