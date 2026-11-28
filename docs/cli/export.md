# groundgate export

Release: main, before 1.0.0 (spec 0.13).

`groundgate export` writes the facts of one stored packet as JSON, for an app that does not read
the store. It decides the packet again first, and it writes nothing if the receipt does not match.

## Command

```text
groundgate export --store DIR PACKET [--pack-dir DIR] [-o FILE]
groundgate export --store DIR PACKET --resolution KEY [-o FILE]
```

| Option | Default | Effect |
|---|---|---|
| `--store DIR` | required | The store folder. |
| `PACKET` | required | The packet key from `admit --store`. |
| `--resolution KEY` | none | The `resolution@1` key from `review resolve`. The export is then `facts@2`. |
| `--pack-dir DIR` | none | A folder of pack files. Not with `--resolution`. |
| `-o`, `--output FILE` | stdout | Write the facts to this file. |

## Example

```bash
packet=$(uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json)
uv run groundgate export --store store "$packet"
```

```text
{
  "format": "facts@1",
  "packet_sha256": "sha256:6526a101d0f7fc146bc39a1944f5e6e158db7fa3a23680b397862b527aff165b",
  "facts": [
    {
      "field": "ira_limit",
      "key": null,
      "value": "7000",
      "unit": "USD",
      "citation": {
        "source": "document",
        ...
        "span": {
          "end": 36,
          "start": 30
        },
        ...
      }
    }
  ]
}
```

The two `...` lines leave out the `ref`, `url`, `source_sha256`, `text_sha256` and
`receipt_sha256` members of the citation.

## Result

Without `--resolution`, the export is `facts@1`: each admitted fact with its citation. With
`--resolution`, the export is `facts@2`. Its `facts` list has a `status` for each fact
(`admitted`, `confirmed`, `chosen` or `corrected`) and a `selector` in each citation. Its `open`
list has each slot with no value. In the example, after `review tasks` and `review resolve` with
no answer, `open` holds `phaseout_start` with the status `open`.

| Exit code | Meaning |
|---|---|
| 0 | The command writes the facts. |
| 1 | The receipt does not match its inputs, or the resolution does not match the answer logs. Each problem is a `mismatch: ...` line on stderr. |
| 2 | Invalid input, or an input that is not in the store. |

## Errors

Each error prints `groundgate: <message>` on stderr and exits 2.

| Message | Cause |
|---|---|
| `DIR: the store folder is not there` | The `--store` folder is not there. |
| `nosuchkey is not a store key` | `PACKET` is not a `sha256:` key. |
| `input missing: the packet@1 object sha256:... is not in the store` | No packet has this key (`InputGone`). |
| `input deleted: the text@1 object sha256:... was deleted at ..., reason: ...` | `store forget` removed an input (`InputGone`). |
| `object sha256:... is not in the store` | The `--resolution` key is not in the store (`NotFound`). |
| `--pack-dir does not apply with --resolution` | Both options are given. |

## See also

- [Review flagged facts and keep receipts](../howto/review.md), sections 8 and 9.
- [Guide: Export](../guide.md#export) gives `facts@1` and `facts@2`, and SPEC §5.1 and §5.2 give
  the formats.
