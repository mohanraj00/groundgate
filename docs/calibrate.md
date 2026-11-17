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
    [--target 0.05] [--date YYYY-MM-DD] [--audit A] [--audit-since YYYY-MM-DD]
```

With `--audit A`, the blind audit labels of the audit set `A` count with the labels of the test
part ([audit](#audit-a-blind-sample-of-production-documents)). These two are the only labels
that the command reads. A review answer and the decision of an approver never count for a
bound, because that person saw the proposed value.

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
document does not list is not scored. A label key must be equal to a key of the schema, with no
change of case. Each label must come from a person who did not see the decisions.

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
- **unscored** is the count of admitted values on the route that no label covers: a field or
  a key that the labels of the document do not list, or a member field of a record.
- **status** is `measured` only when the route has an admitted value, `unscored` is 0 and the
  bound is below the target. If not, it is `draft`.
- **review share** is the share of the scored labels with no admitted value and one or more
  `needs_verification` decisions.
- **miss rate** is the share of the labels with a value that get no admitted right value.

If the policy of the profile names a judge, the command picks the operating point on the
calibration part. It tries each `p` of the `key` judgments of that judge as
`clear.KEY_NOT_AT_VALUE`. For each threshold it counts the `cleared` values of all fields
together. It picks the lowest threshold whose bound is below the target.
A threshold that clears a value with no label does not pass, so label each key that your
extractor can propose. If no threshold
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
  "tried": [{"threshold": 0.6, "admitted": 4, "errors": 1, "bound": "0.7514",
             "unscored": 0, "passes": false}]},
 "fields": {"total": {"scored": 6, "with_value": 6, "review": 0, "review_share": "0",
   "missed": 2, "miss_rate": "0.3333",
   "routes": {"checked": {"admitted": 5, "errors": 1, "error_rate": "0.2", "bound": "0.6574",
                          "unscored": 0, "status": "measured"},
              "cleared": {"admitted": 0, "errors": 0, "error_rate": null, "bound": "1",
                          "unscored": 0, "status": "draft"}}}},
 "draft_profile": {"id": "rates-test", "version": "1.0.1", "sha256": "sha256:..."}}
```

A rate is a decimal string with at most 4 places, or null when there is nothing to count.
`split_sha256` is `sha256` of `groundgate-split/1:` and the canonical JSON of the split file.
The vectors of this format are in
[tests/vectors/calibrate](../tests/vectors/calibrate/README.md).

### Limits

- The measure does not score the member fields of a record. It counts each admitted member
  value as `unscored`.
- The operating point is only `clear.KEY_NOT_AT_VALUE`. The command does not pick
  `doubt.field_match`.
- A small test part gives a high bound. With no error, a bound below 0.05 needs 59 admitted
  values on one route.

## audit: a blind sample of production documents

