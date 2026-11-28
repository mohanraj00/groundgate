# groundgate store forget

Release: main, before 1.0.0 (spec 0.13).

`groundgate store forget` removes the objects of a packet that hold document data, and records
each deletion with its time and reason in `logs/deleted.jsonl`. Use it when you must delete a
document.

## Command

```text
groundgate store forget --store DIR PACKET --reason TEXT [--all]
```

| Option | Default | Effect |
|---|---|---|
| `PACKET` | required | The packet key. |
| `--store DIR` | required | The store folder. The folder must exist. |
| `--reason TEXT` | required | The reason, for the deleted log. |
| `--all` | off | Also remove each object and answer log of the packet, its tasks, resolutions and correction packets, and the packet. |

Without `--all`, the text, the candidates and the other objects with document data go. The
candidates of each correction that `review resolve` wrote also go, because they hold the value
that a person typed. The packet, the receipt and the other kept objects stay. An object that
two packets share goes for both. The run record goes too if a line holds a string of 8 or more
characters that is in the text. That check is not a proof.

With `--all`, a review policy stays, and a kept object that another packet names stays. Run
[store check](store-check.md) first: a packet that `forget` cannot read names nothing.

## Example

```bash
PACKET=$(uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json)
uv run groundgate store forget --store store "$PACKET" --reason "the owner asked"
uv run groundgate verify --store store "$PACKET"
```

```text
deleted text@1 sha256:f439bc6761cfde81a428153b00746dc09ffac4c9c78da160e958de57690a908b
deleted candidates@1 sha256:866ee6f8ba53257a4c81db3d4fea9b4280a0419d87a7e2b87bd2b7b71dcfe147
groundgate: input deleted: the text@1 object sha256:f439bc6761cfde81a428153b00746dc09ffac4c9c78da160e958de57690a908b was deleted at 2026-11-28T11:51:04Z, reason: the owner asked
```

`verify` cannot decide again without the text, so it exits 2 with `input deleted`. It does not
report a mismatch.

## Result

The command prints one line for each object: the state, the kind and the key. A log line has
the path in place of the kind and the key. The state is `deleted`, `absent` (another `forget`
removed it first), `kept` or `unchecked`. If other packets name the object, the line ends with
`(1 other packet names it)` or `(N other packets name it)`.

Exit codes: 0 success, 1 an object is `unchecked`, 2 invalid input or a store error.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 1 | `unchecked KIND KEY` | `forget` cannot read this object. It removes the rest. Repair the store, then run `forget` again. |
| 2 | `groundgate: notakey is not a store key` | `PACKET` is not `sha256:` and 64 hex digits. |
| 2 | `groundgate: the packet sha256:... is not in the store` | `NotFound`: the store has no packet with this key. |
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. |

With `--all`, if another writer holds an answer log of the packet, the command stops before it
removes the packet. Run `forget` again to finish the work.

If the packet also has a task and an answer log, `--all` also deletes them. It also deletes the
schema, the receipt and the packet. The output then has lines such as
`deleted logs/answers/6526a101.../303789f3....jsonl` and `deleted packet@1 sha256:6526a101...`.

## See also

- [The store note](../design/store.md), section 8, rule 3, gives the full procedure of `forget`.
- [Review flagged facts](../howto/review.md#8-keep-the-inputs-in-a-store) shows `forget` and
  `input deleted` in Python.
- [Guide: Store](../guide.md#store) gives the store contract.
