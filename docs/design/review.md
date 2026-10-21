# Review: the step that collects a person's answers

Status: approved on 2026-10-20, issue #287. Only the formats of section 5 are built (#408). It
changes no decision. The review step keeps its data in the store of [store.md](store.md) (#288),
so the two notes go together. The last section lists the code issues.

## 1. The answers in short

| Question (#287) | My answer | Section |
|---|---|---|
| Where the step goes | After `admit`: `read -> extract -> admit -> review -> app`. `report` stays the read-only page. | 3 |
| How an answer reaches the app | Outside `admit`. An answer never changes the receipt and never enters `admit` as a judgment. A resolution with no model reads the receipt and the answers. | 2, 6 |
| How a correction is checked | It is a new candidate with a person as proposer. It goes through `admit` with the other candidates of the packet. | 6.2 |
| The formats | Four store kinds: `review-policy@1`, `task@1`, `answer@1` and `resolution@1`. | 5 |
| `unsure` | It never settles a task. The task stays open for another reviewer. | 6.1 |
| Two reviewers who disagree | The slot is `disputed`, and the app gets no value. Only a reviewer that the review policy names as a lead settles it. | 6.1 |
| The six item kinds | One question template and one view for each. Format 1 builds number, text and long span. Closed set, model text and structure wait for their inputs. | 7 |
| The UI | A local server, `groundgate review serve`, with the standard library only and no script from another host. | 8, 9 |
| Answers as labels | An audit answer is a blind label. A review answer is not blind. It counts as a label for a measure only after #234 shows agreement for its kind. | 10 |

## 2. Three options

**A. Answers as recorded judgments.** SPEC §2.6 already lets a person be a judge, so the app
could send each answer back into `admit` as a judgment. But a judgment answers only the
questions `key` and `field_match`, with a probability, about a candidate in the packet. It
cannot choose between two values, correct a value or move a span. To widen it changes
decisions, so it is a new spec version. The receipt then also mixes the record of the gate with
the record of the person.

**B. A review layer outside `admit`.** The receipt stays the record of the gate. Tasks and
answers are new records beside it, and a resolution combines them with no model. A correction
is a candidate, so the gate still checks its span. This changes no decision and needs no spec
version.

**C. Formats only.** groundgate defines the formats and the resolution, and each app builds its
own page. This is less code. But most of the time goes into the page, and the bench label pages
show that small details change the answers (section 8). Nothing would measure the page.

I choose B. It keeps the property of C: the formats are public, and the groundgate page is one
client of them.

## 3. The step and what a user sees

The module is `groundgate.review`. It is outside `admit`, as `groundgate.extract` is. It calls
`admit`, and the core never imports it. It uses only the standard library.

```bash
groundgate review tasks    --store DIR PACKET            # write the tasks of one packet
groundgate review serve    --store DIR --reviewer ana    # answer them in the browser
groundgate review resolve  --store DIR PACKET            # write and print the resolution
groundgate review measures --store DIR                   # the measures of section 10
```

`PACKET` is the store key of one `admit` call (store.md §5). A user sees this:

1. `review serve` prints `http://127.0.0.1:<port>/#<token>`. The user opens it.
2. The page shows one item. The source page with the value in a box is on the left. The
   question, the choices and the keys are on the right.
3. The user presses one key. The next item opens, and the page shows how many items are left.
4. To correct a value, the user selects it in the text. If the gate refuses the selection, the
   page shows the reason at once.
5. `review resolve` prints one line for each field: the final value, or the reason that there is
   none.

## 4. Terms

- A **slot** is one thing that a person decides: a field and a key, or one decision of a
  `multiple` field.
- A **task** asks about one slot. The **review policy** sets which slots get a task.
- An **answer** is what one reviewer gives for one task.
- The **resolution** gives the final state and value of each slot. The app reads it.
- An **audit** task asks about an admitted value that the review policy picked at random. The
  page does not show that the gate admitted it.
- A **lead** is a reviewer whose answer settles a dispute.

## 5. The formats

Each format is a store kind with a version. A new version is a new kind, so an old key never
gets a new meaning (store.md §4). Each format gets a JSON Schema in the package, as
`candidate.schema.json` does.

### 5.1 The review policy

```json
{"format": "review-policy@1",
 "audit": {"rate": "0.02", "seed": "2026-10-lease"},
 "agree": 1,
 "leads": ["ana"],
 "rejected": false}
```

- `audit.rate` is the share of admitted slots that get an audit task. `"0"` turns the audit off.
- A slot gets an audit task when the first 8 bytes of SHA-256 over `seed`, the packet key, the
  field and the key, as an integer divided by 2^64, are less than `rate`. The pick is a function
  of the policy, so it needs no log, and anyone can check it. Section 6.3, point 2, gives the
  exact bytes and the comparison.
- `agree` is how many reviewers must agree before a slot resolves. The default is 1.
- `leads` names the reviewers who can settle a dispute. The default is none.
- `rejected: true` also makes a task for a slot whose decisions are all rejected. The default
  is false.

### 5.2 The task

`review tasks` makes a task for each slot that one of these rules selects:

1. A slot with a `needs_verification` decision. Its choices are each decision of the slot that
   passed, in decision order. A rejected decision of the slot shows as another reading, with no
   choice key.
2. A coverage entry `REQUIRED_FIELD_MISSING`. The task has no choice.
3. An audit pick: a slot with exactly one passed decision, and that decision is admitted.
4. With `rejected: true`, a slot whose decisions are all rejected.

```json
{"format": "task@1",
 "packet": "sha256:...",
 "slot": {"field": "total_revenue", "key": "2025", "decisions": [3, 7]},
 "item": "number", "mode": "review", "template": "number@1",
 "question": "Which amount is total revenue for 2025?",
 "parts": ["amount", "scale", "sign", "unit", "field", "key"],
 "codes": ["CONFLICTING_CANDIDATES"],
 "choices": [{"decision": 3, "value": "4200000", "unit": "USD", "shown": "$4,200,000 (written 4,200, in thousands)",
              "evidence": {"start": 18120, "end": 18125}},
             {"decision": 7, "value": "4200", "unit": "USD", "shown": "$4,200",
              "evidence": {"start": 18120, "end": 18125}}],
 "places": [{"start": 18120, "end": 18125, "page": 41, "box": [72.0, 310.5, 101.2, 321.0]}]}
```

- `mode` is `review` or `audit`.
- With one choice, the question names that value: "Is total revenue for 2025 $4,200,000
  (written 4,200, in thousands)?"
- `template` names the question template and its version. If a bad question gives bad answers,
  a later analysis finds every answer to that template (#287, rule 3).
- `parts` lists each part that the person checks. The question names each of them (section 8).
  The core has no period, so the period comes from the field name, its description or its key.
- A task holds offsets, pages and boxes. It holds no document text other than the values that its
  question and choices quote. The page reads the text from the store. Thus `forget` can remove
  the text and keep the tasks, and `forget --all` also removes the values (store.md §8).
- The task names no review policy. The same packet always gives the same task bytes for a slot,
  so a task always has the same key, and a new policy keeps the answers (section 6.3, point 1).
- `slot.decisions` lists each decision of the slot, passed or rejected, in receipt order. The
  page reads a rejected decision from the receipt.

### 5.3 The answer

An answer is one record of an answer log (store.md §6). Each reviewer writes a separate log for
each packet.

```json
{"format": "answer@1", "task": "sha256:...", "reviewer": "ana",
 "verdict": "correct",
 "decision": null,
 "candidate": {"id": "review-1", "field": "total_revenue", "key": "2025", "value": "4200000",
               "unit": "USD", "proposer": "person:ana",
               "evidence": [{"start": 18120, "end": 18125},
                            {"role": "scale", "start": 17002, "end": 17025}]},
 "codes_kept": [],
 "statements": null, "nodes": null,
 "reason_seen": false, "keys": 3, "ms": 8400, "time": "2026-10-20T10:31:07Z"}
```

| Verdict | Means | Needs |
|---|---|---|
| `confirm` | The only choice is right. | nothing |
| `choose` | This choice is right. | `decision` |
| `correct` | No choice is right. The right value is at the selected span. | `candidate` |
| `adjust_span` | The value is right, but its span starts or ends at another place. | `candidate` |
| `not_in_document` | The document does not give this field. | nothing |
| `unsure` | The person cannot tell. | nothing |

- `candidate` is a normal candidate (SPEC §2.5). The checks ignore `proposer`, but the candidate
  digest covers it.
- `codes_kept` lists each code of a correction that the person saw and kept (section 6.2).
- `statements` and `nodes` are for model text and structure (section 7). They are null in
  format 1.
- `reason_seen`, `keys`, `ms` and `time` are for the measures. The resolution never reads them.

### 5.4 The resolution

```json
{"format": "resolution@1", "packet": "sha256:...", "policy": "sha256:...",
 "answers": [{"reviewer": "ana", "head": "sha256:..."}],
 "slots": [{"field": "total_revenue", "key": "2025", "decisions": [3, 7], "status": "corrected",
            "value": "4200000", "unit": "USD", "evidence": {"start": 18120, "end": 18125},
            "receipt": "sha256:...", "task": "sha256:...", "statements": null, "nodes": null}]}
```

`answers` names the head of each answer log that the resolution read, in code point order of
the reviewer name. Thus the app can show which answers it used. `receipt` is the correction
receipt when the value comes from a correction. If not, it is the receipt of the packet. Slots
are in code point order of the field, then of the key with null first, then of the first
decision. `decisions` tells apart two slots of a `multiple` field. `statements` and `nodes` are
null in format 1 (section 7).

| Status | The app gets |
|---|---|
| `admitted` | The value of the gate. There is no task, or an audit agrees. |
| `confirmed`, `chosen`, `corrected` | The value of the person. |
| `not_in_document` | No value. The person says that the document does not give it. |
| `rejected` | No value. Each decision was rejected, and the policy makes no task. |
| `open` | No value. No answer settles the task yet. |
| `disputed` | No value. Two reviewers disagree. |

## 6. The resolution rules

### 6.1 Answers

The resolution is a pure function of the packet, the review policy, the tasks and the answer
logs. It reads no clock and calls no model. The same inputs give the same bytes.

1. The latest answer of each reviewer to a task counts. The log keeps the earlier answers.
2. `unsure` counts as no answer. The queue gives the task to another reviewer next.
3. `confirm` is the same as `choose` of the only choice. A task with two or more choices has no
   `confirm`.
4. Two answers agree when they have the same verdict and the same target. The target of
   `choose` is the decision. The target of `correct` and `adjust_span` is the canonical value,
   unit and key for a number, and the start and end for text. `not_in_document` has no target.
5. A slot resolves when at least `agree` reviewers give answers that agree, and no reviewer
   gives an answer that disagrees.
6. If two answers disagree, the slot is `disputed`. The latest answer of a lead settles a
   dispute alone. With no lead, the slot stays `disputed`.
7. An audit answer that confirms the value keeps the slot `admitted`. Each other answer, except
   `unsure`, removes the admitted value. Rules 1 to 6 then apply to the answers of the slot.

Under rule 7, the gate is wrong when one person says so. That is safe for the app, because it
gets no value until the answers settle. The measure counts an escape only when the slot then
resolves to another value or to `not_in_document`.

### 6.2 Corrections go through `admit`

A `correct` or `adjust_span` answer holds a candidate. The resolution runs `admit` one time for
each such answer, with:

- the text, schema, policy, references and packs of the packet;
- the candidates of the packet, without the candidates of the slot, and with the person's
  candidate;
- the judgments of the packet, without the judgments of the removed candidates. A judgment for
  a candidate that is not in the packet makes the packet invalid (SPEC §2.6).

The other candidates stay, so a relation (SPEC §3.4) checks the person's value against the
other fields. The resolution takes from this correction receipt only the decision of the
person's candidate, and it keeps the receipt in the store.

1. If that decision is `admitted`, the correction counts.
2. If it is `needs_verification`, the correction counts only when `codes_kept` holds each of its
   codes. Before the person keeps a code, the page shows it in plain words from
   `codes.DESCRIPTIONS`.
3. If it is `rejected`, the correction never counts. The page shows the code at once, and the
   person selects again.

Rule 2 finds a typing error. If the person types 4,200 for a value under "in thousands", the
gate flags `SCALE_WORD`, and the person must keep that code with one more key. If the gate gives
`PART_MISSING`, the page asks the person to select the part, for example the scale line, and it
adds the part as a role item.

The server runs the same `admit` call when the person answers, so the page shows the outcome at
once. The resolution runs it again and does not trust the server.

### 6.3 Points that the cases settle

The note review (#397) left open points, and the cases of #408 need an answer for each. The
cases under `tests/review/cases/` name these points as rules `6.3.1` to `6.3.9`.

1. **A policy change keeps the answers.** A task names no review policy. Each slot has at most
   one task, and the receipt sets its mode: `audit` for a slot with one passed decision that is
   admitted, and `review` for each other slot. An answer counts when its task is the task of a
   slot of the packet, also when the current policy does not make that task. The policy sets
   which tasks the queue shows, and `agree` and `leads`. Thus a new lead or a new audit rate
   never removes an answer.
2. **The audit pick.** H is the first 8 bytes, big-endian, of SHA-256 over the ASCII bytes
   `groundgate-audit/1:` and then the UTF-8 canonical JSON (RFC 8785) of the list
   `[seed, packet key, field, key, decision]`. `key` is null for a field without keys.
   `decision` is the receipt index of the decision for a `multiple` field, and null for other
   fields. JSON quotes each string, so two different lists never give the same bytes. `rate` is
   a decimal string with at most 18 digits after the point, and no last 0 after the point. With
   `rate` = n / 10^d, the slot gets an audit task when H * 10^d < n * 2^64. This is integer
   arithmetic, with no float. `tests/review/audit-picks.json` has vectors.
3. **The status names.** A slot that resolves to a choice is `confirmed` when its task has one
   choice, and `chosen` when it has two or more. `correct` and `adjust_span` give `corrected`.
   An audit confirm gives `admitted` (rule 7).
4. **Two leads.** The latest answers of the leads settle a dispute when they agree with each
   other. If two leads disagree, the slot stays `disputed`. A lead whose latest answer is
   `unsure` has no answer.
5. **An answer that breaks its task.** For example: `confirm` on a task with no choice or with
   two or more choices, `choose` of a decision that is not a choice, or a candidate for another
   field or key. Then the resolution stops with an error that names the reviewer and the
   sequence of the record. It does not skip the record, because the server checks each answer
   before the write (section 9, rule 8), so such a record shows a fault.
6. **Agreeing corrections at two spans.** For a number, two corrections at different spans can
   agree (rule 4). The value, the evidence and the receipt then come from the correction of the
   first reviewer in code point order of the name.
7. **A correction that does not count** (section 6.2, rules 2 and 3) is no answer under rules 4
   to 6. Under rule 7 it still removes an admitted value, because the person said that the value
   is wrong.
8. **The kept codes.** `codes_kept` must hold each code of the correction decision that is not
   informational. `EVIDENCE_REANCHORED`, `VALUE_DERIVED`, `KEY_CITED`, `ADMITTED_BY_POLICY` and
   `MODEL_CLEARED` do not need a key.
9. **The order.** Section 5.4 gives the order of `answers` and of `slots`.

## 7. Item kinds

In format 1, the field type selects the kind. A `number` or `integer` field gives `number`. A
`string` field gives `text`, or `span` when the value has more than 300 characters or a line
break.

| Kind | The question names | The view | Answer | Format 1 |
|---|---|---|---|---|
| `number` | the amount as written and in full, scale, sign, unit, field, key | the page with the value in a box | all six verdicts | yes |
| `text` | the entity and its role: "Is 'Example Holdings Ltd' the lessor, not the lessee?" | the full sentence, with a mark at each end of the span | all six verdicts | yes |
| `span` | the start and the end | the start and the end with their context, and the middle closed | all six verdicts; the arrow keys move an end | yes |
| `closed_set` | the option, and that no other option fits | the quote and the option list; one key chooses another option | `confirm`, `choose`, `not_in_document`, `unsure` | no |
| `model_text` | each statement | the model text beside the source; each statement next to its cited span, with the words that differ marked | `statements`: `supported`, `unsupported` or `unsure` for each | no |
| `structure` | each node of a page | the page with the nodes in boxes; accept or correct in bulk | `nodes`: the nodes accepted and corrected | no |

Format 1 reserves the kind names and the members `statements` and `nodes`. A later kind adds a
template and a view, and it does not change `answer@1`.

- A **closed set** needs a schema member with the options. That changes what the gate checks,
  so a spec issue comes first.
- A **model text** task comes from an input that the app gives: the model text and its
  statements, each with a cited span. The core never admits model text (#285). A statement is
  not a candidate. The resolution gives the verdict of each statement, not a value.
- A **structure** task is only for a node that the app uses, for example a node that a field
  cites (#285).

## 8. The page

These rules come from the bench label pages, where I measured what works.

- **The source.** For a PDF, the page draws the source page from the word boxes of
  `layout.json` as positioned text, with the value in a box. For HTML, it shows the original
  page in a sandboxed frame (section 9). It marks the value there only when the value text
  occurs one time on the page. If not, the page says so. For plain text, it shows the lines
  around the value.
- **The question names every part.** "$4,200,000 (written 4,200, in thousands)", not "4,200".
  On the bench, most wrong answers came from a part that the question did not name, usually the
  scale. If the scale line is on an earlier page, the page shows that page too, or names it.
- **Conflicts side by side.** Each choice shows its value and its span. One key picks one.
- **One key for each answer.** `y` confirm, `1` to `9` choose, `x` not in the document, `u`
  unsure. `n` opens the choices and the selection, and `s` starts a selection. `r` shows the
  reason. The arrow keys go back and forward.
- **A correction is a selection.** The page reads the selected number with the core reader and
  shows the value in full. The person can type the value instead, and the gate then checks it
  against the span.
- **The reason is closed.** The page shows no outcome and no code until the person presses `r`.
  This applies to each task, so a review task with one choice and an audit task look the same.
  The answer records `reason_seen`.
- **Order.** Tasks are grouped by document and in page order. After an answer, the next task
  opens, and the page shows how many are left. A task that this reviewer answered, or a slot
  that is resolved, leaves the queue.

The bench measured the pdf.js page view, not the word-box view. Issue 5 measures the word-box
view on a development split before I say that it is as good. The page loads no script from
another host (section 9). If the word-box view gives less agreement, a later issue adds a PDF
renderer to the package as data, with its license.

## 9. Security

The report page stays as it is: no scripts, and a Content-Security-Policy that blocks them.

The review page needs a script, so it is a separate local server. Its rules:

1. Bind to `127.0.0.1` only. Refuse a request whose `Host` header is not `127.0.0.1:<port>`.
   This stops DNS rebinding.
2. Make a random token at start with `secrets`. Put it in the start URL after `#`, so that it
   does not go into a server log. Each API request sends it in a header. Refuse a request
   without it, so that another site cannot write an answer.
3. Accept a POST only with `Content-Type: application/json` and a body of at most 64 KiB.
4. Send a CSP header with each response: `default-src 'none'; script-src 'self'; style-src
   'self'; connect-src 'self'; frame-src 'self'; img-src 'self'; form-action 'none'; base-uri
   'none'; frame-ancestors 'none'`. The script and the style are files in the package.
5. Put document text into the page only with `textContent`, never with `innerHTML`.
6. Serve an HTML source in a frame with `sandbox=""` and its own CSP, `default-src 'none';
   style-src 'unsafe-inline'`. It runs no script and loads no image, so it cannot call an
   outside host.
7. Read objects only by a store key that matches `sha256:[0-9a-f]{64}`. Take no path or URL from
   a document, a reply, a task or a request.
8. Check each answer against its task before the write: a verdict that the kind permits, a
   decision in the choices, and a span inside the text.

A PR for the server needs a security review. The calibrate label page follows the same rules
when it moves into this server (issue 6).

## 10. Answers as labels, and the measures

Each answer is also a label (#287, rule 4). But a review answer is not blind, because the person
sees the proposed value. #234 measures whether review answers agree with blind labels on items
that the reviewer did not label.

1. An audit answer with `reason_seen` false is a blind label.
2. A review answer is a label for a measure of its kind only after #234 shows agreement for that
   kind.
3. An answer on a document in the development split can go into the learning loop of #383. No
   answer on a document in the held-out split goes into it. The split comes from the `splits`
   log (store.md §10).

`review measures` gives these measures for each kind, and for each field in that kind:

- the time for each item, from `ms`;
- the share of items answered with one key, from `keys`;
- the agreement of the answers with blind labels (#234);
- the escapes that the audit finds (section 6.1, rule 7).

The first two measures show that the review is fast. The last two show that it is right. A
faster page that lowers agreement is a loss. The measures never put the kinds in one average,
because a long span or a summary takes much more time than a number. Each kind has its own
extra measure:

| Kind | Extra measure |
|---|---|
| `text`, `span` | The share of answers that move a span end, and how far |
| `closed_set` | The share of answers that choose another option |
| `model_text` | The time for each statement, and the share of statements marked `unsupported` |
| `structure` | The time for each page, and the share of nodes corrected |

## 11. Fit with other work

- **#288, the store.** Tasks, review policies, correction receipts and resolutions are objects.
  Answers are logs. The queue and the measures are views.
- **#385, calibrate in groundgate.** A calibrate item is a blind task, and a calibrate label is
  an answer. Issue 6 moves `groundgate calibrate label` onto this server. Calibrate keeps its
  work folder in 0.11, and its labels come from a view of the answer logs.
- **#383, the development split.** Section 10, point 3.
- **#285, the document model.** The `structure` kind, and a node id as a place in a task, come
  with the document model in 0.12.
- **#66.** A model that answers review tasks is a judge. It stays outside `admit`, and this note
  adds none.

## 12. Changes to other docs

- `docs/howto/review.md` keeps the report page. When the server ships, it gets a second part
  for the answers.
- `docs/design/hybrid-decisions.md`: a person on the review page gives an answer, not a
  judgment. A person can still give a judgment as SPEC §2.6 says.
- `CONTEXT.md` gets the terms of section 4.

## 13. Code issues

I open these after the maintainer approves this note and store.md. Issues 1 to 3 wait for store
issues 1 and 2. No issue changes a decision.

1. **Review formats, with resolution cases by hand.** JSON Schemas for the four formats. Cases
   under `tests/review/cases/`: a packet, a policy, answers and the expected resolution, written
   by hand before the code. They cover each rule of section 6. Done in #408, with the points of
   section 6.3.
2. **`groundgate review tasks`.** The rules of section 5.2, the audit pick, and the templates
   `number@1`, `text@1` and `span@1`.
3. **`groundgate review resolve`.** The rules of section 6, with corrections through `admit` and
   the correction receipts in the store.
4. **`groundgate review serve`.** The page of section 8 and the rules of section 9, for
   `number`, `text` and `span`. Needs a security review.
5. **`groundgate review measures`, and a first measure.** The measures of section 10 on the
   development split of a bench set, with blind labels, beside #234. It gives the agreement of
   the word-box view, so that I can compare it with the pdf.js pages of the bench.
6. **Calibrate labels through the review server.** After #385. Calibrate items become blind
   tasks, and `labels.json` becomes a view. Needs a security review.
7. **Later kinds.** `structure` with #285 in 0.12. `closed_set` after a spec issue for the
   options. `model_text` after an issue for its input. The OCR crop with #7.
