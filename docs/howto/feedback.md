# Run extraction and evidence repairs

`groundgate.run` owns the extraction loop. Your app gives it text, a schema and one function
that takes a prompt and returns a raw JSON reply. The runner makes bounded calls, admits the
candidates and repairs only the evidence that each code permits. `admit` stays deterministic
and never calls a model.

## 1. Supply a client

This client is a fixed example. Replace its body with your model call. The client owns the
transport, credentials and timeout. It returns a JSON string, with no Markdown fences. Give
`model_id` the version that your client uses.

```python
import json

import groundgate as gg
from groundgate.run import RunPolicy, replay, run

text = "Amounts (in thousands)\nAmount 5."
schema = {"fields": {"amount": {"type": "integer"}}}


def value_item(words, role="value"):
    return {"source": "document", "role": role, "text": words}


def client(prompt):
    request = json.loads(prompt.split("\n", 1)[1])
    candidate = {
        "field": "amount",
        "value": "5000",
        "unit": None,
        "key": None,
        "evidence": [value_item("5")],
    }
    if request["phase"] == "repair":
        candidate["evidence"].append(value_item("in thousands", "scale"))
        return json.dumps(candidate)
    return json.dumps({"candidates": [candidate], "not_found": []})


result = run(
    text,
    schema,
    client=client,
    model_id="fixed-example-1",
    run_policy=RunPolicy(max_repair_rounds=2),
)
print(result.complete)
for decision in result.receipt.decisions:
    print(decision.field, decision.value, decision.outcome)
print(sum(entry["kind"] == "call" for entry in result.record["entries"]))
```

```text
True
amount 5000 admitted
2
```

For targeted reference evidence, `result.candidates` contains an offsets-only value item. The
raw quote remains in the saved reply artifact; the adapter removes it from the admission
packet to prevent re-anchoring outside the selected reference region.

The first proposal lacks scale evidence. The repair keeps `5000` and cites the scale. The
final receipt covers the repaired candidate. The earlier receipt and reply stay in the run
record and its artifacts.

## 2. Read the final outcome and completeness

Use `result.receipt` and `result.candidates` together. The runner admits all final proposals
in one call, so different values for one non-`multiple` field and key meet the conflict check.
An admission in an earlier round is not a final admission.

`result.complete` says whether the planned calls completed. A client failure, malformed reply
or exhausted total call budget returns an incomplete result with completed receipts. A
rejected candidate, a failed repair or a repair-round limit retains its core outcome. These
states do not prove that a field is absent. The record's entries give the failure or stop
reason; `record["final"]["fields"]` lists the field's search and repair states.

The initial response must account for every requested field in `candidates` or `not_found`,
never both. For example, an empty response for the requested field is:

```json
{"candidates": [], "not_found": ["amount"]}
```

For a field with no first-pass candidate, the runner searches the supplied texts using the
field name, aliases and description. One targeted call gets only the selected regions and
asks for that field. Title and alias matches take priority over individual description words.
The search retains at most 1024 match records; omitted counts and truncation stay in the record.
A rejected candidate does not trigger that pass. Search terms, retained
regions, truncation and not-found replies stay in the record. No match is the result of that
search, not proof of absence. Set `RunPolicy(targeted=False)` for a run without this pass.

## 3. Keep repairs bounded

The default is two extra calls per original value and 128 calls in total. There are at most
1024 active proposals and 8 MiB of stored admission packet/receipt pairs. Active candidate
payloads may use at most half that byte budget. These limits stop the run incomplete while
retaining its last recorded packet and receipt. Proposals from an admission that could not be
recorded are not active in the returned candidate list. This applies to new values and evidence
repairs alike; the final field states name the admission-history limit. Raw prompts and replies
have separate limits. Duplicate proposals
share a repair budget. The runner fixes citation codes only. It keeps field, unit, key and
source fixed. It refuses changes to unrelated evidence roles. A no-op or repair not-found
reply ends that proposal's loop and keeps its last candidate.

If a repair changes the value, the runner keeps the original and admits the new proposal
once. The new proposal gets no repair. If both pass with different values, the final receipt
flags the conflict. A `SCALE_WORD` response may supply a scaled value this way; it does not
create a new repair budget. A terminal code such as `VALUE_NOT_IN_EVIDENCE` gets no repair.
The [design note](../design/runner.md) gives the complete per-code rules and defaults.

Caller input errors fail before a model call. A runtime core or internal error raises
`RunnerError`; its `record` holds the completed part of the run. Model-client exceptions
become recorded incomplete results without copying their exception messages.

## 4. Save and replay

Save the run record, artifacts, exact text, schema, policy and references together. Artifacts
contain complete prompts and replies, including source text. The runner returns them in memory
and does not choose file paths. The app chooses storage.

```python
stored_record = json.loads(json.dumps(result.record))
stored_artifacts = json.loads(json.dumps(result.artifacts))
print(replay(stored_record, stored_artifacts, text, schema).ok)
print(gg.verify(result.receipt.to_dict(), text, schema, result.candidates).ok)
```

```text
True
True
```

Replay uses the saved replies and makes no model calls. It reconstructs the prompts, search,
limits, repairs and every admission, then compares the complete chained record. A changed
input, artifact, setting, entry or final receipt fails verification. A model id in the record
is the app's claim, not an authenticated model identity.

For an app-owned loop, `gg.feedback_message` still builds reason text from one decision. It
does not enforce repair diffs. Use the runner when groundgate should own those limits.
