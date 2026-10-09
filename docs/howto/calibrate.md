# Measure a judge's thresholds

A judge is a model that answers one question about a value. groundgate never runs a judge. It
reads the judge's answers as recorded judgments, and the policy sets the threshold at which an
answer counts. A threshold belongs to one model and one kind of document, so groundgate ships
none. `groundgate-calibrate` measures yours.

This page runs every step once, from your documents to a decision with a recorded judgment. The
judge here is a rule of a few lines, so the page runs with no model and no network. The
documents, the candidates and the labels are made up. The
[calibrate README](../../calibrate/README.md) is the reference for each command and each rule.

## 1. Install the tool

```bash
pip install groundgate-calibrate
```

It installs groundgate too. The tool runs the groundgate that is installed, and records its spec
version.

The tool has two questions:

- `field`, the field doubt: does the text state this admitted value as this field? A judge
  answers with a probability. A probability below the threshold adds `MODEL_DOUBT`, and the
  value goes to review.
- `key`, the key clear: which of the field's keys does a value flagged `KEY_NOT_AT_VALUE` belong
  to? A judge chooses a key with a confidence. The candidate's key at or above the threshold
  clears the flag.

This page measures the field doubt.

## 2. Write a judge

A judge has three members:

- `id`: the name that the commands and the policy use.
- `digest`: the model version. A threshold holds for one version only.
- `ask(state, questions)`: the answers. `state` is the text around the value: up to 400
  characters before it and 150 after it, with the value in brackets. `questions` has one entry.
  The field question is of type `noul`, and the answer is `{"noul": p}`, where `p` is the
  probability that the statement is true. The key question is of type `choice`, and the answer
  is `{"choice": name, "confidence": p}`, where `name` is one of the question's `criteria`.

This judge doubts every value with the word "monthly" in the 50 characters before it:

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg
from groundgate_calibrate import judges
from groundgate_calibrate.cli import main


class PremiumRule:
    id = "premium-rule"
    digest = "premium-rule-1"

    def ask(self, state, questions):
        before = state.split("[")[0][-50:]
        p = 0.03 if "monthly" in before.lower() else 0.92
        return {name: {"noul": p} for name in questions}
```

A package adds a judge with an entry point in the group `groundgate.judges`. The entry point
names a class or a function that the tool calls with no arguments, and that returns the judge:

```toml
[project.entry-points."groundgate.judges"]
premium-rule = "my_package.judges:PremiumRule"
```

When the package is installed, `--judge premium-rule` loads it. This page has no package, so it
adds the judge in the process. Do this only in a test:

```python
judges.BUILT_IN["premium-rule"] = PremiumRule
```

Two judges are built in. `jev` is hosted. `chat` sends the text window to a server that accepts
chat requests. Set `GROUNDGATE_CHAT_URL` to its base URL, `GROUNDGATE_CHAT_MODEL` to the name it
reports, and `GROUNDGATE_CHAT_VERSION` to your version string. `GROUNDGATE_CHAT_KEY` is optional.
Then use `--judge chat` in step 6. With a server on your machine, the text stays there. With a
hosted server, use only documents that you may send. The [Judges reference](../../calibrate/README.md#judges)
gives the settings and digest. Both judges use the same calibration steps as this test judge.

## 3. Write the inputs

The tool takes three inputs, the same that you give `groundgate admit`:

- a folder of documents, one `<doc>.txt` for each document;
- a folder of candidates, one `<doc>.json` for each document, with the list of its candidates;
- a schema.

Each document here is a short policy summary. The extractor gives one candidate for
`annual_premium`. In every sixth document, the extractor takes the monthly premium instead. That
value is in the text, so groundgate admits it. A judge must catch it. Three right documents say
"For monthly billing" before the annual premium, so the rule doubts them too.

```python
work = Path(tempfile.mkdtemp())
docs, cands = work / "docs", work / "candidates"
docs.mkdir()
cands.mkdir()
schema = {
    "fields": {
        "annual_premium": {
            "type": "integer",
            "unit": "USD",
            "description": "The total premium for one year of coverage.",
        }
    }
}
(work / "schema.json").write_text(json.dumps(schema))

