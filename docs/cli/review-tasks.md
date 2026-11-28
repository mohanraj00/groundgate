# groundgate review tasks

Release: main, before 1.0.0 (spec 0.13).

`groundgate review tasks` decides a stored packet again and writes a review task for each slot
that needs a person. A person then answers the tasks with `review serve` or `review api`.

## Command

```text
groundgate review tasks --store DIR PACKET [--policy FILE] [--model-text FILE]
```

| Option | Default | Effect |
|---|---|---|
| `PACKET` | required | The packet key that `admit --store` printed. |
| `--store DIR` | required | The store folder. The folder must exist. |
| `--policy FILE` | none | A `review-policy@1` JSON file. Without it, there is no audit task and no task for a rejected slot. |
| `--model-text FILE` | none | A `model-text@1` JSON file of the app. The command puts it in the store and writes its task. |

A slot gets a task in each of these cases:

- it has a `needs_verification` decision;
- a required field is missing;
- the audit of the policy picks it;
- the policy has `"rejected": true`, and each decision of the slot is rejected.

## Example

```bash
PACKET=$(uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json)
uv run groundgate review tasks --store store "$PACKET"
```

```text
sha256:682a44647d87a0659788d19b59ef6e2a5ffa9d3a09ca97d1c717b7c0d7d1ed3c
```

The `phaseout_start` decision is `needs_verification` with the code `QUALIFIED_VALUE` ("above
$79,000"), so it gets one task.

## Result

The command writes one `task@1` object for each selected slot. It prints each task key on its
own line, in slot order. The same packet always gives the same task bytes, so a second run
prints the same keys and writes nothing new.

Exit codes: 0 success, 1 the receipt does not match its inputs, 2 invalid input.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 1 | `mismatch: ...`, then `groundgate: no task for a receipt that does not match` | The stored receipt does not match its inputs. The command writes no task. |
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. |
| 2 | `groundgate: notakey is not a store key` | `PACKET` is not `sha256:` and 64 hex digits. |
| 2 | `groundgate: input missing: the packet@1 object sha256:... is not in the store` | The store has no object with this key. |
| 2 | `groundgate: input deleted: the text@1 object sha256:... was deleted at ..., reason: ...` | `store forget` removed an input of the packet. |
| 2 | `groundgate: the review policy format must be review-policy@1` | The policy file is not a valid `review-policy@1` object. Other policy messages name the bad member. |

Each message on stderr starts with `groundgate:`. A `ValueError`, a `PacketError` or a
`StoreError` gives exit 2.

## See also

- [Review flagged facts](../howto/review.md#9-answer-the-tasks-on-the-review-page) shows the
  tasks, the page and the resolution in Python.
- [The review note](../design/review.md) gives the policy (section 5.1) and the task format
  (section 5.2).
- [groundgate review serve](review-serve.md) and [groundgate review api](review-api.md) take
  the answers.
