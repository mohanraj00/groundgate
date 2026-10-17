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
import tempfile
from pathlib import Path

import groundgate as gg
from groundgate.run import RunPolicy, RunResult, replay, run

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
print(sum(entry["kind"] == "call" for entry in result.record))
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
states do not prove that a field is absent. The record's lines give the failure or stop
reason; the last line, `record[-1]["fields"]`, lists the field's search and repair history. These states
record attempts, not an active candidate inventory. An admission-history limit entry lists
retained, dropped and reverted ids. Read `result.candidates` with its receipt for active values.
If a run stops before a field has a valid disposition, its history contains
`incomplete_no_disposition`. This does not say whether a client was attempted or prove absence;
read the call and protocol-failure entries for that detail. Field histories do not include
phase names. Call and limit events carry `phase`; use those events to identify the stopped work.
The phase-specific stops are:

| Phase | Stop and field state |
|---|---|
| Initial | An oversized initial chunk plan or prompt raises `RunInputError` before the first call. An aborted reply with no valid field disposition leads to `incomplete_no_disposition`. |
| Targeted | Exhausted `max_calls` records `unsearched` for each skipped field and a `call_limit` event. If the regions do not fit the prompt budget, the worst-ranked region goes first and the search records `search_truncated`. If no region fits, the field and event record `search_limit`. A targeted quote outside the sent regions records `protocol_failure` for that field only; the run continues. |
| Repair | An oversized prompt records `prompt_limit`; exhausted `max_calls` records `call_limit`. A completed run with an eligible candidate left after its repair rounds records `repair_limit`. |

`proposed` and `model_not_found` can appear in the initial or targeted phase. A targeted
not-found reply records both `model_not_found` and `targeted_not_found`: the first records the
model response, and the second records completion of that phase. `admission_history_limit`
can stop admission in any phase, with the last accepted packet retained.

The initial response must account for every requested field in `candidates` or `not_found`,
never both. For example, an empty response for the requested field is:

```json
{"candidates": [], "not_found": ["amount"]}
```

For a field with no first-pass candidate, the runner searches the supplied texts using the
field name, aliases and description. One targeted call gets only the selected regions and
asks for that field. Title and alias matches take priority over individual description words.
The search uses at most the first 64 distinct queries in that priority order and records
`omitted_queries`. It retains at most 1024 match records; omitted counts and truncation stay in
the record. Each retained query still scans every supplied source to count all its hits,
including omitted matches. The caller must bound the number of requested fields, the number
and size of references, and document length before calling the runner. Search may scan up to
`missing fields * 64 * total source characters`, plus query matching and schema-processing
work. `max_calls` limits client calls, not this CPU work. Casefolds are cached once per source
across fields; expansion maps and byte offsets use compact arrays.
A rejected candidate does not trigger that pass. Search terms, retained regions, truncation
and not-found replies stay in the record. No match is the result of that search, not proof
of absence. Set `RunPolicy(targeted=False)` for a run without this pass.

## 3. Keep repairs bounded

The default is two extra calls per original value and 128 calls in total. There are at most
1024 active proposals and 8 MiB of stored admission packet/receipt pairs. Active candidate
payloads may use at most half that byte budget. These limits stop the run incomplete while
retaining its last recorded packet and receipt. Proposals from an admission that could not be
recorded are not active in the returned candidate list. This applies to new values and evidence
repairs alike; the final field states name the admission-history limit. Raw prompts and replies
are separate from the admission-history byte budget. The reply-size setting limits parsing
only; it does not limit the size of retained raw reply artifacts. Duplicate proposals
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

The record is a log: a list of lines, one dict for each line. The first line names every
input by digest: the text, the schema, the policy and each reference. The last line holds the
field states and the final receipt digest. Each line holds the digest of the line before it.
The artifacts are objects keyed by digest: the inputs, the complete prompts and replies, and
each admission packet. They include source text. They also include an oversized reply that
exceeded `max_reply_bytes`: the runner keeps that raw body for replay but does not parse it.
The setting is a parsing limit, not a transport or artifact-size limit. The client owns any
transport cap before it returns.

`result.write(folder)` writes each object to `folder/objects/` first and the log to
`folder/run.jsonl` last, one line of canonical JSON for each entry. `RunResult.read(folder)`
reads only the objects that the log names, gets the inputs from them and replays the run. A
changed line, or a changed, missing or oversized object, raises `ValueError`. It reads at most
`max_bytes` (1 GiB by default) and refuses a symlink or a special file in the folder.

```python
folder = Path(tempfile.mkdtemp()) / "run"
result.write(folder)
print(RunResult.read(folder).run_sha256 == result.run_sha256)
print(replay(result.record, result.artifacts, text, schema).ok)
print(gg.verify(result.receipt.to_dict(), text, schema, result.candidates).ok)
```

```text
True
True
True
```

Replay uses the saved replies and makes no model calls. It reconstructs the prompts, search,
limits, repairs and every admission, then compares the complete chained record. A changed
input, artifact, setting, entry or final receipt fails verification. A model id in the record
is the app's claim, not an authenticated model identity.

For an app-owned loop, `gg.feedback_message` still builds reason text from one decision. It
does not enforce repair diffs. Use the runner when groundgate should own those limits.
