# Extensions: a general core, packs for kinds of documents, and tools for the app's documents

Status: design for discussion, issue #275. Nothing in this file is built. It changes no decision.
The locale design (#60, [locale-packs.md](locale-packs.md)) is one kind of pack in this design,
and the hybrid design ([hybrid-decisions.md](hybrid-decisions.md)) supplies the judge and the
audit sample. This file extends the modes and plug-in packs of the hybrid design (§7) from locales
to kinds of documents.

## 1. The problem

The sets that measure extraction of fields are digital documents in English from U.S. government
sources or U.S. public companies: drug labels, IRS publications, accident reports and Federal
Register documents in the v0.1 set and set 2, and annual financial reports of companies, federal agencies
and states in the 0.8 sets. One small set from outside the U.S. exists: `bench/india` reads 101
number tokens from SEBI circulars, and it measures one number rule, not fields. A rule written
from one of these documents and measured on a different one is held out by document, not by kind.
So no published number says how groundgate extracts fields from an invoice, a bank statement, a
product datasheet, a report from a different country, a scan or a folder of mixed documents.

I see three layers of knowledge in groundgate today, and they are not equally at risk:

| Layer | Examples | Tuned to the sets? |
|---|---|---|
| Safety checks | the value is at the location; scale, unit and sign agree; a qualifier sends the value to review | No. They are true for every document. |
| Reading heuristics | scale phrases such as "in thousands", label lines, table rows, how a key mention is found | Probably. They came from the sets. |
| Extraction | how a PDF table becomes rows with tabs | Yes. It came from the layouts in the sets. |

Some knowledge already comes from the app. The schema carries `aliases` and `keys` (SPEC §2.3),
the units table, and the policy carries a `judge` (§2.4). So the core is partly ready for this
design. The rest of the knowledge is in code.

A strict gate on an unfamiliar document fails mostly toward review, not toward an escape. If it
cannot find the scale or the key, it asks a person. I expect an unfamiliar kind of document to
cost reviews and misses, and to keep few escapes, except for one class: the right number for the
wrong field. That class is about meaning, and a rule cannot see meaning. This is an expectation,
not a measure. Section 10 says how I measure it.

## 2. The goal

- The core is general. Its checks are true for any document, and it holds no knowledge about one
  kind of document.
- Knowledge about a kind of document comes from an **extension** that the app adds: groundgate's
  own packs, a third party's, or the app's.
- An app whose documents are mixed or scanned, with no pack that fits, gets **tools** that measure
  and improve reliability on its own documents.
- Every guarantee stays. The decision is deterministic and dependency-free, never calls a model,
  and `groundgate verify` reproduces each receipt.

Not in this design: non-Latin scripts, dates, arrays of records, and checks across documents.
Each one needs its own design.

## 3. The layers and where extensions plug in

The core is a gate, not an extractor. It receives a value and a location, and it decides. Each
layer around it is general and accepts extensions:

| Layer | Its job | "General" means | Extension |
|---|---|---|---|
| Readers | turn a file into text with locations | reads PDF, scans, word-processor and spreadsheet files (DOCX, XLSX), HTML | a reader |
| Runner (#268) | asks the model for the requested fields and repairs them | works with any field list | a strategy |
| Core | decides admitted, needs_verification or rejected | its checks are true for any document | a pack, a check |
| Judges | answer a question of meaning before the decision | any model, recorded | a judge |
| Tools | measure and improve on the app's documents | work on the app's own data | none |

## 4. Two rules

These two rules were decided on 2026-10-15. Every later section follows them.

**Rule 1. An extension that changes a decision is data, not code.**

A pack or a check is declared data with an id, a version and a status. groundgate resolves it
into the schema and the policy before the decision, and the receipt records its digest. If a pack
changes, every hash changes, and `verify` with the same pack gives the same outcome.

An app cannot add code to the decision. Code in the decision would break three things: `verify`
could not reproduce the receipt, the core would no longer be dependency-free, and a bad plugin
could read or change any input. Readers, strategies and judges can be code, because they run
outside the decision. Their output enters the core only as an input that the packet records (#66).

**Rule 2. An extension adds knowledge. It never removes a safety check.**

A pack can say that "Turnover" is a name of the revenue field. It cannot turn off the scale check,
widen the qualifier window to zero, or admit a value that a check rejects. The core has no switch
that a pack can reach for these.

A pack can still make groundgate less safe inside these limits. A wide list of aliases makes more
wrong values match a field. So the receipt names the pack that each check used, and the tools
measure each pack (section 10). A pack that nobody measured has the status `draft`, and the report
says so for every value that it helped to admit.

## 5. The extension points

| Extension | Layer | Data or code | In the receipt | Exists in 0.8 |
|---|---|---|---|---|
| Vocabulary pack | Core | data | digest | No. The locale design (#60) is the first one. |
| Kind pack | Core and runner | data | digest | Partly: `aliases`, `keys` and `units` in the schema. |
| Check | Core | data | digest | No. #273 is the first derived value. |
| Judge | before the core | code | each judgment that applied (candidate digest, question, answer, probability); the judge's id and version are in the policy, through `policy_sha256` | Yes, experimental: the `judge` block (SPEC §2.4, §2.6). |
| Reader | before the core | code | the document's digest only; `verify` needs the text again | PDF and markup extract. |
| Strategy | Runner | code | not in the receipt; in the runner's log | No. The runner is 0.9. |

For packs and checks, the digest in the receipt is a part of this design. A 0.8 receipt has no
pack and no check of this kind.

### 5.1 Vocabulary pack

Words that the reading rules use: scale words and phrases ("in thousands", "lakh"), unit words,
qualifier words, abbreviations, and number formats. The locale design is a vocabulary pack for one
language and region. Its principles hold for every vocabulary pack: the algorithm is fixed and the
pack supplies only lists and settings; a pack is measured before it is trusted; a rare form gets a
flag.

### 5.2 Kind pack

The knowledge about one kind of document, for example "financial filings" or "invoices":

- field templates: a name, a type, a unit, `aliases` and `keys`;
- the relations between those fields (5.3);
- the vocabulary packs that the kind needs;
- for the runner, the strategy that works best (outside the receipt).

An app takes the field templates that it needs into its schema. The schema that the app writes
still decides: if the schema gives a field's aliases, the pack does not add to them. If the
schema and a pack disagree on a type or a unit, the packet is invalid. groundgate never chooses
between them silently.

### 5.3 Check

A relation between fields, as arithmetic in a small fixed form, for example:

- a total equals the sum of its parts;
- assets equal liabilities plus equity;
- an invoice total equals the sum of its lines plus the tax.

Each relation has a tolerance for rounding. If a relation fails, every field in it goes to review
with one new code, because the core does not know which field is wrong. If a relation holds, the
core admits nothing more because of it, until a measure shows that this is safe. This is the
first defense against the right number for the wrong field that does not depend on a model. A
relation protects only fields that have one: a name, a date or an invoice number has none.

The exact form of a relation is for the spec version that adds it, with vectors written by hand.

### 5.4 Judge

A model answers a question of meaning, for example "is this location the field that the app asked
for?". The answer enters the packet as a recorded judgment, and the policy names the judge and its
thresholds. This is built and experimental. The plan for it has two stages:

1. **Doubt only.** A judgment can move a value from admitted to needs_verification. It can only add
   reviews, so it is safe to use before it is measured. `doubt.field_match` is this stage.
2. **Clear on a measured route.** A judgment can move a value from needs_verification to admitted
   only on a route (kind of document, field, code) where its error rate has a measured bound.
   `clear.KEY_NOT_AT_VALUE` is the first clear; the measure of it is #67 and #112.

A judge never admits a value that a check rejects. The judge must be a different model, or at
least a different prompt, from the extractor. A model that approves the output of a model is weak
evidence when both make the same error, so the tools measure how often both are wrong on the same
item.

### 5.5 Reader

A reader turns a file into text and locations: OCR for scans, and word-processor and spreadsheet files (DOCX, XLSX) (#7). A reader can
be code, because it runs before the decision. Its output is the document text that the receipt
already hashes.

A scan has one risk that a digital file does not have: the text itself can be wrong. If OCR reads
"8" as "3", the core grounds the value to wrong text, and the receipt looks good. So a reader for
scans must give a confidence for each span of text, and the core must take that confidence as
evidence: a value on text with low confidence goes to review. That is a decision change, and it
needs a spec version. A scan will have a lower ceiling than a digital file, and the report must
say so.

### 5.6 Router

A folder of mixed documents needs something that says which kind pack applies to each document.
The router is a model or a rule outside the core, and its answer is an input that the packet
records. If the router has low confidence, no kind pack applies, and the document uses the
general core only. A wrong kind applies the wrong aliases, so the tools measure the router too.

## 6. What a pack cannot do

- Turn off or weaken a check in SPEC §3 or §4.
- Add code that runs during the decision.
- Change the meaning of a code, an outcome or a receipt field.
- Change the result of `verify` without a change of its digest.
- Add a value to the document text or the evidence.

## 7. Tools for the app's own documents

No pack fits a folder of mixed or scanned documents. For these apps, the answer is not a better
rule but a measure on their own documents, and a short path from that measure to fewer reviews.

I do not plan one reliability score for each value. A score that nobody calibrated looks precise
and is not. The app gets a measured number for each field instead, from its own documents.

1. **Label kit.** The label page from the bench: the document page with the value boxed, beside
   the question. A person labels a sample of the app's documents blind, before any model output is
   shown. 50 to 100 documents is a start.
2. **Measure.** One command gives, for each field and for each pack: the admitted error rate with
   its bound, the share of right values sent to review, and the misses (section 10).
3. **Operating point.** For each field, the app chooses between more review and fewer escapes, or
   the opposite. The tool shows the measured trade-off for the policy settings. The app decides.
   groundgate never changes a policy by itself.
4. **Audit sample.** In production, a fixed random share of the documents goes to a person, and the
   person checks every admitted value in each sampled document (hybrid design §4, rule 6). A sample
   of whole documents supports both bounds of section 10: a sample of single values cannot show
   that a document has no wrong value. The tool gives the admitted error rate for each field over a
   recent period, and raises an alert when its bound passes the limit that the app set.
5. **Review answers become labels.** Each answer from a reviewer adds to the measure. The measure
   improves while the app works, with no extra work.
6. **Pack suggestions.** From review answers, the tool proposes knowledge for the app's own pack,
   for example: "reviewers approved 'Turnover' for the revenue field 40 times". A person approves
   each suggestion. The tool never applies one by itself, and an approved suggestion starts as
   `draft`.
7. **Changed-value test.** A script takes values that the app's reviewers approved and changes them
   in the ways that real errors occur: the number from the row above or below, the prior year
   column, a wrong scale, a wrong sign. It counts how many each check, pack and judge stops. It
   needs no new labels.

## 8. The status of an extension

Every pack, check and judge route has one status:

| Status | Meaning | Effect |
|---|---|---|
| `draft` | not measured on documents that nobody used to write it | can add doubt; the report marks each value that it helped to admit |
| `measured` | measured on held-out documents of its kind, with a published bound | can help to admit |
| `retired` | replaced or found unsafe | the core refuses it; old receipts still verify |

A pack can change its status only with a new version, so a receipt always says which status
applied.

## 9. What stays in the core

When this design is built, the core holds only:

- the safety checks of SPEC §3 and §4;
- one number reader, one qualifier matcher and one key matcher, which read their words from packs;
- the English vocabulary that every packet uses today, as the first vocabulary pack, so that a
  packet with no pack decides as it does now;
- the receipt, the digests and `verify`.

The first test of this design is a move. I take the knowledge that came from the current sets out of the
code and into the first kind packs, for example "financial reports". If every vector and every bench outcome stays the
same with the pack, the core is general. Each one that changes shows a rule that was tuned.

## 10. How I measure

**The main number is the admitted error rate**: of the values that groundgate admitted, the share
that are wrong. It is the number that an app needs before it trusts a value with no check. Next
to it: the share of right values sent to review (the manual work that the core causes), and the
silent misses (the work of the runner).

- **Unit.** One final admitted value, after the repair rounds, for each document, requested field
  and key. A keyed field such as a dose for adults and a dose for children has one unit for each
  key. A field with `multiple` true has one unit for each distinct value that groundgate admitted.
  So every admitted value is in the rate, also a wrong one that the label does not give.
- **Misses.** A labeled value with no matching admitted value has one of two causes, and the
  report counts them separately. If a right proposal for it went to review, it is a right value
  sent to review: the core's work. If no right proposal was admitted or sent to review, it is a
  silent miss: the runner's work. The miss rate of #269 is the sum of the two parts, so the report
  gives each part next to the sum. Misses are never in the admitted error rate.
- **Wrong.** The admitted value is not the field's value in the blind label, or the document does
  not state the field. For a number, the value is compared after its scale, with its unit and
  sign, and a right number under a wrong key or condition is wrong. For a string, the value is
  compared after whitespace normalisation and lower-casing (SPEC §4.4), so "Premium" for a label
  of "Basic" is wrong.
- **Not an escape.** A wrong value sent to review is a catch. A field with no value is a silent miss or a review, not an escape.
- **Excluded.** An item that the label marks as unclear in the document. The report gives the count.
- **For each field, each kind and each route.** A route is one pack, check or judge question that
  can change an outcome to admitted, on one kind of document, one field and one code. A total can
  hide one route that fails: 10,000 right admits from the core and 5 admits from a judge clear with
  2 errors give 2 in 10,005, but that route alone is 2 in 5. The same is true inside one judge
  question: many safe clears on one field can hide an unsafe field. So a route gets the status
  `measured` only from its own bound, for that kind, field and code. A bound over a wider group
  never qualifies a narrower route.
- **The bound.** A one-sided 95% upper bound that stays above zero when no error occurs. Errors in
  one document come together, so values in one document are not separate trials. A resample by
  document alone is not sufficient: with 0 errors, every resample has 0 errors, and the bound is
  0%. The report gives two bounds:
  - a bound on the admitted values that allows for clusters by document. Divide the number of
    values and the number of errors by a design effect of at least 1. The effective trials are the
    quotient for the values, rounded down. The effective errors are the quotient for the errors,
    rounded up, and never more than the effective trials. Then take the Clopper-Pearson upper
    bound. These rules make the bound larger, so it is approximate and conservative. If the
    effective trials are 0, the report gives no bound, and the slice cannot become `measured`. If
    the set has too few errors to estimate the design effect, the report uses a stated default;
  - the exact Clopper-Pearson upper bound on documents: the share of documents with at least one
    wrong admitted value. It needs no design effect.

  The report gives the number of documents and of kinds next to each bound. A status of
  `measured` (section 8) uses the larger of the two bounds.

**The set.** A set of several kinds of documents unlike the current sets, labeled blind. Part of it
is sealed: it is used only for a release measure, never for rule work. If we tune on it, it becomes
one more set that the rules were tuned on.

**The catch rate** (the share of wrong proposals that groundgate stops) stays a tool for
diagnosis and for the changed-value test. It is not a promise to users, because it depends on how
bad the model is.

## 11. Stability for 1.0

Each extension point is an interface that 1.0 must keep. I plan to promise only:

- the format of vocabulary packs, kind packs and checks;
- the recorded-judgment input;
- the status rules of section 8.

Readers, strategies and the router stay experimental after 1.0.

## 12. The plan by version

| Version | Content |
|---|---|
| 0.9 | as planned in #274. The set of #269 includes two or three kinds unlike the current sets. |
| 0.10 | the pack format, versioned and hashed into the receipt; the move of section 9; relation checks (5.3) |
| 0.11 | the tools of section 7: label kit, measure, operating point, audit sample, review answers to labels |
| 0.12 | readers: OCR with confidence as evidence, word-processor and spreadsheet files (DOCX, XLSX) (#7); the router |
| 1.0 | a stable pack format, a measured general core, a published bound for each kind |

## 13. Open questions

1. Where the packs live: in this repository, in a separate package, or both, with the app's own
   packs outside.
2. The fixed form of a relation: a sum and a difference only, or a small expression language.
3. How a kind pack and a vocabulary pack combine when both give a scale word.
4. How large a measure must be before a pack becomes `measured`: a number of documents, of kinds,
   or a bound.
5. Which kinds of documents the first varied set covers.

## 14. Decisions

- 2026-10-15: an extension that changes a decision is data, not code, and its digest is in the
  receipt. An extension adds knowledge and never removes a safety check (section 4).
- 2026-10-15: groundgate reports measured numbers for each field, not one reliability score for
  each value (sections 7 and 10).
