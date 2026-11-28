# groundgate.store.packets.admit_packet()

Release: main, before 1.0.0 (spec 0.13).

`admit_packet` runs `admit` and writes each input and the receipt to a store. It returns the key
of a `packet@1` object that names them, so that `verify` can decide again from that key alone.

## Call

```text
admit_packet(store, text, schema, candidates, policy=None, document_id=None, judgments=None, *,
             references=None, document_source=None, packs=(), reading=None, doubt=None,
             pin=None, places=None, completeness=None, outline=None) -> tuple[str, Receipt]
```

- `store`: a store, such as a [FolderStore](folder-store.md).
- `text`, `candidates`, `document_id`, `judgments`, `references`, `document_source`, `doubt`,
  `pin`, `places`, `completeness`, `outline`: the arguments of `admit`.
- `schema`, `policy`: dicts, not `Schema` or `Policy` objects.
- `packs`: the packs of your app. The store keeps each one as a `pack@1` object.
- `reading`: the key of a reading of the same text, from `groundgate read --store`.
  `admit_packet` does not take the completeness from the reading. Give it as `completeness`.

## Example

```python
import json
import tempfile
from pathlib import Path

from groundgate.store import FolderStore
from groundgate.store.packets import admit_packet

quick = Path("docs/quickstart")
text = (quick / "doc.txt").read_text(encoding="utf-8")
schema = json.loads((quick / "schema.json").read_text())
candidates = json.loads((quick / "candidates.json").read_text())
with tempfile.TemporaryDirectory() as root, FolderStore(root) as store:
    packet, receipt = admit_packet(store, text, schema, candidates, document_id="irs-590a")
    again, _ = admit_packet(store, text, schema, candidates, document_id="irs-590a")
print(packet[:23], packet == again)
for d in sorted(receipt.decisions, key=lambda d: d.value):
    print(f"{d.field} {d.value} {d.outcome} {' '.join(d.codes)}".rstrip())
```

```text
sha256:825cb7586a850503 True
ira_limit 7000 admitted
ira_limit 70000 rejected VALUE_NOT_IN_EVIDENCE
phaseout_start 79000 needs_verification QUALIFIED_VALUE
```

## Result

A tuple of the packet key and the `Receipt`. The same inputs give the same packet key. A packet
with no doubt, pin, places, completeness or outline has no member for it, so its key stays the
key of an older packet.

## Errors

- `PacketError`: `give the schema as a dict to store it`, and the same for the policy.
- `PacketError`: the store keeps canonical JSON, where `5.0` is `5`. If that change gives
  another receipt, `admit_packet` writes nothing and raises `the store keeps canonical JSON,
  and in canonical JSON the inputs give another receipt. ...`.
- `PacketError`: `x is not a store key` and `the reading ... is of another text`, for `reading`.
- `PacketError`: an input that `admit` refuses.
- `StoreError` and `ValueError`: the faults of the store, for example an object above
  `max_bytes`.

## See also

- [Review flagged facts and keep receipts, section 8](../howto/review.md#8-keep-the-inputs-in-a-store)
- [Keep pack files with receipts, section 6](../howto/keep-packs.md#6-or-keep-the-packs-in-a-store)
- [Guide: Store](../guide.md#store)
- [load_packet()](load-packet.md)
