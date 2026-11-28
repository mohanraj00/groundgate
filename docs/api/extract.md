# groundgate.extract.extract()

Release: main, before 1.0.0 (spec 0.13).

`extract` runs the extraction loop around your model client. It makes a bounded number of calls
and admits the candidates. It repairs only the evidence that each code permits. It records each
prompt and reply, so a replay needs no model. `admit` stays deterministic and never calls a model.

## Call

```text
extract(text, schema, *, client, model_id, policy=None, run_policy=None,
        document_id=None, document_source=None, references=None, packs=()) -> RunResult
```

- `text`: the NFC text, or a `Document` from [read_document()](read-document.md). With a
  `Document`, the chunks hold whole nodes and a reply can cite a node.
- `schema`, `policy`, `document_id`, `document_source`, `references`, `packs`: as for `admit`.
- `client`: a function that takes the prompt string and returns the raw JSON reply string. It
  owns the transport, the credentials and the timeout.
- `model_id`: a string that is not blank. The record keeps it as the claim of your app.
- `run_policy`: a `RunPolicy`. `None` gives the defaults below.

`RunPolicy` fields and defaults: `chunk_chars=12000`, `overlap_chars=1000`,
`max_repair_rounds=2`, `targeted=True`, `search_context_chars=1000`, `max_target_regions=8`,
`max_calls=128`, `max_prompt_chars=65536`, `max_reply_bytes=1048576`,
`max_candidates_per_reply=256`, `max_total_candidates=1024`, `max_admission_bytes=8388608`,
`drop_rounded=False`, `max_region_chars=6000`, `max_sweep_calls=2`.

## Example

The client is a stand-in for a model call. It gives one fixed reply.

```python
import json

from groundgate.extract import RunPolicy, extract

text = "The IRA contribution limit is $7,000. The deduction phases out above $79,000.\n"
schema = {
    "fields": {
        "ira_limit": {"type": "integer", "unit": "USD"},
        "phaseout_start": {"type": "integer", "unit": "USD"},
    }
}


def client(prompt):
    def fact(field, value, quote):
        evidence = [{"source": "document", "role": "value", "text": quote}]
        return {"field": field, "value": value, "unit": "USD", "key": None, "evidence": evidence}

    found = [fact("ira_limit", "7000", "$7,000"), fact("phaseout_start", "79000", "$79,000")]
    return json.dumps({"candidates": found, "not_found": []})


result = extract(text, schema, client=client, model_id="fixed-example-1", run_policy=RunPolicy())
print(result.complete, len(result.candidates))
for d in result.receipt.decisions:
    print(f"{d.field} {d.value} {d.outcome} {' '.join(d.codes)}".rstrip())
print([line["kind"] for line in result.record])
```

```text
True 2
phaseout_start 79000 needs_verification QUALIFIED_VALUE
ira_limit 7000 admitted
['header', 'plan', 'call', 'admission', 'final_admission', 'final']
```

`QUALIFIED_VALUE` ends the repairs of a candidate, so the runner makes one call only.

## Result

A `RunResult`:

- `receipt`: the final `Receipt`. Read it with `candidates`.
- `candidates`: the final candidates that the receipt decides.
- `record`: the run log, one dict for each line. Each line holds the digest of the line before.
- `artifacts`: the objects that the log names by digest: inputs, prompts, replies, packets.
- `complete`: `False` when a client error, a bad reply or a call limit stopped the run.
  `record[-1]["fields"]` gives the history of each field.
- `run_sha256`: the digest of the last log line.
- `write(folder)` and `RunResult.read(folder, max_bytes=2**30, packs=())`: a run in a folder.
- `save(store, packs=())` and `RunResult.load(store, packet)`: a run in a store.

## Errors

- `ExtractInputError` (a `ValueError`), before the first call: `client must be callable and
  model_id non-blank`, `schema must request at least one field`, `run_policy must be RunPolicy`,
  `inputs must be encodable as UTF-8`, and an initial plan or prompt above the limits.
  `RunPolicy(...)` raises it too, for example `overlap_chars must be less than chunk_chars`.
- `PacketError`: an input that `admit` refuses, for example `field 'a' has unknown type 'nope'`.
- `ExtractError` (a `RuntimeError`): `runner failed; inspect the partial record`. Its `record`
  holds the lines written so far.
- An exception in `client` raises nothing. The result is incomplete, and the record keeps only
  the name of the exception type.

## See also

- [Run extraction and evidence repairs](../howto/feedback.md)
- [Run groundgate under a job runner](../howto/job-runner.md)
- [replay()](replay.md)