truth = {}
for n in range(1, 61):
    doc, annual = f"policy-{n:03d}", 1200 + 12 * n
    monthly = annual // 12
    lead = "For monthly billing, the annual premium" if n in (20, 35, 49) else "The annual premium"
    text = (
        f"Policy summary {n}\n\n"
        f"{lead} is ${annual:,}. "
        f"The deductible is $500. A monthly premium of ${monthly} applies to the payment plan.\n"
    )
    wrong = n % 6 == 0
    value = monthly if wrong else annual
    candidate = {
        "id": "c1",
        "field": "annual_premium",
        "value": str(value),
        "unit": "USD",
        "evidence": [{"text": f"${value:,}"}],
    }
    (docs / f"{doc}.txt").write_text(text)
    (cands / f"{doc}.json").write_text(json.dumps([candidate]))
    truth[doc] = not wrong
print(sum(truth.values()), "right,", len(truth) - sum(truth.values()), "wrong")
```

```text
50 right, 10 wrong
```

Give each candidate an `id`. The `judge` command in step 7 needs it, because a judgment names
its candidate by `id`.

## 4. Sample and split

`sample` runs groundgate on every document and keeps the items for one question. For the field
question, an item is a candidate that groundgate admits with no judgment. `--context` is one
sentence that every prompt starts with.

```python
w = work / "field"
main([
    "sample", "--work", str(w), "--docs", str(docs), "--candidates", str(cands),
    "--schema", str(work / "schema.json"), "--question", "field",
    "--context", "The text is from an insurance policy summary.",
])  # fmt: skip
```

```text
60 items in 60 documents
With no failure, the calibration part needs this many right items for each ceiling:
  0.05: 59
  0.1: 29
  0.2: 14
A split by document puts about half of the items in the calibration part.
```

A ceiling is the most error that you accept. For the field doubt, the error is a right value that
the judge doubts. The tool picks a threshold on the calibration part, so that part needs enough
right items. 60 documents are enough for a ceiling of 0.2 only.

`sample` reads each field's `description` from the schema for the field question and the label
page. Without a description, the field question uses the field name. `--descriptions` is an
optional JSON file that maps field names to meanings. Each entry replaces that field's schema
description. Use it with spec 0.5 schemas, which have no `description`. The tool needs groundgate
0.5 or later. The field prompt digest includes its description, so a new description needs a
new calibration.

`split` puts each document in the calibration part or the test part, by sha256 of its name. Run
it before any judge answers, because the split must not depend on the answers:

```python
main(["split", "--work", str(w)])
```

```text
wrote split.json: 32 calibration, 28 test
```

## 5. Label every item

Label every item before any judge answers. Run the label page:

```bash
groundgate-calibrate label --work W
```

It serves a page at `http://localhost:8780`. Use `--port` to change the port. The page shows the
document, the marked value, the field and the options. It never shows a judge's answer. Each
click saves the label in `W/labels.json`:

- For the field question, the label is `true`, `false`, or `null` for not sure.
- For the key question, the label is the list of the field's keys that the value belongs to.
  An empty list means none.

The report leaves out the items labeled not sure. If extraction lost the shape of a table, put a
`links.json` in `W` that maps each document name to its original, such as a web page. The label
page then links to it.

This page writes the labels from the truth that made the documents. Never do this with real
data. A label must come from a person who reads the text.

```python
labels = {it["id"]: truth[it["doc"]] for it in json.loads((w / "items.json").read_text())}
(w / "labels.json").write_text(json.dumps(labels))
```

## 6. Ask the judge and read the report

`ask` asks the judge every question once, and writes `answers-<judge>.json`. It refuses to run
until every item has a label. After it runs, the labels are frozen.

```python
main(["ask", "--work", str(w), "--judge", "premium-rule"])
```

`ask` saves each answer as it goes. If it stops, run it again with the same judge, and it goes on
where it stopped. `report` then writes `REPORT.md` and `report.json`:

```python
main(["report", "--work", str(w)])
print((w / "REPORT.md").read_text(), end="")
```

```text
wrote REPORT.md, report.json
# Calibration report

Generated by `groundgate-calibrate report`. The threshold for each ceiling comes from the calibration part (hybrid design §9). The test part shows what that threshold does on documents that did not choose it.

## premium-rule (premium-rule-1)

A doubt catches a wrong value, and it sends a right one to review. The ceiling is on the share of right values doubted.

| Ceiling | Threshold | Test: wrong caught | Test: right doubted | Test: wrong | Test: right |
|---:|---:|---:|---:|---:|---:|
| 0.05 | none |  |  | 6 | 22 |
| 0.1 | none |  |  | 6 | 22 |
| 0.2 | 0.5 | 6 | 2 | 6 | 22 |

Policy blocks, one for each ceiling that has a threshold:

- 0.2: `{"judge": {"id": "premium-rule", "digest": "premium-rule-1", "doubt": {"field_match": 0.5}}}`
```

