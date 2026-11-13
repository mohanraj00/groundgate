# groundgate calibrate

Measure a judge's thresholds for groundgate on your own documents. This command is experimental.

A judge is a typed-decision model that answers a question about a flagged or admitted value. A
threshold belongs to one model and one kind of document: the field doubt gave 0.3 on FDA labels
([#106](https://github.com/mohanraj00/groundgate/issues/106)) and 0.2 on NTSB reports
([#110](https://github.com/mohanraj00/groundgate/issues/110)). So groundgate ships no thresholds. This tool measures
yours, as [hybrid design](design/hybrid-decisions.md) §9 describes. It is part of groundgate
from 0.11. Before 0.11 it was the separate package `groundgate-calibrate`.

The command is outside the decision. groundgate reads a judge's answers only as recorded
judgments. Only `ask` and `judge` send questions to a judge, and only to the judge that you name.

[Measure a judge's thresholds](howto/calibrate.md) runs every step once, on made-up documents
with a test judge. This page is the reference.

## Steps

```bash
groundgate calibrate sample --work W --docs D --candidates C --schema S --question key \
    --context "The text is from a 10-K filing." [--store DIR]
groundgate calibrate split  --work W [--store DIR --set NAME]  # before any model run
groundgate calibrate label  --work W [--store DIR --reviewer NAME]  # blind, before ask
groundgate calibrate ask    --work W --judge NAME [--store DIR --reviewer NAME]
groundgate calibrate report --work W [--store DIR]  # REPORT.md, report.json
```

- `D` holds one `<doc>.txt` for each document.
- `C` holds one `<doc>.json` for each document: a list of your extractor's candidates in the
  candidate format of the installed groundgate's spec.
- `S` is a schema of that spec. `sample` reads each field's `description` for the field
  question and the label page. Without a description, the field question uses the field name.
- `--descriptions` is an optional JSON file that maps field names to meanings. Each entry
  replaces that field's schema description. Use it with spec 0.5 schemas, which have no
  `description`.

- `label` serves the label page on `127.0.0.1`, port 8780. `--port` changes the port. It prints
  a start URL such as `http://127.0.0.1:8780/#<token>`. Open that full URL: the page sends the
  token with each request, and the server refuses a request without it. Each click saves a label
  in `W/labels.json`: `true`, `false` or `null` (not sure) for the field question, and the list
  of the field's keys (empty for none) for the key question.
- **Labels in a store.** With `--store DIR`, `sample` also writes a packet for each document and
  a blind task for each item to the store, and `W/tasks.json` maps each item to its task
  ([review.md §11](design/review.md#11-fit-with-other-work)). Then `label --store DIR --reviewer
  NAME` opens the review page of `groundgate review serve` on these tasks, and each label is an
  `answer@2` in the answer log of the reviewer. Press `y` (yes), `w` (wrong) or `u` (not sure)
  for the field question. For the key question, click each key that the value gives, or press
  its number, then press `Enter`. You can also go to a key with `Tab` and press `Space`. Press
  `u` if you are not sure. Each question shows the description of the field. `ask --store DIR
  --reviewer NAME` reads the labels from the answer logs and keeps the head of each log. `report
  --store DIR` reads the logs only up to those heads, so a later answer does not change the
  report. After a judge run starts, `label --store` refuses to open and refuses each answer, as
  the label page does. Each label write, on the label page or through `label --store`, holds the
  lock `W/.labels.lock` across the freeze check and the write. `ask` holds the same lock while
  it writes its partial file and reads the labels, so no label write falls between the two. The
  lock is `flock` on POSIX and `msvcrt.locking` on Windows. Both wait for the lock, and the
  system releases it when the process ends, so a stopped process does not leave it held. One
  work folder never mixes label sources: `ask` refuses when an earlier judge run has its labels
  from another source, or from other log heads. Without `--store`, `W/labels.json` holds the
  labels, as in 0.10.
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

- **Labels only from the page.** The label server refuses a request whose `Host` is not
  `127.0.0.1` and its port, so DNS rebinding cannot reach it. Each start makes a new random
  token, and a request without it gets 403, so another web site cannot post a label. A label
  must be `application/json` of 64 KiB at most. A Content-Security-Policy lets the page run only
  its own script and style.
- **Blind labels.** The label tool shows the document, the marked value, the field and the
  options. It never shows the candidate's key, groundgate's reading or a judge's answer.
- **Split first.** `split` is written once, by document, on sha256 of the document name. It
  refuses to run after a judge has answered, and `ask` refuses to run without it.
- **The splits log.** With `--store DIR --set NAME`, `split` also writes the split of each
  document to the `splits` log of the set in the store
  ([store.md §10](design/store.md#10-fit-with-other-work)). The calibration part is
  `development`, because it chooses the thresholds, and the test part is `held-out`. The
  document is the store key of its text. The log comes before any label, so `split` refuses
  to write it when `labels.json` has a label, or when the store has an answer to an item of
  `W/tasks.json`. If the log already puts a document in another
  split, `split` stops and writes nothing. `split` writes the log before `split.json`, so if
  it stops between the two, run it again: the log keeps one record for each document. A work
  folder with no store works as before.
- **Labels first.** `ask` refuses to run until every item has a label (not sure counts), and it
  records a digest of the labels. The label tool refuses changes once a judge has answered, and
  `report` refuses answers whose labels changed.
- **Fixed prompts.** `split` also records a digest of every prompt. `ask` refuses to run when the
  documents, items or config changed after the split, and `report` refuses answers to other
  prompts. `ask` goes on after a stop only with the same judge, model and prompts.
  The field prompt digest includes its description. A new description needs a new calibration.
- **Fixed scoring.** `ask` also records a digest of the items and the split, and `report`
  refuses answers when either changed.
- **One spec.** `sample` records the groundgate spec version. Every later step refuses to run
  under another version, because another spec can admit and flag other candidates.
- **Your offsets stay right.** `sample` refuses a document that is not NFC, and never changes
  the text, because your candidates' byte offsets point into it.
- **Text leaves the machine.** A hosted judge sends a window of each document out: 400 code
  points before the value and 150 after. Use it only on documents that you may send.

## Judges

Two judges are built in. `groundgate calibrate ask --help` names them. `jev` is a hosted judge.
It reads its API key from the environment and sends a window of each document out of the machine.

`chat` uses a server that accepts chat requests. Set these environment variables:

- `GROUNDGATE_CHAT_URL`: the base URL, such as `http://127.0.0.1:11434/v1`. It must be `https`,
  or `http` to this machine (`localhost`, `127.0.0.1` or `::1`). A request to this machine never
  goes through a proxy.
- `GROUNDGATE_CHAT_MODEL`: the model name, exactly as the server reports it in each response.
- `GROUNDGATE_CHAT_VERSION`: your version string, such as the local model's file digest.
- `GROUNDGATE_CHAT_KEY`: optional. When set, it goes in the `Authorization: Bearer` header.

Run `groundgate calibrate ask --work W --judge chat`. It sends the text window to
`<url>/chat/completions`. With a server on your machine, the text stays there. With a hosted
server, use only documents that you may send. The model states its probability in JSON:
`confidence` for a choice question and `p` for a noul question. The calibration measures that
number. The judge uses no log-probabilities.

The digest is `chat-1:<model>@<version>`. `chat-1` names the prompt template and answer parsing.
A change to either needs a new digest and calibration. `ask` and `judge` refuse a response that
reports another model name. An invalid JSON answer, choice or probability gets up to 2 retries.
After that, the judge stops and shows the reply. The request is the same each time, so a retry
helps only when the server does not give the same answer to the same request. The judge refuses
a redirect, so the key goes only to the URL that you set. If the server does not answer, the
judge stops and names the URL.

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
groundgate calibrate judge --docs D --candidates C --schema S --policy policy.json \
    --calibration W-key W-field --out J
```

- The policy's `judge` block names the judge, the model version and the thresholds, as `report`
  wrote it. The judge must be that version, and each calibration must be of that version.
- Each question that the policy has a threshold for needs its calibration, and is asked as that
  calibration asked it: the same wording, context, descriptions and window.
  `judge` refuses a schema that gives a field another description than the field calibration had.
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

## measure: a profile on your gold set

`groundgate calibrate measure` gives the field measure of one profile
([SPEC §4.10](../SPEC.md)) on a gold set that you keep
([#640](https://github.com/mohanraj00/groundgate/issues/640)). It reads only the three inputs
that you name, and it calls no model. A recorded run gives the candidates and the judgments as
files.

```bash
groundgate calibrate measure --profile P --gold G --split S --out DIR \
    [--target 0.05] [--date YYYY-MM-DD]
```

### The gold set, format 1

`G` is a directory:

- `G/docs/<doc>.txt`: the document text, in Unicode NFC.
- `G/candidates/<doc>.json`: the list of the candidates that your extractor recorded.
- `G/judgments/<doc>.json`: optional. The list of the recorded judgments of the document.
- `G/labels.json`: the labels.

```json
{"groundgate_gold": 1,
 "labels": {"inv-001": {"total": "90", "due_date": "2026-12-01", "discount": null,
                        "rate": {"standard": "10", "express": null}}}}
```

A label is the right value of a field in one document, in the canonical form of the receipt
`value`, as a string. For a `number` or `integer` field, two numbers are equal when they have
the same value, so `40` and `40.0` are equal. For each other field type, the texts must be
equal. Null says that the document has no value for the field. For a field with `keys`, the
label is an object from a key of the schema to a value or null. A value is right only under its
own key, so the value of `express` under the key `standard` is an error. A field or a key that a
document does not list is not scored. The report counts each admitted value under a key with no
label as `unscored_admitted`. Each label must come from a person who did not see the decisions.

A document name starts with a letter or a digit, and then has only letters, digits, `.`, `_`
and `-`, at most 128 characters. `labels.json` lists each document of `docs/` and no other. The
command refuses a link, a file of more than 16 MiB and a set of more than 10,000 documents.

The gold set digest is `sha256` of `groundgate-gold/1:` and the canonical JSON of
`{"groundgate_gold": 1, "files": {doc: {"text", "candidates", "judgments"}}, "labels"}`. Each
member of `files` is the `sha256` of the bytes of that file, and `judgments` is null when the
document has no judgment file.

### The split file, format 1

```json
{"groundgate_split": 1, "documents": {"inv-001": "calibration", "inv-002": "test"}}
```

Each gold document has one part. The calibration part picks the judge threshold. The test part
gives each number of the report. Write the split before you look at a decision, and keep it.
At least one document must be in the test part.

### What the command measures

The gate decides each document with the profile. For a field with keys, each key with a label
is one scored label. Then, for each field, on the test part:

- A **route** is `cleared` when the admitted decision has `MODEL_CLEARED`, and `checked`
  when it has not.
- **admitted** is the count of admitted values on the route. Two candidates with one value in
  one document are one admitted value.
- **errors** is the count of admitted values that are not the label. An admitted value for a
  null label is an error.
- **bound** is the one-sided 95% upper bound of the admitted error rate (Clopper-Pearson).
  With no admitted value, the bound is 1.
- **status** is `measured` only when the route has an admitted value and the bound is below
  the target. If not, it is `draft`.
- **review share** is the share of the scored labels with no admitted value and one or more
  `needs_verification` decisions.
- **miss rate** is the share of the labels with a value that get no admitted right value.

If the policy of the profile names a judge, the command picks the operating point on the
calibration part. It tries each `p` of the `key` judgments of that judge as
`clear.KEY_NOT_AT_VALUE`. For each threshold it counts the `cleared` values of all fields
together. It picks the lowest threshold whose bound is below the target. If no threshold
passes, the draft profile has no clear threshold, and no value is cleared.
With more than 100 different `p`, it rounds each `p` up to two decimal places first.

### The output

`DIR` gets three files. The command refuses a `DIR` that has one of them.

- `report.json`: report format 1, below.
- `REPORT.md`: the same numbers as a table.
- `profile.json`: the draft profile change. It is the input profile with the next patch
  version, the threshold of the operating point, one route row for each route with an admitted
  value, and the gold set digest. The command never writes the input profile. Read the draft,
  and then replace your profile with it if you agree.

```json
{"groundgate_calibration_report": 1, "spec": "0.12", "date": "2026-11-13",
 "profile": {"id": "rates-test", "version": "1.0.0", "sha256": "sha256:..."},
 "gold_sha256": "sha256:...", "split_sha256": "sha256:...",
 "documents": {"calibration": 4, "test": 6}, "target": "0.7",
 "operating_point": {"judge": {"id": "j", "digest": "j-1"}, "KEY_NOT_AT_VALUE": 0.7,
  "tried": [{"threshold": 0.6, "admitted": 4, "errors": 1, "bound": "0.7514", "passes": false}]},
 "fields": {"total": {"scored": 6, "with_value": 6, "review": 0, "review_share": "0",
   "missed": 2, "miss_rate": "0.3333", "unscored_admitted": 0,
   "routes": {"checked": {"admitted": 5, "errors": 1, "error_rate": "0.2", "bound": "0.6574",
                          "status": "measured"},
              "cleared": {"admitted": 0, "errors": 0, "error_rate": null, "bound": "1",
                          "status": "draft"}}}},
 "draft_profile": {"id": "rates-test", "version": "1.0.1", "sha256": "sha256:..."}}
```

A rate is a decimal string with at most 4 places, or null when there is nothing to count.
`split_sha256` is `sha256` of `groundgate-split/1:` and the canonical JSON of the split file.
The vectors of this format are in
[tests/vectors/calibrate](../tests/vectors/calibrate/README.md).

### Limits

- The measure scores the fields of the schema. It does not score the member fields of a record.
- The operating point is only `clear.KEY_NOT_AT_VALUE`. The command does not pick
  `doubt.field_match`.
- A small test part gives a high bound. With no error, a bound below 0.05 needs 59 admitted
  values on one route.

