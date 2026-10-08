# Send reasons back to the extractor

groundgate tells you why it did not admit a fact. Some of these reasons are mistakes in the
citation, such as a quote with one changed character or a scale that the model did not cite. The
model can fix these mistakes if you tell it what is wrong. This page returns the reasons to the
model once, admits the new candidates, and keeps both receipts.

## The pipeline

groundgate is one step in a pipeline that your app owns:

1. The extractor reads the document and proposes candidates.
2. A judge (optional) answers questions about the candidates. Your app records the answers and
   gives them to `admit` as judgments. groundgate never calls the judge.
3. groundgate decides each candidate and writes a receipt.
4. A feedback loop (optional) returns the reasons for each decision that is not admitted to the
   extractor. Your app admits the new candidates and keeps the new receipt.

groundgate never calls a model, so the loop is in your code. Each decision is the feedback: the
outcome, the codes, the parts that the evidence cited and the parts that are missing. You decide
whether to return it to the extractor.

## 1. Admit the first round

The document is a table of plan costs in thousands of dollars. The model makes three mistakes:

- For `claims_paid`, it gives the scaled value but does not cite "(in thousands)".
- For `stop_loss_premiums`, its quote has no space after the `$`, so the quote is not in the text.
- For `admin_costs`, it changes the order of two digits.