The report gives, for each ceiling, the threshold from the calibration part. Then it gives what
that threshold does on the test part, which did not choose it:

- The calibration part has 28 right values, and the judge doubts 1 of them at any threshold from
  0.05. The 95% upper bound of 1 in 28 is 0.16, which is below the ceiling of 0.2. So the tool
  takes the highest threshold, 0.5.
- On the test part, that threshold catches all 6 wrong values and doubts 2 of the 22 right ones.
  The 2 are the test documents that say "For monthly billing".
- The ceilings 0.05 and 0.1 get no threshold. With no doubt at all, the bound of 0 in 28 is 0.10.
  The calibration part has too few right values to show an error that low.

Each threshold comes with the `judge` block of a policy. `report --check` fails when `REPORT.md`
or `report.json` differs from what the work directory gives. Use it in CI.

## 7. Record judgments, and admit with them

Put the `judge` block in your policy. It names the judge, its model version and the threshold:

```python
policy = {
    "judge": {"id": "premium-rule", "digest": "premium-rule-1", "doubt": {"field_match": 0.5}}
}
(work / "policy.json").write_text(json.dumps(policy))
```

`judge` asks the judge about your production documents, and writes the recorded judgments, one
`<doc>.json` for each document. It asks each question as the calibration asked it: the same
wording, context, descriptions and window. It asks only where the answer can change the
decision. Here, those are the admitted candidates.

```python
prod = work / "prod"
(prod / "docs").mkdir(parents=True)
(prod / "candidates").mkdir()
text = (
    "Policy summary 61\n\n"
    "The annual premium is $1,932. The deductible is $500. "
    "A monthly premium of $161 applies to the payment plan.\n"
)
candidates = [
    {
        "id": "c1",
        "field": "annual_premium",
        "value": "161",
        "unit": "USD",
        "evidence": [{"text": "$161"}],
    }
]
(prod / "docs" / "policy-061.txt").write_text(text)
(prod / "candidates" / "policy-061.json").write_text(json.dumps(candidates))
main([
    "judge", "--docs", str(prod / "docs"), "--candidates", str(prod / "candidates"),
    "--schema", str(work / "schema.json"), "--policy", str(work / "policy.json"),
    "--calibration", str(w), "--out", str(prod / "judgments"),
])  # fmt: skip
```

```text
policy-061: 1 judgments
```

Give the judgments to `admit` with the same policy:

```python
recorded = json.loads((prod / "judgments" / "policy-061.json").read_text())
print(json.dumps(recorded, indent=1))
without = gg.admit(text, schema, candidates)
with_judge = gg.admit(text, schema, candidates, policy, judgments=recorded)
print(without.decisions[0].outcome, without.decisions[0].codes)
print(with_judge.decisions[0].outcome, with_judge.decisions[0].codes)
```

```text
[
 {
  "candidate_id": "c1",
  "judge": {
   "id": "premium-rule",
   "digest": "premium-rule-1"
  },
  "question": "field_match",
  "p": 0.03
 }
]
admitted ()
needs_verification ('MODEL_DOUBT',)
```

Without the judgment, groundgate admits the monthly premium as the annual premium, because the
number is in the text. With it, the value goes to review with `MODEL_DOUBT`. On the command line:

```bash
groundgate admit DOC SCHEMA CANDIDATES --policy policy.json --judgments J/<doc>.json
```

The receipt records the judgments and the policy, so `verify` needs both again.

## Before you use a threshold

- **Measure on your documents.** A threshold from this page, or from another kind of document,
  means nothing for yours.
- **Take enough documents.** `sample` prints how many right items each ceiling needs with no
  failure. About half of the items go to the calibration part.
- **Calibrate again for a new model version.** `judge` refuses a calibration of another version.
- **Calibrate again for a new spec version.** Every step refuses a work directory that was
  sampled under another groundgate spec, because another spec admits and flags other values.

The [calibrate README](../../calibrate/README.md#rules-that-the-tool-keeps) lists every rule
that the tool keeps, and the [guide](../guide.md#recorded-judgments) describes the `judge`
block.
