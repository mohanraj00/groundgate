# Check your own model's extractions

Your model reads a document and proposes facts. groundgate stands between the model and your
store. It gives each fact one of three outcomes and writes a receipt that records each decision.
This page builds that step for a short benefits notice with four fields. The model reads two
fields right, one field has a qualifier in the text, and one value is wrong.

groundgate never calls your model. Your app calls the model, and groundgate reads what the model
returned.

## 1. Write the schema

The schema names the fields that you want, with their types and units.
[Write a schema](../schema.md) explains each key. This is the document and its schema:

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg

text = (
    "SUMMARY OF BENEFITS, PLAN YEAR 2027\n"
    "\n"
    "Deductible: $1,500 for each person, $3,000 for each family.\n"
    "Out-of-pocket limit: up to $6,000 for each person.\n"
    "After the deductible, the plan pays 80% of covered costs.\n"
    "Office visit copay: $25. Specialist visit copay: $60.\n"
)
schema = {
    "fields": {
        "deductible": {"type": "integer", "unit": "USD", "required": True},
        "out_of_pocket_max": {"type": "integer", "unit": "USD"},
        "coinsurance": {"type": "integer", "unit": "%"},
        "office_copay": {"type": "integer", "unit": "USD"},
    }
}
```

The document must be a Python `str` in Unicode NFC. If your text is not in NFC, normalise it
before the model reads it (see [Documents](../guide.md#documents)).

## 2. Build the output format

`gg.extractor_schema(schema)` returns a JSON Schema for the model's structured output. Give it to
the model as its output schema. Each field gets its own candidate shape, so the model cannot send
a field, a unit or a key that your schema does not have:

```python
output_format = gg.extractor_schema(schema)

shape = output_format["properties"]["candidates"]["items"]["anyOf"][0]
for name in ("field", "unit", "key"):
    print(name, json.dumps(shape["properties"][name]))
```

```text
field {"const": "deductible"}
unit {"const": "USD"}
key {"type": "null"}
```

The schema uses only the subset of JSON Schema that the strict structured-output modes accept.
Every member is required, and no object takes other members. An evidence item has no offsets: a
model cannot count UTF-8 bytes, so it quotes the text, and groundgate finds the quote.

To see the whole output format, write your schema to `schema.json` and print it:

```bash
groundgate schema schema.json
```

## 3. Write the instructions

The output format gives the shape. The instructions tell the model what to put in it. This is a
shorter form of the text in [The extractor's output](../guide.md#the-extractors-output). Keep its
rules:

```python
instructions = """\
Extract the fields from the text. Give "value" as the fact is, as a plain number without $,
commas or a unit, with its sign and scale: a number in brackets, or a loss, is negative, and a
table "in thousands" multiplies its numbers by 1000.

Give the evidence as quotes, each copied verbatim from the text:
- role "value": the number as written, such as "(12,040)";
- role "sign": the brackets or the loss word that make the value negative, when the value quote
  does not hold them;
- role "scale": the words that scale the number, such as "(in thousands)";
- role "unit": the unit or $ sign when it is not next to the number;
- role "field": the words that name the field, such as a table row label;
- role "key": the words that name the key, such as a table column heading.
Leave out each role that the value does not need.

If no text states a value, but you know it, give a "knowledge" item that states the value and
its basis, or an "external" item with the URL of a page that states it, the date that you read
the page, and a quote from it.
"""
```

## 4. Call the model

The function below is a stub with fixed output. Your app replaces it with its own model call,
with `instructions`, `text` and `output_format` as the inputs:

```python
def your_model(instructions, text, output_format):
    """A stub with fixed output, in the shape of output_format."""

    def quote(words):
        return [{"source": "document", "role": "value", "text": words}]

    return {
        "candidates": [
            {
                "field": "deductible",
                "value": "1500",
                "unit": "USD",
                "key": None,
                "evidence": quote("$1,500"),
            },
            {
                "field": "out_of_pocket_max",
                "value": "6000",
                "unit": "USD",
                "key": None,
                "evidence": quote("$6,000"),
            },
            {
                "field": "coinsurance",
                "value": "20",
                "unit": "%",
                "key": None,
                "evidence": quote("80%"),
            },
            {
                "field": "office_copay",
                "value": "25",
                "unit": "USD",
                "key": None,
                "evidence": quote("$25"),
            },
        ]
    }


out = your_model(instructions, text, output_format)
candidates = [{"id": f"c{i}", **c} for i, c in enumerate(out["candidates"], 1)]
```

The output format has no `id`, so give each candidate one. The receipt sorts its decisions by
candidate hash, not by input order. Each decision echoes the `id` as `candidate_id`, so you can
find the candidate of each decision.

## 5. Admit the candidates

Give the document, the schema and the candidates to `gg.admit`:

```python
receipt = gg.admit(text, schema, candidates)
print(receipt.to_dict()["summary"])
print(receipt.coverage)
```

```text
{'admitted': 2, 'needs_verification': 1, 'rejected': 1}
()
```

`coverage` is empty, because the required field `deductible` has an admitted candidate. If no
candidate of a required field is admitted or flagged, `coverage` lists the field with
`REQUIRED_FIELD_MISSING`.

## 6. Act on each outcome

Each decision has an `outcome`, its `codes` and the byte span of the value in `evidence`. A
decision on outside evidence has no span. Its `source`, `ref` and `url` name the source, and the
candidate holds the quote or the statement. Do one thing for each outcome:

1. If the outcome is `admitted`, store the fact.
2. If the outcome is `needs_verification`, put the fact in a queue for a person. Give the person
   the codes and the evidence.
3. If the outcome is `rejected`, do not store the fact. Log the codes.

```python
store, queue, log = {}, [], []
by_id = {c["id"]: c for c in candidates}


