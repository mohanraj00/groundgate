# groundgate-calibrate

Measure a judge's thresholds for groundgate on your own documents.

A judge is a typed-decision model that answers a question about a flagged or admitted value. A
threshold belongs to one model and one kind of document: the field doubt gave 0.3 on FDA labels
([#106](https://github.com/mohanraj00/groundgate/issues/106)) and 0.2 on NTSB reports
([#110](https://github.com/mohanraj00/groundgate/issues/110)). So groundgate ships no thresholds. This tool measures
yours, as [hybrid design](https://github.com/mohanraj00/groundgate/blob/main/docs/design/hybrid-decisions.md) §9 describes. It is a separate package, so the groundgate core never
contains code that calls a model.

```bash
pip install groundgate-calibrate
```

[Measure a judge's thresholds](https://github.com/mohanraj00/groundgate/blob/main/docs/howto/calibrate.md) runs every step once, on made-up documents with a test
judge. This page is the reference.

## Steps

```bash
groundgate-calibrate sample --work W --docs D --candidates C --schema S --question key \
    --context "The text is from a 10-K filing."
groundgate-calibrate split  --work W        # before any model run
groundgate-calibrate label  --work W        # label in the browser, blind, before ask
groundgate-calibrate ask    --work W --judge NAME   # NAME: a judge (see Judges)
groundgate-calibrate report --work W        # REPORT.md, report.json
```

- `D` holds one `<doc>.txt` for each document.
- `C` holds one `<doc>.json` for each document: a list of your extractor's candidates in the
  candidate format of the installed groundgate's spec (0.6 with groundgate 0.6.0).
- `S` is a schema of that spec.
- `--descriptions` is an optional JSON file that maps each field name to a one-line meaning.
  The field question and the label tool show it.

- `label` serves the label page at `http://localhost:8780`. `--port` changes the port. Each
  click saves a label in `W/labels.json`: `true`, `false` or `null` (not sure) for the field
  question, and the list of the field's keys (empty for none) for the key question.
- `report --check` writes nothing. It fails when `REPORT.md` or `report.json` differs from what
  `W` gives, so a CI job can check a committed report.

If extraction lost the shape of your tables, put a `links.json` in `W` that maps each document
name to its original, such as the source web page. The label tool then links to it.

`W` keeps everything that a later step needs: the config, a copy of each document with items,
the items, the labels, the split, the answers and the report. A step never asks for an earlier
input again.

## Questions

- **`key`: the key clear.** The items are the candidates that groundgate flags
  `KEY_NOT_AT_VALUE` with no judgment. A judge chooses one of the field's keys, or none. A judge clears a flag
  when it chooses the candidate's key with a confidence of t or more. The clear is right when
  the label holds that key, and an escape when it does not. The ceiling is on the escape rate
  among clears, and the tool takes the lowest threshold that keeps the bound below it.
- **`field`: the field doubt.** The items are the candidates that groundgate admits with no judgment. A judge
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
  options. It never shows the candidate's key, groundgate's reading or a judge's answer.
- **Split first.** `split` is written once, by document, on sha256 of the document name. It
  refuses to run after a judge has answered, and `ask` refuses to run without it.
- **Labels first.** `ask` refuses to run until every item has a label (not sure counts), and it
  records a digest of the labels. The label tool refuses changes once a judge has answered, and
  `report` refuses answers whose labels changed.
- **Fixed prompts.** `split` also records a digest of every prompt. `ask` refuses to run when the
  documents, items or config changed after the split, and `report` refuses answers to other
  prompts. `ask` goes on after a stop only with the same judge, model and prompts.
- **Fixed scoring.** `ask` also records a digest of the items and the split, and `report`
  refuses answers when either changed.
- **One spec.** `sample` records the groundgate spec version. Every later step refuses to run
  under another version, because another spec can admit and flag other candidates.
- **Your offsets stay right.** `sample` refuses a document that is not NFC, and never changes
  the text, because your candidates' byte offsets point into it.
- **Text leaves the machine.** A hosted judge sends a window of each document out: 400 code
  points before the value and 150 after. Use it only on documents that you may send.

## Judges

One judge is built in. `groundgate-calibrate ask --help` names it. It is a hosted model: it reads
its API key from the environment, and it sends a window of each document out of the machine.

A judge has an `id`, a `digest` that names one model version, and `ask(state, questions)`.
`state` is the text around the value, with the value in brackets. `ask` answers each question in
the typed-decision format:

- The key question is a choice question. The answer is `{"choice": name, "confidence": p}`, where
  `name` is one of the question's `criteria`.
- The field question is a noul question. The answer is `{"noul": p}`, where `p` is the
  probability that the statement is true.

A package adds a judge with an entry point:

```toml
[project.entry-points."groundgate.judges"]
mine = "my_package:make_judge"   # called with no arguments, it returns the judge
```

Then `--judge mine` uses it. A plug-in cannot take the name of another judge, and the judge's
`id` must equal its name.

## In production: recorded judgments

Since spec 0.4, groundgate reads a judge's answers only as recorded inputs. `judge` writes them for your documents:

```bash
groundgate-calibrate judge --docs D --candidates C --schema S --policy policy.json \
    --calibration W-key W-field --out J
```

- The policy's `judge` block names the judge, the model version and the thresholds, as `report`
  wrote it. The judge must be that version, and each calibration must be of that version.
- Each question that the policy has a threshold for needs its calibration, and is asked as that
  calibration asked it: the same wording, context, descriptions and window.
- A question is asked only where its answer can change the decision: the key question of each
  candidate flagged `KEY_NOT_AT_VALUE`, and the field question of each admitted candidate. With
  both thresholds, the field question also goes to each candidate whose only flag is
  `KEY_NOT_AT_VALUE`, because the key judgment can admit it.
- Give one calibration for each question.
- A judged candidate needs a unique `id`, because a judgment names its candidate by `id`.
- `J/<doc>.json` holds the judgments. Pass them to groundgate:
  `groundgate admit DOC SCHEMA CANDIDATES --policy policy.json --judgments J/<doc>.json`.

## The result

`report` writes, for each ceiling with a threshold, the `judge` block of a policy (hybrid
design §7) with the model and the threshold. Spec 0.4 and later read it, with the judgments that `judge`
writes ([#116](https://github.com/mohanraj00/groundgate/issues/116)). A block for the field
question looks like this:

```json
{"judge": {"id": "mine", "digest": "mine-2026-10", "doubt": {"field_match": 0.3}}}
```

A block for the key question has `"clear": {"KEY_NOT_AT_VALUE": t}` in place of `doubt`. To use
both thresholds, put both in one block.