A gold set tells you how a profile did before you used it. The blind audit tells you how it
does on the documents that it decides now ([SPEC §4.18](../SPEC.md),
[#643](https://github.com/mohanraj00/groundgate/issues/643)). It picks whole documents at
random, and a person labels each field without the proposed value. `calibrate measure --audit`
then counts those labels with the gold set labels.

The page for the audit task is not part of this command. It is a separate issue.

### The audit set, format 1

`A` is a directory that you keep:

- `A/audit.json`: `{"groundgate_audit": 1, "seed": "2026-11-audit"}`. Choose the seed one
  time, before the first document, and do not change it.
- `A/log.jsonl`: the audit log. Each line is one entry in canonical JSON.
- `A/labels.jsonl`: the audit labels. Each line is one label in canonical JSON.
- `A/docs/<doc>.txt`, `A/candidates/<doc>.json` and the optional `A/judgments/<doc>.json`:
  the recorded inputs of each labelled document, as in a gold set.

```bash
groundgate calibrate audit add  --audit A --name DOC --receipt receipt.json
groundgate calibrate audit pick --audit A [--profile P] [--out pick.json]
groundgate calibrate audit rate --audit A --report DIR/report.json
```

### The log and the pick

`audit add` adds one document entry to the log for a receipt that a profile decided:

```json
{"document":"inv-0007","entry":"document","items":4,"profile":"sha256:..."}
```

`items` is the count of the admitted values of the receipt. Add each document that the gate
decides, in the order in which it decides them, also a document with no admitted value.

`audit pick` replays the pick from the seed and the log. It reads no clock and no label, so
the same seed and the same log give the same documents each time:

- For each profile version, each document is picked until the picked documents have 30 items.
- After that, a document is picked when its hash is below the rate of its profile version. The
  rate starts at 10%.
- A new profile version has a new digest, so it starts again at 10% with no picked item.

With `--profile P`, the output also has the tasks of the picked documents of that profile: one
task for each field, and one for each key of a field with keys.

```json
{"groundgate_audit_task": 1, "document": "inv-0007", "profile": "sha256:...",
 "field": "total", "key": null}
```

A task gives the document and the field only. It has no proposed value, no evidence and no
outcome, and a field with an admitted value gets the same task as a field with none.

### The labels

The labeler reads the document and writes the right value of each task, in the canonical form
of the receipt `value`, or null when the document has no value for the field:

```json
{"date":"2026-11-15","document":"inv-0007","field":"total","groundgate_audit_label":1,"key":null,"labeler":"ana","profile":"sha256:...","value":"90"}
```

The format is closed. A record with another member, for example the `verdict` of a review
answer or the decision of an approver, stops the measure. So does a label of a document that
is not in the pick. The last label of one document, field and key counts.

### The measure and the rate

`calibrate measure --audit A` replays the pick, reads the labels of the profile `P`, and decides
each labelled document again from its recorded candidates and judgments. It counts those
documents with the test part of the gold set. The report then has an `audit` member:

```json
"audit": {"audit_sha256": "sha256:...", "seed": "2026-11-audit", "since": null,
          "picked": 34, "documents": 30, "duplicates": 0, "admitted": 41, "skipped": 0,
          "routes": [{"field": "total", "route": "checked", "admitted": 43, "errors": 0,
                      "error_rate": "0", "bound": "0.0673", "unscored": 0,
                      "status": "measured"}],
          "rate": "0.02", "alerts": []}
```

The measure decides the audit documents two times when the draft has another clear threshold
than `P`. The `fields` of the report and the routes of the draft come from the draft profile.
The `audit` member comes from `P` as it is, because the log and the labels name the digest of
`P`. So an error that `P` admits gives an alert, also when the draft does not admit that value.

- `picked` is the count of the picked documents of the profile, and `documents` the count of
  them with a label. `admitted` is the count of the values that `P` admits and the labels cover.
- `duplicates` is the count of the labelled documents that do not count. A document text
  counts one time: an audit document with the text of a gold set document does not count, and
  nor does one with the text of an audit document before it in the log.
- `routes` has one row for each route of `P` with an admitted value, from the test part and the
  audit documents together. Its members are those of a route in `fields`.
- `skipped` is the count of the labels of another profile version, or of a day before
  `--audit-since`.
- `rate` is the next audit rate. It is `0.02` when the audit labels cover 30 or more admitted
  values and each route with an admitted value is `measured`. If not, it is `0.1`. A route
  whose admitted values all have no label (`unscored`) is a `draft`, so it keeps the rate at
  `0.1`.
- `alerts` lists each route of `routes` with a labelled admitted value whose bound is not below
  the target. The command prints one `alert:` line for each. With `--audit-since`, only the
  labels from that day on count, so the alert is for that period.

`audit rate` adds the rate of a report to the log as a rate entry. It refuses the report of an
audit set with another seed. The pick uses the rate from that line on. So the rate goes down to 2% while each bound stays below the target, and it goes up
again to 10% when a bound passes the target or the profile version changes.

The route rows of the draft profile count the audit documents in `documents`. `gold_sha256`
stays the digest of the gold set.

## events: the decisions of an outside approver

An approver outside groundgate sees the exported facts (`facts@1` or `facts@2`) and approves,
rejects or corrects each one. Each decision can come back as one calibration event
([SPEC §4.19](../SPEC.md), [#642](https://github.com/mohanraj00/groundgate/issues/642)). The
events tell you where a profile version needs work. They are not labels: the approver saw the
proposed value, so an event never counts for a bound. `calibrate measure` and the audit never
read them.

```bash
groundgate calibrate events add --store S --events approvals.jsonl
groundgate calibrate events suggest --store S --profile invoice.json --out drafts.json
```

### The events file

The events file has one JSON event (SPEC §4.19) on each line, and each line ends with a line
break. The approver writes it. `fact_sha256` is the digest of kind `fact` over the fact object
that the approver saw. `groundgate.calibrate.events.fact_sha256(fact)` calculates it.

`events add` checks each event before it writes one. Then it appends each event to the `events`
log of its profile digest in the store. An event with the `origin` of an event in the log is a
copy, and `add` does not write it. So you can add the same file again. The command prints the
count of the new events and of the copies. `store check` reports an events log with a record
that is not an event of its profile.

### The drafts

`events suggest` reads the events of the profile version of `--profile` and writes the drafts
as JSON (`groundgate_profile_drafts`, format 1). It changes nothing: you accept or refuse each
draft, then you make a new profile version and measure it. The new version has a new digest,
so it starts with no events.

- `review_share`: one for each field and key with events, in code point order. It gives the
  counts of the approved, rejected and corrected values, and `share`, the part of the events
  that the approver found wrong, rounded up to two decimals. A high share tells you to send the
  field to review, or to keep its route a draft.
- `value_test`: one for each rejection and correction, in log order. It names the packet, the
  value that the gate must not admit (`refuse`) and the right value (`admit`, null for a
  rejection and for a correction to null). Add it to your gold set or to your tests, and
  replay the packet with a new profile version to see the effect, with no model call.
- `term`: one for a correction to a string when the right value is on exactly one line of the
  packet text, with words before it on that line. `alias` is those words, with the punctuation
  and spaces at the end removed. The draft names the packet and the line. A field name or an alias that the
  field has already gives no draft. Check each term against the document before you add it to
  the field's `aliases`.

`missing_packets` lists each packet of a correction that is not in the store. A correction of
such a packet gives no term. `suggest` scans the packet text once for each packet
and right value, and for at most 1024 of them. `unscanned_corrections` counts the corrections
after that bound, which give no term.
