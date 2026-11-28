# groundgate.extract.replay()

Release: main, before 1.0.0 (spec 0.13).

`replay` rebuilds a saved run of [extract()](extract.md) from its recorded replies, and compares
every line of the record. It makes no model call.

## Call

```text
replay(record, artifacts, text, schema, policy=None, references=None, packs=()) -> Verification
```

- `record`: the run log, `RunResult.record`.
- `artifacts`: the objects of the run, `RunResult.artifacts`.
- `text`: the text of the run. For a run on a `Document`, give the same `Document`.
- `schema`, `policy`, `references`: the inputs of the run.
- `packs`: the packs that the run read. The record holds their digests, not the packs.

The run policy, the model id, the document id and the document source come from the record.

## Example

```python
import json

from groundgate.extract import extract, replay

text = "The IRA contribution limit is $7,000.\n"
schema = {"fields": {"ira_limit": {"type": "integer", "unit": "USD"}}}


def client(prompt):
    evidence = [{"source": "document", "role": "value", "text": "$7,000"}]
    fact = {"field": "ira_limit", "value": "7000", "unit": "USD", "key": None, "evidence": evidence}
    return json.dumps({"candidates": [fact], "not_found": []})


result = extract(text, schema, client=client, model_id="fixed-example-1")
print(replay(result.record, result.artifacts, text, schema))
print(replay(result.record, result.artifacts, text.replace("7,000", "8,000"), schema))
```

```text
Verification(ok=True, problems=())
Verification(ok=False, problems=('run differs from replay',))
```

## Result

A `Verification` with `ok` and `problems`. `ok` is `True` when the replay gives the same
prompts, the same record and the same artifacts. Otherwise `problems` holds one of these:

- `run differs from replay`: an input, a setting, a line or the final receipt changed.
- `artifacts differ from replay`: the objects are not the objects of the replay, for example
  an extra object.
- `runner version differs: the record is '...', this runner is 'groundgate-run/6'`.
- `runner or core version differs`: the record has another spec version.
- `invalid replay record or inputs`: the record or an input is not valid.

## Errors

`replay` raises no error for a bad record or a bad input. It returns `ok=False` with the
problem. To read a run from a folder or a store, use `RunResult.read(folder)` or
`RunResult.load(store, packet)`. These raise `ValueError` when the replay differs.

## See also

- [Run extraction and evidence repairs, section 4](../howto/feedback.md#4-save-and-replay)
- [Run groundgate under a job runner](../howto/job-runner.md)
