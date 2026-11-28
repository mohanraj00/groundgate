# gg.load_pack()

Release: main, before 1.0.0 (spec 0.13).

`load_pack` reads one vocabulary pack or kind pack from a file, and runs the loader checks of
SPEC §4.8 on it. Give the result to `admit`, `verify` and `feedback_message` in `packs`.

## Call

```text
gg.load_pack(path) -> dict
```

- `path`: a `str` or a `pathlib.Path` to a JSON file of at most 1 MiB.

## Example

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg

pack = {
    "groundgate_pack": 1,
    "type": "vocabulary",
    "id": "lac-x-myapp",
    "version": "1.0.0",
    "scale": {"words": {"lac": 5}},
}
path = Path(tempfile.mkdtemp()) / "lac.json"
path.write_text(json.dumps(pack), encoding="utf-8")
lac = gg.load_pack(path)
schema = {
    "packs": [{"id": "lac-x-myapp", "version": "1.0.0"}],
    "fields": {"grant": {"type": "integer"}},
}
candidates = [{"field": "grant", "value": "500000", "evidence": [{"text": "5 lac"}]}]
receipt = gg.admit("The grant is 5 lac rupees.", schema, candidates, packs=[lac])
print(receipt.decisions[0].outcome, receipt.decisions[0].packs)
```

```text
admitted ('lac-x-myapp',)
```

## Result

The pack as a dict, after the checks. Do not load a built-in pack such as `finance` or
`us-10k`: name it in the schema, and do not give it.

## Errors

`load_pack` raises `gg.PacketError`. Each message but the L1 message names the file:

- `pack file '<path>' is not a file`
- `pack file '<path>' cannot be read: <cause>`
- `pack file '<path>' is more than 1048576 bytes (L4)`: groundgate refuses the file before it
  parses it.
- `pack file '<path>' is not JSON: <cause>`
- `pack: an object has one key twice (L1)`: a JSON object in the file has one key two times.
- `pack file '<path>': pack '<id>': <check>`: the pack fails a loader check of SPEC §4.8.

## See also

- [Python API](../guide.md#python-api) in the guide, for packs and kind packs.
- [Keep pack files with receipts](../howto/keep-packs.md).
