# groundgate review resolve

Release: main, before 1.0.0 (spec 0.13).

`groundgate review resolve` reads the answers to the tasks of one packet and gives the final
value of each slot. It runs `admit` again for each correction, so a value that a person types
goes through the same gate.

## Command

```text
groundgate review resolve --store DIR PACKET [--reviewer NAME]... [--policy FILE]
```

| Option | Default | Effect |
|---|---|---|
| `PACKET` | required | The packet key that `admit --store` printed. |
| `--store DIR` | required | The store folder. The folder must exist. |
| `--reviewer NAME` | none | Read the answer log of this reviewer. Repeat it for each reviewer. The name must be NFC text. |
| `--policy FILE` | none | A `review-policy@1` JSON file. Without it, `agree` is 1, with no lead and no audit. |

## Example

```bash
PACKET=$(uv run groundgate admit --store store docs/quickstart/doc.txt docs/quickstart/schema.json docs/quickstart/candidates.json)
uv run groundgate review tasks --store store "$PACKET" > /dev/null
uv run groundgate review resolve --store store "$PACKET" --reviewer ana
```

```text
sha256:edcdbfd93af11b6eb362cd0981322285c5cce89d1883b690f7af998c102f5f45
ira_limit: 7000 USD (admitted)
phaseout_start: no value (open: no answer settles the task yet)
```

`ana` has no answer yet, so the task stays open. After `ana` confirms the task (see the example
of [review api](review-api.md)), the same command prints:

```text
sha256:771eea5be24641a094eba3e8278b8c37d5cfe8bda1fcf78c4c32088e40f23c1f
ira_limit: 7000 USD (admitted)
phaseout_start: 79000 USD (confirmed)
```

## Result

The command writes each correction packet and one `resolution@1` object to the store. It prints
the resolution key, then one line for each slot: the final value and its status, or the reason
that there is no value. The status is `admitted`, `confirmed`, `chosen`, `corrected`,
`not_in_document`, `rejected`, `open` or `disputed`. Give the resolution key to
`groundgate export --resolution` for `facts@2`.

Exit codes: 0 success, 1 the receipt does not match its inputs, 2 invalid input.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 1 | `mismatch: ...`, then `groundgate: no resolution for a receipt that does not match` | The stored receipt does not match its inputs. |
| 2 | `groundgate: answer N of the reviewer NAME: ...` | `AnswerError`: an answer breaks its task. |
| 2 | `groundgate: --reviewer must be NFC text; normalize the name to NFC and try again` | The reviewer name is not NFC. |
| 2 | `groundgate: input deleted: the text@1 object sha256:... was deleted at ..., reason: ...` | `store forget` removed an input of the packet. |
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. |
| 2 | `groundgate: the review policy format must be review-policy@1` | The policy file is not valid. |

A packet key that is not in the store gives `input missing`, as in
[review tasks](review-tasks.md#errors).

## See also

- [Review flagged facts](../howto/review.md#9-answer-the-tasks-on-the-review-page) shows
  `write_resolution` in Python.
- [The review note](../design/review.md), section 6, gives the resolution rules.
- [Guide: Export](../guide.md#export) gives `facts@2`.
