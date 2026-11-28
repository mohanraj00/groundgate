# groundgate store pin

Release: main, before 1.0.0 (spec 0.13).

`groundgate store pin` writes the bytes of a source file to the store as a `source@1` object and
prints its source pin. The pin records the digest of the bytes, the retrieval day and the
origin. Give the pin to `admit` with `--pin`.

## Command

```text
groundgate store pin --store DIR FILE --origin {fetched,supplied} --retrieved YYYY-MM-DD
                     [--url URL] [--edition TEXT] [--label TEXT]
```

| Option | Default | Effect |
|---|---|---|
| `FILE` | required | The source file. |
| `--store DIR` | required | The store folder. The command makes it if it is not there. |
| `--origin` | required | `fetched` or `supplied`. |
| `--retrieved YYYY-MM-DD` | required | The retrieval day. |
| `--url URL` | none | The URL of the source. A `fetched` pin needs it. |
| `--edition TEXT` | none | An edition marker, for example `"2024 revision 2"`. |
| `--label TEXT` | none | For a `supplied` copy only, for example `"unofficial copy"`. |

## Example

```bash
uv run groundgate store pin --store store docs/quickstart/doc.txt --origin supplied --retrieved 2026-11-28 --label "unofficial copy" > pin.json
uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json --pin pin.json
cat pin.json
```

```text
sha256:1de5bb238e2853b597bdd4b87529c697af41b55c8d4e1eac6ee30211f9046567
{
  "groundgate_pin": 1,
  "source_sha256": "sha256:1cedf391ae9855c9a2f9cbcfe1508a9c6f682a1d1df34b144f849377cd58871f",
  "url": null,
  "retrieved": "2026-11-28",
  "edition": null,
  "origin": "supplied",
  "label": "unofficial copy"
}
```

The first line is the packet key from `admit`. The packet names a `pin@1` object.

## Result

The command prints the pin as JSON (SPEC §4.14), with each member. A member that you do not give
is `null`. The command checks the pin before it writes, so a bad pin writes nothing.
`store check` later compares the bytes of the reading source of each pinned packet with
`source_sha256`.

Exit codes: 0 success, 2 invalid input.

## Errors

Each pin error is a `PacketError` with the text `pin:` and the rule (S1 to S5):

| Exit | Message | Cause |
|---|---|---|
| 2 | `groundgate: pin: a fetched pin must give the url (S5)` | `--origin fetched` with no `--url`. |
| 2 | `groundgate: pin: only a supplied pin has a label (S5)` | `--label` with `--origin fetched`. |
| 2 | `groundgate: pin: retrieved must be a real day as YYYY-MM-DD (S3)` | `--retrieved` is not a real day. |
| 2 | `groundgate: [Errno 2] No such file or directory: 'FILE'` | `FILE` is not there (an `OSError`). |

A usage error, such as a missing `--origin`, also exits 2.

## See also

- [The store note](../design/store.md), section 5.2, gives the `pin@1` member of a packet.
- [SPEC §4.14](../../SPEC.md) defines the source pin.
- [groundgate store check](store-check.md) compares a pin with its source.
