# groundgate-calibrate

Measure a judge's thresholds for groundgate on your own documents.

A judge is a typed-decision model that answers a question about a flagged or admitted value. A
threshold belongs to one model and one kind of document: the field doubt gave 0.3 on FDA labels
(#106) and 0.2 on NTSB reports (#110). So groundgate ships no thresholds. This tool measures
yours, as hybrid design §9 describes. It is a separate package, so the groundgate core never
contains code that calls a model.

## Steps

```bash
groundgate-calibrate sample --work W --docs D --candidates C --schema S --question key \
    --context "The text is from a 10-K filing."
groundgate-calibrate split  --work W        # before any model run
groundgate-calibrate label  --work W        # label in the browser, blind, before ask
TYPESAFE_API_KEY=... groundgate-calibrate ask --work W --judge jev
groundgate-calibrate report --work W        # REPORT.md, report.json
```

- `D` holds one `<doc>.txt` for each document.
- `C` holds one `<doc>.json` for each document: a list of your extractor's candidates in the
  spec 0.3 candidate format.
- `S` is a spec 0.3 schema.
- `--descriptions` is an optional JSON file that maps each field name to a one-line meaning.
  The field question and the label tool show it.

`W` keeps everything that a later step needs: the config, a copy of each document with items,
the items, the labels, the split, the answers and the report. A step never asks for an earlier
input again.

## Questions

- **`key`: the key clear.** The items are the candidates that spec 0.3 flags
  `KEY_NOT_AT_VALUE`. A judge chooses one of the field's keys, or none. A judge clears a flag
  when it chooses the candidate's key with a confidence of t or more. The clear is right when
  the label holds that key, and an escape when it does not. The ceiling is on the escape rate
  among clears, and the tool takes the lowest threshold that keeps the bound below it.
- **`field`: the field doubt.** The items are the candidates that spec 0.3 admits. A judge
  gives the probability that the text states the value as the field. A judge doubts a value
  when that probability is below t. A doubt catches a wrong value, and it sends a right one to
  review. The ceiling is on the share of right values doubted, and the tool takes the highest
  threshold that keeps the bound below it.

The bound is the one-sided 95% upper bound (Clopper-Pearson) on the calibration part. The
report gives the test part at each threshold, and a table of the answers by confidence.

## Before you label

`sample` prints how many right items each ceiling needs with no failure: 59 at 0.05, 29 at 0.1
and 14 at 0.2. The split puts about half of the items in the calibration part. Take enough
documents for the ceiling that you need before you start.

## Rules that the tool keeps

- **Blind labels.** The label tool shows the document, the marked value, the field and the
  options. It never shows the candidate's key, spec 0.3's reading or a judge's answer.
- **Split first.** `split` is written once, by document, on sha256 of the document name. It
  refuses to run after a judge has answered, and `ask` refuses to run without it.
- **Labels first.** `ask` refuses to run until every item has a label (not sure counts), and it
  records a digest of the labels. The label tool refuses changes once a judge has answered, and
  `report` refuses answers whose labels changed.
- **Fixed prompts.** `split` also records a digest of every prompt. `ask` refuses to run when the
  documents, items or config changed after the split, and `report` refuses answers to other
  prompts. `ask` goes on after a stop only with the same judge, model and prompts.
- **Your offsets stay right.** `sample` refuses a document that is not NFC, and never changes
  the text, because your candidates' byte offsets point into it.
- **Text leaves the machine.** A hosted judge sends a window of each document out: 400 code
  points before the value and 150 after. Use it only on documents that you may send.

## The result

`report` writes, for each ceiling with a threshold, the `judge` block of a policy (hybrid
design §7) with the model and the threshold. The groundgate core does not read it yet: a judge's
answer can only enter a decision as a recorded input in a later spec version (#66).