The function `your_model` is a stub with fixed output. Your app replaces it with its own model
call, as in [Check your own model's extractions](own-model.md#4-call-the-model). The stub returns
better candidates when it gets feedback.

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg
from groundgate.codes import DESCRIPTIONS, INFO

text = (
    "PLAN COSTS FOR 2026\n"
    "(in thousands)\n"
    "\n"
    "Claims paid\t$ 48,200\n"
    "Stop-loss premiums\t$ 1,240\n"
    "Administrative costs\t$ 3,150\n"
    "\n"
    "Members at year end: 12,400.\n"
)
schema = {
    "fields": {
        "claims_paid": {"type": "integer", "unit": "USD"},
        "stop_loss_premiums": {"type": "integer", "unit": "USD"},
        "admin_costs": {"type": "integer", "unit": "USD"},
        "members": {"type": "integer"},
    }
}
output_format = gg.extractor_schema(schema)
instructions = "Extract the fields from the text. ..."  # the instructions from own-model.md


def item(words, role="value"):
    return {"source": "document", "role": role, "text": words}


def your_model(instructions, text, output_format, feedback=None):
    """A stub with fixed output, in the shape of output_format."""
    if feedback is None:
        return {
            "candidates": [
                {
                    "field": "claims_paid",
                    "value": "48200000",
                    "unit": "USD",
                    "key": None,
                    "evidence": [item("48,200")],
                },
                {
                    "field": "stop_loss_premiums",
                    "value": "1240000",
                    "unit": "USD",
                    "key": None,
                    "evidence": [item("$1,240"), item("(in thousands)", "scale")],
                },
                {
                    "field": "admin_costs",
                    "value": "3510000",
                    "unit": "USD",
                    "key": None,
                    "evidence": [item("$ 3,150"), item("(in thousands)", "scale")],
                },
                {
                    "field": "members",
                    "value": "12400",
                    "unit": None,
                    "key": None,
                    "evidence": [item("12,400")],
                },
            ]
        }
    return {
        "candidates": [
            {
                "field": "claims_paid",
                "value": "48200000",
                "unit": "USD",
                "key": None,
                "evidence": [item("48,200"), item("(in thousands)", "scale")],
            },
            {
                "field": "stop_loss_premiums",
                "value": "1240000",
                "unit": "USD",
                "key": None,
                "evidence": [item("$ 1,240"), item("(in thousands)", "scale")],
            },
        ]
    }


def show(receipt):
    for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
        print(f"{d.candidate_id} {d.outcome:<18} {d.field:<18} {' '.join(d.codes)}".rstrip())


out = your_model(instructions, text, output_format)
first = [{"id": f"c{i}", **c} for i, c in enumerate(out["candidates"], 1)]
receipt1 = gg.admit(text, schema, first)
show(receipt1)
```

```text
c1 needs_verification claims_paid        PART_MISSING
c2 rejected           stop_loss_premiums QUOTE_NOT_FOUND
c3 rejected           admin_costs        VALUE_NOT_IN_EVIDENCE
c4 admitted           members
```

## 2. Build a feedback message

For each decision that is not admitted, build one message from these members:

- `d.codes`: the reason codes. `DESCRIPTIONS` in `groundgate.codes` gives one sentence for each
  code. Omit the codes in `INFO`, because they do not change the outcome.
- `d.missing`: the parts that the value needs and that no item cites, in the order `sign`,
  `scale`, `unit`, `key`.
- `d.parts`: the role items that the evidence cited. Report each part with `passed` false.

Also repeat the candidate's value and quotes, so that the model sees what it sent:

```python
by_id = {c["id"]: c for c in first}


def feedback_message(d, candidate):
    quotes = ", ".join(f'{e.get("role", "value")} "{e["text"]}"' for e in candidate["evidence"])
    lines = [f'Field "{d.field}": you gave the value "{candidate["value"]}" with {quotes}.']
    for code in d.codes:
        if code not in INFO:
            lines.append(f"- {code}: {DESCRIPTIONS[code]}")
    for part in d.missing:
        lines.append(f'- Cite the {part} with a "{part}" item.')
        if part in ("unit", "key"):
            lines.append('- Also cite the words that name the field with a "field" item.')
    for p in d.parts:
        if not p.passed:
            lines.append(f'- The "{p.role}" item does not support the {p.role} at the value.')
    return "\n".join(lines)


for d in sorted(receipt1.decisions, key=lambda d: d.candidate_id):
    if d.outcome != "admitted":
        print(feedback_message(d, by_id[d.candidate_id]))
```

```text
Field "claims_paid": you gave the value "48200000" with value "48,200".
- PART_MISSING: The value needs a sign, a scale or a unit that no evidence item supports.
- Cite the scale with a "scale" item.
Field "stop_loss_premiums": you gave the value "1240000" with value "$1,240", scale "(in thousands)".
- QUOTE_NOT_FOUND: The quoted value text does not occur in the document or reference.
Field "admin_costs": you gave the value "3510000" with value "$ 3,150", scale "(in thousands)".
- VALUE_NOT_IN_EVIDENCE: The value cannot be read from the cited text.
```

## 3. Choose what to retry

Send a feedback message only when a better citation can fix the decision. These codes are worth a retry:

| Code | What the model can fix |
|---|---|
| `PART_MISSING` | Cite the part that `missing` names. A `unit` part also needs a passing `field` item. |
| `QUOTE_NOT_FOUND` | Copy the quote exactly from the text. |
| `NON_VERBATIM_EVIDENCE` | Copy the quote exactly from the text. |
| `KEY_NOT_AT_VALUE`, with `key` in `missing` | In a table, cite the column heading with a `key` item and the row label with a `field` item. |
| `SIGN_CITATION_INVALID`, `SCALE_CITATION_INVALID`, `UNIT_CITATION_INVALID`, `FIELD_CITATION_INVALID`, `KEY_CITATION_INVALID` | Cite the part at the value. If the retry fails again, a person checks the fact. |
| `SCALE_WORD` | Send the scaled value, such as `1250000000` for "$1.25 billion". |
| `NO_EVIDENCE` | Quote the value. |

A unit item and a key item pass only with a passing field item, and a field item passes only on
a field with `aliases` (see [the schema guide](../schema.md)). A key item puts its key at the value
only in a table, by the column rule. So if the field has no `aliases`, or the value is in prose,
a missing unit or key is not worth a retry. A person checks the fact.

These codes are not worth a retry:

- `VALUE_NOT_IN_EVIDENCE` with a wrong value usually means that the model read the wrong number.
  Drop the fact. A second answer from the same model is not better evidence.
- `CONFLICTING_CANDIDATES` needs a person. Two models read different values, and groundgate never
  picks.
- `QUALIFIED_VALUE` can mean that the schema comparator is wrong. If the field is a limit, set its
  `comparator`, such as `le` for "up to". If not, a person checks the fact.
- `KEY_NOT_AT_VALUE` with a key item: the text puts another key at the value. A person checks
  the fact.
- `LOW_CONFIDENCE`, `MODEL_DOUBT`, `EVIDENCE_QUOTED` and `EVIDENCE_STATED` come from your policy or
  your judge, not from the citation.

A decision is worth a retry when each of its codes is on the first list:

```python
RETRY = {
    "PART_MISSING",
    "QUOTE_NOT_FOUND",
    "NON_VERBATIM_EVIDENCE",
    "SCALE_WORD",
    "NO_EVIDENCE",
    "SIGN_CITATION_INVALID",
    "SCALE_CITATION_INVALID",
    "UNIT_CITATION_INVALID",
    "FIELD_CITATION_INVALID",
    "KEY_CITATION_INVALID",
}


def in_table_row(d, references=()):
    """A key item can pass only by the column rule, so only on a line with tabs."""
    if d.source == "document":
        data = text.encode()
    elif d.source == "reference":  # pass the references that you gave admit
        data = next(r["text"] for r in references if r["id"] == d.ref).encode()
    else:
        return False
    start = data.rfind(b"\n", 0, d.evidence[0]) + 1
    end = data.find(b"\n", d.evidence[0])
    return b"\t" in data[start : end if end >= 0 else len(data)]


def worth_a_retry(d):
    if d.outcome == "admitted":
        return False
    if {"unit", "key"} & set(d.missing) and not schema["fields"][d.field].get("aliases"):
        return False  # a unit or key item needs a passing field item, and so the field's aliases
    for code in d.codes:
        if code in INFO or code in RETRY:
            continue
        if code == "KEY_NOT_AT_VALUE" and "key" in d.missing and in_table_row(d):
            continue
        return False
    return True


retry = [d for d in sorted(receipt1.decisions, key=lambda d: d.candidate_id) if worth_a_retry(d)]
print([d.candidate_id for d in retry])
```

```text
['c1', 'c2']
```

## 4. Ask the model again

Send the instructions, the text and the output format again, with the feedback message of each retry.
Then admit the new candidates:

```python
feedback = "\n".join(feedback_message(d, by_id[d.candidate_id]) for d in retry)
out = your_model(instructions, text, output_format, feedback=feedback)
second = [{"id": f"r{i}", **c} for i, c in enumerate(out["candidates"], 1)]
receipt2 = gg.admit(text, schema, second)
show(receipt2)
```

```text
r1 admitted           claims_paid        VALUE_DERIVED
r2 admitted           stop_loss_premiums VALUE_DERIVED
```

Both facts are now admitted. `VALUE_DERIVED` only informs: the value is the cited number times the
scale that the scale item cites.

## 5. Limit the retries and keep both receipts

Ask again once. Each round costs one model call, and a fixed limit stops a model that makes the
same mistake again. After the last round, act on each outcome as usual:

1. If a fact is admitted in any round, store it. The exception: if two rounds admit different
   values for the same field and key, and the field is not `multiple`, store neither value. Send
   both to a person. Each `admit` call sees only its own candidates, so no receipt flags this
   `CONFLICTING_CANDIDATES`.
2. If a retried fact is still flagged, send it to a person.
3. If a fact is rejected, drop it and log the codes.

Keep the receipt and the candidates of each round. Each receipt verifies against its own
candidates:

```python
folder = Path(tempfile.mkdtemp())
rounds = [(receipt1, first), (receipt2, second)]
for n, (receipt, candidates) in enumerate(rounds, 1):
    (folder / f"receipt-{n}.json").write_text(json.dumps(receipt.to_dict(), indent=2))
    (folder / f"candidates-{n}.json").write_text(json.dumps(candidates, indent=2))

for n in (1, 2):
    stored = json.loads((folder / f"receipt-{n}.json").read_text())
    sent = json.loads((folder / f"candidates-{n}.json").read_text())
    print(n, stored["summary"], gg.verify(stored, text, schema, sent).ok)
```

```text
1 {'admitted': 1, 'needs_verification': 1, 'rejected': 2} True
2 {'admitted': 2, 'needs_verification': 0, 'rejected': 0} True
```

The first receipt still shows `c1` flagged and `c2` rejected. That is the record of what the model
sent first. The second receipt holds only the new candidates. If your schema has required fields,
read the coverage of both rounds together.

## Next

- [Check your own model's extractions](own-model.md): the output format, the instructions and the
  first `admit` call.
- [Check values in tables](tables.md): the scale, unit, field and key items in a table.
- [Review flagged facts](review.md): the queue for a person.
- [Decisions](../guide.md#decisions) in the guide, and [SPEC.md](../../SPEC.md) §3 for each check.
