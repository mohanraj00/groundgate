# groundgate review measures

Release: main, before 1.0.0 (spec 0.13).

`groundgate review measures` reads each answer log of a store and prints the measures of the
review: for each item kind, and for each field in that kind. It writes nothing to the store.

## Command

```text
groundgate review measures --store DIR [--policy FILE] [--set NAME --split NAME] [--json]
```

| Option | Default | Effect |
|---|---|---|
| `--store DIR` | required | The store folder. The folder must exist. |
| `--policy FILE` | none | A `review-policy@1` JSON file for `agree` and `leads`. Without it, `agree` is 1 and there is no lead. |
| `--set NAME` | none | The set of the `splits` log. Give it with `--split`. |
| `--split NAME` | none | Measure only the documents in this split of `--set`, for example `development`. |
| `--json` | off | Print the measures as JSON. |

## Example

The store has the answer of `ana` from the example of [review api](review-api.md).

```bash
uv run groundgate review measures --store store
```

```text
packets: 1
number: answers 1, median time 0 ms, one key 0 of 1, agreement with blind labels 0 of 0, escapes 0 of 0 audit slots
  number phaseout_start: answers 1, median time 0 ms, one key 0 of 1, agreement with blind labels 0 of 0, escapes 0 of 0 audit slots
```

The API answer sent no `ms` and no `keys`, so the time is 0 and no answer has one key. The
packet has no audit task, so the last two measures are 0 of 0.

## Result

The first line counts the packets with an answer log. Then each kind has one line, and each
field of that kind has an indented line:

- `answers`: the latest answer of each reviewer to each task.
- `median time`: the median of `ms`.
- `one key`: the answers given with one key.
- `agreement with blind labels`: the pairs that agree, of all pairs. A blind label is an answer
  to an audit task with `reason_seen` false.
- `escapes`: the audit slots that resolve to another value or to `not_in_document`, of the
  audit slots that an answer settles.

Some kinds add a measure, for example `span moved` for `text` and `span`. With `--json`, the
output has `kinds`, `packets`, `skipped`, `no_split` and `other_split`. Each pair is a list
`[count, total]`.

Exit codes: 0 success, 1 a packet is left out, 2 invalid input.

## Errors

| Exit | Message | Cause |
|---|---|---|
| 1 | `skipped: ...` on stderr | A packet whose receipt does not match, whose answers break their tasks, or whose answer log cannot be read. The measures leave it out. |
| 2 | `groundgate: give the set and the split together` | `--set` or `--split` is alone. |
| 2 | `groundgate: nostore: the store folder is not there` | The `--store` folder does not exist. |
| 2 | `groundgate: the review policy format must be review-policy@1` | The policy file is not valid. |

For example, a torn last line in an answer log gives `skipped: answer log sha256:...
sha256:...: logs/answers/.../....jsonl has a torn last line: it has no line break`. Run
[store check --repair](store-check.md) to cut the line.

## See also

- [Review flagged facts](../howto/review.md#9-answer-the-tasks-on-the-review-page) shows the
  measures in Python.
- [The review note](../design/review.md), section 10, gives the measures and their purpose.
