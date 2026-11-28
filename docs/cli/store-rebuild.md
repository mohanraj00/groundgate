# groundgate store rebuild

Release: main, before 1.0.0 (spec 0.13).

`groundgate store rebuild` builds the views of a store folder again from its objects and logs.
A view is a JSON file under `views/`. The objects and the logs stay the same.

## Command

```text
groundgate store rebuild --store DIR
```

| Option | Default | Effect |
|---|---|---|
| `--store DIR` | required | The store folder. The folder must exist. |

## Example

```bash
uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json > /dev/null
uv run groundgate store rebuild --store store
```

```text
wrote views/readings.json
wrote views/calibrate-labels.json
wrote views/review-queue.json
wrote views/latest-resolutions.json
wrote views/review-measures.json
```

## Result

The command writes the five views and prints one `wrote` line for each:

| View | Holds |
|---|---|
| `readings.json` | The reading cache: each source, reader and options, with its readings. `read --store` uses it. |
| `calibrate-labels.json` | The label of the last answer of each reviewer to each calibrate task. |
| `review-queue.json` | The open review tasks for all reviewers, for each review policy, with the reviewers that answered each task. |
| `latest-resolutions.json` | The current resolution of each packet, and the packets with an answer log and no current resolution. |
| `review-measures.json` | The review measures for each review policy, for all packets and for each split. |

The command takes no policy. Each review view gives one result for each `review-policy@1`
object of the store, and one for the default policy of `review tasks`. A view is a cache: if
you delete it, `store rebuild` writes it again.

Exit codes: 0 success, 2 invalid input or a store error.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. The command does not make a folder. |

A `StoreError` or an `OSError` gives exit 2 with the message after `groundgate:`.

## See also

- [The store note](../design/store.md), section 7.4, gives each view and its format.
- [Guide: Store](../guide.md#store) gives the store contract.