def cited(decision):
    if decision.evidence is None:  # outside evidence has no span in the text
        return f"{decision.source}: {decision.ref or decision.url or 'the extractor'}"
    start, end = decision.evidence
    return text.encode()[start:end].decode()


for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
    codes = " ".join(d.codes)
    if d.outcome == "admitted":
        store[d.field] = (d.value, d.unit)
        print(f"{d.candidate_id} store   {d.field} = {d.value} {d.unit}")
    elif d.outcome == "needs_verification":
        queue.append({"candidate": by_id[d.candidate_id], "codes": d.codes, "cited": cited(d)})
        print(f"{d.candidate_id} review  {d.field} = {d.value} {d.unit} at {cited(d)!r}: {codes}")
    else:
        log.append({"candidate": by_id[d.candidate_id], "codes": d.codes})
        print(f"{d.candidate_id} drop    {d.field} = {d.value} {d.unit}: {codes}")
```

```text
c1 store   deductible = 1500 USD
c2 review  out_of_pocket_max = 6000 USD at '$6,000': QUALIFIED_VALUE
c3 drop    coinsurance = 20 %: VALUE_NOT_IN_EVIDENCE
c4 store   office_copay = 25 USD
```

The text says "up to $6,000", and the field has the default comparator `eq`. So groundgate flags
`c2` with `QUALIFIED_VALUE`, and a person checks it. This field is a limit, so a better fix is
`"comparator": "le"` in the schema. Then the same candidate is admitted.

The model gave 20 for `coinsurance`, the share that the member pays. The cited text holds 80, so
groundgate rejects `c3` with `VALUE_NOT_IN_EVIDENCE`. The fact does not go into the store.

[When a fact is rejected or flagged](../guide.md#when-a-fact-is-rejected-or-flagged) gives the
usual cause of each code and what to do. [Review flagged facts](review.md) shows the queue for a
person.

## 7. Store the receipt and verify it

`receipt.to_dict()` is the JSON receipt, with its own hash. Store it with the inputs that made
it: the document, the schema, the candidates and the policy, if you gave one. This example writes
to a temporary folder:

```python
folder = Path(tempfile.mkdtemp())
(folder / "receipt.json").write_text(json.dumps(receipt.to_dict(), indent=2))
(folder / "candidates.json").write_text(json.dumps(candidates, indent=2))
```

Later, read the files again and verify the receipt. `gg.verify` decides every candidate again and
compares the result with the stored receipt:

```python
stored = json.loads((folder / "receipt.json").read_text())
sent = json.loads((folder / "candidates.json").read_text())
check = gg.verify(stored, text, schema, sent)
print(check.ok, check.problems)
```

```text
True ()
```

If a person or a program changes the receipt, the check fails. Here the rejected fact `c3` is
marked as admitted:

```python
for decision in stored["decisions"]:
    if decision["candidate_id"] == "c3":
        decision["outcome"] = "admitted"
check = gg.verify(stored, text, schema, sent)
print(check.ok, len(check.problems))
```

```text
False 2
```

The two problems are the decision of `c3` and the hash of the receipt.

A receipt names its spec version, and `verify` accepts only the version that it implements. Pin
the groundgate version where you keep receipts. On the command line, `groundgate verify` does the
same check and exits with 1 when the receipt does not match.

## Several models in one call (optional)

You can send the candidates of two or more models through one `admit` call. If two candidates for
a single-valued field pass the checks with different values, groundgate flags both with
`CONFLICTING_CANDIDATES`. It never picks between them. A person picks.

A second model reads the family deductible. Each value is in the text, so each candidate passes
the checks alone:

```python
second = [
    {
        "id": "b1",
        "proposer": "model-b",
        "field": "deductible",
        "value": "3000",
        "unit": "USD",
        "key": None,
        "evidence": [{"source": "document", "role": "value", "text": "$3,000"}],
    },
]
receipt = gg.admit(text, schema, candidates + second)
for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
    if d.field == "deductible":
        print(d.candidate_id, d.outcome, d.value, " ".join(d.codes))
```

```text
b1 needs_verification 3000 CONFLICTING_CANDIDATES
c1 needs_verification 1500 CONFLICTING_CANDIDATES
```

Other members of a candidate, such as `proposer`, are kept and ignored by the checks. The
candidate hash covers them. A second model helps only when the two models disagree: if both read
the same wrong value, both candidates get the same decision.

## Next

- [Send reasons back to the extractor](feedback.md): ask the model again when a fact is flagged
  or rejected for a reason that a better citation can fix.
- [Check values in tables](tables.md): cite the scale, the unit, the row and the column.
- [Use evidence from outside the document](outside-sources.md): references, web pages and the
  model's own knowledge.
- [SPEC.md](../../SPEC.md) is the normative definition of every check.
