# Changelog

Versions follow [SemVer](https://semver.org). A change to how any candidate is decided is a new
spec version, and receipts name the spec version they were decided under.

## Unreleased

Spec 0.10, a draft. Receipts name `"groundgate": "0.10"` and every digest uses the
`groundgate/0.10:` prefix, so all hashes differ from 0.9.0.

- A decision whose unit check does not pass names the units that the evidence shows (#362). A
  decision with `UNIT_NOT_IN_EVIDENCE`, `UNIT_CITATION_INVALID` or `unit` in `missing` gets the
  member `evidence_units`: the token, the unit codes with a form next to it, the currency headers
  and statements that reach it, and its heading currency. "250 mg" on a field in `g` names `mg`,
  and `$m` under "presented in Australian dollars" names `AUD`. It is a report: no outcome and no
  code changes, groundgate converts no value, and other decisions do not have the member.
- A value in a dollar column under a statement of another currency was admitted in the wrong
  currency (#365). The statement "presented in Australian dollars" holds `dollars`, a suffix of
  `USD`, and the unit place rule of #249 read it as the unit of a `USD` value. A `$` next to the
  value, or a `$` at a unit place, did the same. Now a **heading conflict** (SPEC §4.3) sends such
  a value to review: the field's unit is a currency unit, and a heading unit that reaches the
  value does not allow it. Two statements that do not agree also give one. Then no unit form,
  unit place or unit item makes the unit present, so the decision lists `unit` in `missing`, or
  gets `UNIT_CITATION_INVALID` with a unit item. No decision moves to `admitted` or to
  `rejected`. The choice of the evidence and the outside path do not change. Vectors 109 to 115.
  Every bench check gives the same numbers.
- A scale word with a long s (U+017F), a dotted capital I (U+0130) or a dotless i (U+0131), such
  as "5 thouſand", made `admit` raise `KeyError` and give no receipt (#350). The lookup now folds
  the found word by the case rule of #356, so it always finds the listed word, and "5 thouſand"
  is a scale word that goes to review with `SCALE_WORD`.
- One case rule for every rule that matched with `re.I` (#356). SPEC §4 defines the fold of a
  letter: the long s (U+017F) folds to `s`, the dotless i (U+0131) and the dotted capital I (U+0130)
  to `i`, the Kelvin sign (U+212A) to `k`, and each other letter to its Unicode lowercase when that
  is one code point. Two letters match when their folds are the same. The scale words,
  abbreviations, qualifier and change words, sign words, per-unit words, heading names, keys,
  aliases and the L6 checks all use it. It is a strict subset of `re.I`: 45 pairs that `re.I` joined
  no longer match, such as `µ` and `μ`, and none of them is ASCII. The final `s` of a currency
  statement now matches `S` and `ſ` too, so "IN MILLIONS OF CANADIAN DOLLARS" is a statement. Two
  keys, or two aliases, of one field with the same fold, such as "State" and "ſtate", make the
  packet invalid. Every bench check gives the same numbers.
- The word lists of the text rules are data now, in the base vocabulary pack `en` 1.0.0
  (`src/groundgate/packs/en/1.0.0.json`, #333). SPEC §4.7 gives its digest. No decision and no
  receipt changes: a test shows that every moved pattern matches the same text as before, on
  every conformance string and every bench document text. The pack also holds the bare `000`
  currency scale of #313 and the currency names of a currency statement of #315, each name
  written out also in the singular.
- The loss words `loss`, `losses`, `deficit` and `deficits` move from the code to the built-in
  vocabulary pack `finance` 1.0.0 (#336). A schema names it with
  `{"id": "finance", "version": "1.0.0"}`, and the packet does not give it. SPEC §4.8 gives its
  digest. Without `finance`, a sign item that holds only a loss word fails with
  `SIGN_CITATION_INVALID`, and the decision goes to review. Brackets still give a sign. The bench
  schemas of the financial sets name `finance`, and every bench check gives the same numbers. The
  currency names of a currency statement stay in `en`: they can stop an admit, so a schema without
  `finance` must still read them. The `en` digest does not change.
  An app pack with the gain word "loss" is now invalid (L6) only when the packet also reads
  `finance`.
- An app can give its own vocabulary packs (#334). `groundgate.load_pack(path)` reads a pack
  file, `admit(..., packs=[...])` and `verify` take the pack objects, and the CLI takes
  `--pack FILE`. The schema names each pack in a new member `packs`. A pack only adds words to
  the base pack. The loader checks of SPEC §4.8 refuse a pack that changes a base word, adds to
  a list that cancels a flag, or exceeds a limit: 1 MiB as a file, 256 KiB as canonical JSON, a
  nesting depth of 8 and 2,000 entries in a list. The receipt gets a member `packs` after
  `references`, and each decision gets a member `packs` with the ids of the packs that it read.
  Both are `[]` for a packet with no pack, so every receipt digest changes, but no outcome or
  code changes. The base pack digest now reads the pack after defaults:
  `sha256:8ee2f5c367baa29969759e3ed3ec5acf39f412a8b4b6afbda6477c1cde7fdeae`.
- The extract runner and `feedback_message` take packs (#351). `extract`, `replay`,
  `RunResult.read` and `feedback_message` get a `packs` argument, and the runner keeps a
  `Schema` that was built with its packs. Before, a schema that named a pack failed in the runner
  with "is not given". The run record holds the digest of each pack through the schema, so a
  replay needs the same packs. No decision changes.
- An app can give kind packs and take field templates from them (#335). A kind pack gives field
  templates and names the vocabulary packs that it needs (SPEC §4.9). A schema field takes a
  template with `"template": "<pack id>/<field>"`. The template fills the members that the field
  does not give, and a member that the field gives wins. A `type` or `unit` that differs from the
  template's makes the packet invalid. The resolved schema keeps `template`, and its `packs`
  holds the digest of each pack, so a changed template changes `schema_sha256`. The receipt
  names a kind pack with the type `kind`, and a decision names the kind pack of its field's
  template. 4 vectors (88 to 91) and 18 invalid packets cover it. No outcome of a packet without
  a kind pack changes.
- Five built-in kind packs hold the field templates of the bench schemas (#337): `us-10k`,
  `us-government-reports`, `annual-reports`, `component-datasheets` and `benefit-summaries`, all
  1.0.0. The built-in vocabulary pack `electronics` 1.0.0 holds the unit forms of `C`, `V` and
  `mA`, and `component-datasheets` needs it. The three financial kinds need `finance`. A schema
  names a kind pack by id and version, and the packet does not give it. SPEC §4.8 lists each
  digest. Every route is `draft`. The bench sets keep their own schema files, so no bench number
  changes. A test writes each set's schema in template form, and it resolves to the same fields,
  member by member. No decision changes.
- `verify` finds the packs of a receipt by id, version and digest (#338). It looks for a
  built-in pack, then a given pack, then a file in the new folder option: `pack_dir` in Python,
  `--pack-dir DIR` on the command line. A pack that is not found, or a pack with another digest,
  is now one problem that names the id, the version and the digests, and `verify` checks nothing
  more. Before, a missing pack raised `PacketError`, and the CLI exited 2. Now it exits 1.
  `verify` reads the folder as untrusted: only the `.json` files directly in it, at most 256,
  each at most 1 MiB, with no link followed, and a file only when its computed digest is the
  digest in the receipt. A built-in version can now be retired: `admit` refuses it and `verify`
  still reads it. No version is retired. A test fails when a built-in pack file is not in the
  list of released digests or has another digest. The how-to
  [Keep pack files with receipts](docs/howto/keep-packs.md) shows a folder layout. A loader
  check error of `load_pack` now names the file. No decision changes.
- A candidate can cite up to 8 field items, such as a row label and a column header (#300).
  The field check passes when one of them passes. Two items of any other role stay
  `CANDIDATE_INVALID`.
- The extract runner's repair round keeps several field items too (#304). Before, a repair reply
  with two field items stopped with `protocol_failure`. A repair that may change `field` can now
  add, remove or replace up to 8 field items. Every other role stays one item.
- The extract runner's prompt says that a field item is the label before the value and must not
  hold the value (#318). When no field item passes because one holds the value or comes after
  it, the repair feedback names the cause, and the run record keeps it in `field_causes`.
- The extract runner can drop a rounded figure beside the exact figure (#319). The rule is
  opt-in: set `RunPolicy(drop_rounded=True)`. The default is off, and the runner then keeps both
  candidates, so admit gives `CONFLICTING_CANDIDATES` (#331). With the setting, it drops a
  candidate in a conflict only when a second candidate for the same field, key and unit rounds to
  it at the precision that the first one states, and the second one is admitted without it.
  "£17.3bn" beside 17,284 in millions keeps 17284000000. The record keeps the dropped candidate
  in a `rounding` line. Two figures that do not round to each other stay a conflict. The rule
  trusts the document: its author can choose the admitted value inside half of the rounded
  figure's precision. A number with more than 1000 digits or an exponent over 1000 is never
  dropped.
- Breaking: the extract run record is `groundgate-run/2` (#318, #319). The prompt changed, so
  every runner digest and prompt differs from 0.9.0. Replay of a `groundgate-run/1` record from
  0.9.0 fails with `runner version differs`, which names both versions.
- Currency scales (#301). `k`, `m` and `bn` count as a scale only directly next to a currency sign
  (`$`, `€`, `£`, `₹`). `€70,471m` is 70471000000. `£m`, `$bn` and `£'000` in a column header are
  a heading scale, and a scale item can cite them. `70 m`, `5m` and `£5 m` stay as written,
  because a bare `m` can be metres.
- `£000` is a currency scale of 10^3, as `£'000` is (#313). The `000` of a currency scale is no
  number token, so `£000` and `£'000` are never an amount of zero. `£000s`, `£0001`, `£000,000`
  and `£ 000` are no scale.
- A heading unit (#315). A unit item can cite a currency header such as `£m` or `US$000`, or a
  statement such as "presented in Australian dollars", when it reaches the value as a heading
  scale does. `$m` under an Australian dollar statement gives `AUD`, and `$m` alone gives only
  `USD`. When the heading units disagree, the unit item fails and the value goes to review. The
  currency names are a core list in §4.3 until the pack format (#320) is approved.
- Dash variants in keys and aliases (#317). A dash matches `-`, `‐`, `‑`, `‒` and `–`, so
  "Out–of–pocket limit" is a mention of "out-of-pocket limit". Between two letters a dash also
  matches across one line break, as in "out-of-\npocket". The minus sign and the em dash match
  only themselves. `groundgate schema check` folds the dashes too.
- Label cells (#316). On a line with a tab, a field item before the first tab, such as "What is
  the overall deductible?", passes for a value in the next cell, with at most 4 words before the
  value and no number, sentence end or alias between. Such an item no longer passes through the
  sentence rule for a value in a later cell or on a later line, so in "What is the overall
  deductible?\tNone\tThis plan pays after a $40 copay" the 40 goes to review.
- The PDF reader writes a ruled table of text cells one row on each line (#332). The rows and
  the cells come from the rules that the page draws, never from the words. The wrapped lines of
  one cell are joined with one space, so "What is the overall deductible?" and its answer are on
  one line with a tab between them. A tall cell keeps its column with an empty slot in the rows
  below it. An irregular grid, a word across a rule, or two cells that look like lists side by
  side keep the text as before. A table with numbers keeps its rows. This changes the reader
  text, and so the text digest, of each PDF with such a table. The recorded texts of the
  published sets do not change.
- The LangExtract adapter reads a list in `field_text` (#324). Each entry that holds text becomes
  one field item, up to 8. Before, the adapter skipped a list. A list for any other role now makes
  the candidate `CANDIDATE_INVALID`.
- Relations across fields (#321, #284). A schema can give `relations`: a total equals the sum of
  its parts, each part times a `factor`. A factor of `-1` subtracts a part, and `0.001` changes
  its unit, as from mg to g. Step 13 adds the values that passed, once for each key. If the sum is
  outside the allowance, each value of the relation gets `RELATION_FAILED`. The allowance is the
  `tolerance` plus half of one unit of the last written digit of each value, times its scale, so
  values in thousands can differ by 500 each. A relation that holds admits nothing. The receipt
  gets a `relations` member with the difference and the allowance of each relation that applied.
  A schema without relations keeps its digest and its receipt.
- The changed-value test (`bench/changed`, #322). It changes the 86 values with a base of the 89
  right values of `bench/afr` in seven ways (next row, next column, wrong scale, sign, digit swap,
  other field, rounded), with no model run, and decides 836 changed values. 15 get through: 9 of
  the 10 values from the next column, 3 of another field and 2 sign changes, and 1 from the next
  row. The relation of the balance sheet checks 252 changed values and stops all 252, because
  each change breaks the sum. It alone stops 11. Its cost: it sends 504 right values to review
  with them, because it cannot name the wrong value. RESULTS.md gives each count by check, with a
  95% bound that allows for clusters by document.

## 0.9.0 (2026-10-18)

Spec 0.9. Receipts name `"groundgate": "0.9"` and every digest uses the `groundgate/0.9:` prefix, so
all hashes differ from 0.8.0. 0.9 is about misses on the fields that an app asks for. I measured it
on a new set of 61 held-out documents, labeled blind before any model output. The miss rate is
still above 90%, so 0.9 does not meet that goal yet.

Breaking: two names change (#286).

- The reader is now `groundgate.read` (#289). `groundgate.extract.extract` is now
  `groundgate.read.read`, `ExtractError` is now `ReadError`, and the command `groundgate extract
  FILE` is now `groundgate read FILE`. The text does not change, so no published number changes.
- `groundgate.extract` is now the extraction loop (#281). `extract` takes a synchronous
  prompt-in, reply-out client. It builds bounded chunks and prompts, admits the candidates,
  repairs permitted evidence, and searches once for fields with no candidate. A repair can not
  change the field, unit, key, source or search region. The run record is a log of canonical JSON
  lines, each with the digest of the line before it, and `RunResult.read` replays a run with no
  client call. Limits on calls, prompt and reply size, candidates and admission history stop a
  run incomplete. The core stays dependency-free and makes no model call.

Spec 0.9 rules for table cells (#280):

- An explicit empty cell keeps its column. In `Cash\t\t$100` the blank first cell stays, so the
  value can not take the first year key.
- An ambiguous tab slot or a plain row can not supply a column key, and two blank lines keep a row
  away from an earlier header. A blank unit cell can not borrow a unit from an earlier column.
- A short table header uses its own row keys. A header with unknown, empty or decorated leading
  slots that would shift the column ordinals is refused.

The PDF reader (#279):

- A row in the top 36 points of the visible page is never a table row, and the walk above a table
  stops at it (#265). A running head with a page number or a year stays in ordinary text (#283).
- A blank cell keeps its column: a short row gets an empty slot for each missing cell (#266).
  Ambiguous geometry gives the plain row with no tabs, so the core sees no cell to cite.
- On the 23 held-out documents with blind layout labels (`bench/requested`), the annual reports
  keep 54 of 75 blank cells in their column and place 8 of 19 running heads right. The
  datasheets keep 25 of 105 blank cells and place 38 of 54 running heads right.

The measure (#269, #282, #294):

- `bench/requested` is a new set of 64 documents in three kinds: 20 component datasheets, 20
  health plan SBCs and 21 annual reports in the held-out part, and 3 development documents. Each
  kind has one fixed field list. `bench/score.py --requested` writes hits, escapes, reviews, silent
  misses, the miss rate and the admitted error rate with its upper bounds.
- With `gpt-6.1-sol` at medium effort, the released one-pass extraction with its feedback loop
  (baseline, on the 0.9 core) misses 187 of the 196 stated values (95.41%), with 9 right values admitted and 1
  escape. The 0.9 extraction loop misses 180 of 196 (91.84%), with 16 right values admitted, 6
  right absences and 0 escapes. It halves the silent misses (118 to 61) and sends more right values
  to review (69 to 119). Most of the gain is in the SBCs.
- The loop did not complete 18 of the 21 annual reports. Each stopped at a harness limit, with no
  transport error, and its present fields count as misses.

## 0.8.0 (2026-10-11)

Spec 0.8. Receipts name `"groundgate": "0.8"` and every digest uses the `groundgate/0.8:` prefix, so
all hashes differ from 0.7.0. 0.8 is about yield: more right values admitted, with no more escapes.
I measured each change on documents that it did not come from.

- The PDF extract writes a table as rows, with a tab between two cells, as the HTML path writes
  table cells (#230). Before, pdfminer gave each column of a table as its own text box, and the
  extract wrote the table column by column. I measured it on the 20 agency financial reports of
  `bench/afr` (`bench/afr/tabs`). With new runs on the new text under 0.8, `claude-haiku-5-5`
  admits 73 right values and 0 escapes (3 and 1 on the 0.7 text under 0.7), and `gpt-6-luna` 74
  and 0 (6 and 0). Two stronger models at high effort admit 82 (`claude-sonnet-5-5`) and 67
  (`gpt-6.1-sol`) right values with 0 escapes. The rules #249 and #250 came from this set, so
  these numbers include their effect on the documents they came from (#263). Two limits stay: a running head far above a table
  can join it as a column heading (#246), and a blank cell gets no empty cell, so the numbers
  after it move one column left (#247).
- A scale item that passes scales the value (#242). With a scale item that holds a scale word, a
  token with no scale word of its own matches only its value times the factor, and its negative.
  The number as written is no longer a derived value. The rule came from the escapes of the Haiku
  replay on the #230 text. Vector 26 pins it. On the new set `bench/acfr` (10 state ACFRs), it
  changes none of the 74 proposals.
- A value quote takes the first occurrence where the field item passes, and a form of the field's
  unit at a unit place of the value counts as the unit when the field item passes (#249). Both
  rules come from the diagnosis of #239. Vector 27 pins them. On the new set `bench/acfr2` (10
  more state ACFRs), `claude-haiku-5-5` goes from 5 to 7 right values admitted and `gpt-6-luna`
  stays at 2, with 0 escapes.
- A key in the title line reaches a table with one number column, across a label line (#250). No
  page break stands between them, and the value's line holds a tab before the value. Vector 28
  pins it. On `bench/acfr2` it changes no decision.
- A string value is at its first occurrence in its evidence span, not at the start of the span
  (#140). With a quote of two sentences, key scope read the first one. Vector 29 pins it. On the
  new set `bench/strings` (10 drug labels), 7 proposals have the case and the rule changes no
  decision: `claude-haiku-5-5` admits 14 right values and `gpt-6-luna` 10, with 0 escapes.
- `gg.extractor_schema` offers the evidence role `key` only on a field that has keys (#256). A key
  item on a field with no keys always fails. No decision changes, and a schema whose fields all
  have keys gives the same output as before. On `bench/acfr`, `claude-haiku-5-5` goes from 20 to
  29 right values admitted and `gpt-6-luna` from 0 to 12. On the documents of `bench/acfr2`,
  which #256 did not come from, they go from 10 to 23 and from 0 to 9. All four runs have 0
  escapes.

Five diagnoses changed no code:

- The cause of each field and key failure on `bench/afr` (`bench/afr/causes`, #239). It led to
  #249 and #250.
- The right values that the document states (#232). A second blind look changed 4 of the 21
  labels to wrong, so 17 values remain. No rule comes from them in 0.8, because they come from the
  v0.1 set and set 2.
- Why most `bench/acfr` proposals are not admitted (`bench/acfr/causes`, #244). The main cause is a
  key item on a field with no keys: 11 Haiku and 35 Luna proposals. It led to #256.
- Which rows the PDF extract puts in a table (`bench/pdfrows`, #246 and #247): 282 rows of 10 more
  state ACFRs, labeled blind. 19 of the 74 short rows have a blank cell before a number. 7 of the
  100 rows above a table are running heads, all in the top 0.027 of the page. A rule from either
  needs a new set.
- Cells with spaces in the column rule (#152). On the #230 text, no row label has only spaces
  before its number cells, so #152 is closed.

## 0.7.0 (2026-10-09)

Spec 0.7. Receipts name `"groundgate": "0.7"` and every digest uses the `groundgate/0.7:` prefix, so
all hashes differ from 0.6.1.

- A unit item must be at a unit place of the value (#164). A unit item that the unit at the number
  does not repeat passed when it came anywhere before the value, also from another row or column.
  Now it passes only on the value's line or before its brackets, in a caption line before the
  table, or in the value's column on an earlier line of the same table. A unit quote takes its
  last occurrence at a unit place. Vectors 25 and 25b pin the places. I measured the rule on a
  held-out set (`bench/afr`, #229): the principal statements of 20 FY2025 agency financial
  reports. Each extractor made 100 proposals, and the rule changes no outcome and no unit part.
  Under spec 0.6 and 0.7 alike, `claude-haiku-5-5` admits 3 right values and 1 escape, and
  `gpt-6-luna` admits 6 right values and 0 escapes.
- `groundgate schema check` prints a line for a field whose unit has no forms (#190).
- A schema integer bound outside ±(2^53-1) makes the schema invalid, with the field and the bound
  in the message (#192). `verify` checks a receipt for such an integer first, and names its path
  (#194).
- `gg.extractor_schema` has no `$schema` member, because the Claude CLI refuses a schema that names
  draft 2020-12 (#197).

Two measures changed no code:

- Outside knowledge (`bench/outside`, #132). Spec 0.6.1 still rejects 45 of the 229 items that were
  fixed before spec 0.5. A person labeled them: 1 is right from outside knowledge, 21 are right from
  the document, and 23 are wrong. A rule for outside evidence (#125) moved out of 0.7, and #232
  looks at the 21 values that the document states.
- Review answers against blind labels (`bench/status/review`, #176). On the 79 key items of the
  status calibration, all 79 answers on the review page match the blind labels. The same person
  gave both, so memory can explain the agreement. `groundgate-calibrate` still takes labels only
  from its blind label page, and #234 repeats the measure on items that the reviewer has not
  labeled.

## 0.6.1 (2026-10-09)

Spec 0.6, unchanged: receipts and digests are the same as in 0.6.0.

- `gg.feedback_message(decision, candidate, schema, text=None, references=None)` (#173) returns the
  text that tells the extractor what to change, or `None` when a new answer cannot change the
  decision. It holds the checks of the feedback how-to, which now calls it, and the five cases that
  the #163 review found.
- One feedback round on the held-out 10-K set (`bench/sec3`, #209). Each decision with a message
  goes back to the same model once, with the first prompt. `claude-haiku-5-5` goes from 15 to 35
  right values and `gpt-6-luna` from 27 to 45, with 0 escapes in both runs. 50 and 49 messages
  went to 12 and 15 documents. 78 and 66 decisions that were not admitted got no message, and 58
  and 51 of them have `KEY_NOT_AT_VALUE`. In most of these, the extractor cited a key item and the
  text puts another key at the value, so a person checks them.

## 0.6.0 (2026-10-08)

Spec 0.6. Receipts name `"groundgate": "0.6"` and every digest uses the `groundgate/0.6:` prefix, so
all hashes differ from 0.5.2. Each rule was measured alone on a held-out set (`bench/sec3`, #170,
#201): 20 10-K filings that no rule came from, and two extractors, `claude-haiku-5-5` and
`gpt-6-luna`, with `gg.extractor_schema(schema)` as their structured output. Under spec 0.5 they
admit 15 and 17 right values with 0 escapes. Every bench set that CI rescores in process gives the
same numbers.

- A unit item that repeats the unit passes (#145). When the field's unit is next to the number, a
  unit item that holds a form of it passes with no field item, even after the number. Alone, it
  admits 15 and 27 right values, with 0 escapes. The other part of #145, a scale quote in any case,
  admitted no more right values on either run, so it did not ship.
- `between` with up to six words before an `and` range (#159). In "between the ages of 18 and 65",
  65 now gets the `range` qualifier too. A word is a run of letters and combining marks. Alone, it
  costs 0 right values. One earlier vector changed: in `20-spec-text`, that 65 now goes to review
  with `QUALIFIED_VALUE`.
- A heading scale over a table (#162). "(in thousands)" on a line with no tab reaches the rows with
  tabs after it. A value there that is the number as written, with no scale item, goes to review
  with `PART_MISSING` and `scale` in `missing`. A field with the unit `%`, a number with its own
  scale word, and a table with spaces between its cells are not reached. Alone, it costs 0 right
  values. The rows are read once for each text, so a long table or a wide row stays linear.
- A field can have a `description` (#171): a non-blank string that changes no decision. It is part
  of the schema digest, and `gg.extractor_schema` puts it in the field's candidate shape.
- `groundgate schema check` now says that a unit item on a field with no `aliases` passes only for
  a unit next to the number.
- `bench/sec3`: the held-out set, the runs script and the measure, which decides each 0.6 rule
  alone. Spec 0.5 is decided on the 0.5.1 wheel.
- The conformance suite has 51 vectors and 38 invalid packets.
- Known gaps, for 0.7: a unit item can still cite a unit from another row (#164). A table with
  spaces between its cells gets no column rule and no heading scale (#152). The Claude CLI refuses
  the `$schema` member of `gg.extractor_schema` (#197). From 0.5.2: #190, #192 and #194.

## 0.5.2 (2026-10-08)

Spec 0.5, unchanged: every decision and receipt is the same as in 0.5.1.

- `groundgate schema check SCHEMA` (#168) prints each setting of a valid schema that makes a check
  fail every time, or pass for the wrong key or field: a `unit` or `keys` with no `aliases`, a key
  in an alias of its field, an alias on two fields or in a longer alias of another field, and a
  `minimum` above the `maximum`. It exits 1 on a finding, 0 on none and 2 on an invalid schema, so
  CI can run it. `admit` does not run it.
- `groundgate admit --docs D --candidates C --schema S --out R` (#169) decides a folder of
  documents. It writes each receipt and `summary.json`, with the outcomes and codes for each
  document and in total, and prints the totals. In Python, a loop over `gg.admit` does the same.
- A JSON integer outside [-(2^53-1), 2^53-1] in the candidates, references, judgments, policy or
  document id is now a `PacketError` that names the path of the value (#143). Before, the digest
  raised `ValueError` and no candidate got a decision.
- Known gaps, for 0.7: such an integer as a schema bound (#192) or in a receipt that `verify` reads
  (#194) still raises `ValueError`, and `schema check` does not yet find a unit code with no forms
  (#190).

## 0.5.1 (2026-10-08)

Spec 0.5, unchanged: every decision and receipt is the same as in 0.5.0.

- `gg.extractor_schema(schema)` and `groundgate schema`: a JSON Schema for a model's structured
  output, built from your schema (#148). Each field has its own candidate shape, with its unit and
  keys as constants, and items are quotes. It uses only the subset of JSON Schema that the strict
  structured-output modes take. Every candidate that it accepts passes steps 1, 2, 6 and 7.
- The guide has the instructions that go with it, and an example from a made-up 10-K table.
- Docs (#156, #161): a guide to writing a schema (`docs/schema.md`), five how-to guides
  (`docs/howto/`: your own model, feedback to the extractor, financial tables, outside sources, and
  review and receipts), and a map of the docs (`docs/README.md`). `tests/test_docs.py` runs every
  example on these pages.
- SPEC text (#158): the SPEC now states what the code and the vectors decide in 9 places, and
  makes 6 rules that could be read two ways exact, with no decision change. Vectors `20-spec-text` and `20b-spec-text-outside` reach each case, so there
  are 47 vectors.
- Known gap, for 0.6 (#162): in a table "(in thousands)", a value given unscaled with no scale
  item is admitted.

## 0.5.0 (2026-10-07)

Spec 0.5. Receipts name `"groundgate": "0.5"` and every digest uses the `groundgate/0.5:` prefix, so
all hashes differ from 0.4.0. One evidence object still works, as a list with one item. Every bench
set that CI rescores in process gives the same numbers. One earlier vector changed: in
`15-combined`, a value with no unit next to its number now goes to review with `PART_MISSING`,
where 0.4 rejected it with `UNIT_NOT_IN_EVIDENCE`.

- The evidence list (#141). `evidence` is a list of items, and each item names its source and its
  role. [docs/adr/0001-admit-by-policy.md](docs/adr/0001-admit-by-policy.md) records the decision,
  and [CONTEXT.md](CONTEXT.md) defines the terms.
  - Sources: `document` (the default), `reference` (text that the app supplies, by `ref`),
    `external` (a URL with the quote from it) and `knowledge` (the extractor's own statement).
  - Roles: `value` (the default), `sign`, `scale`, `unit`, `field` and `key`. Each role has its
    own check and its own reject code, such as `SCALE_CITATION_INVALID`.
  - A quote without offsets is found in its text. `QUOTE_NOT_FOUND` rejects a quote that is not
    there.
  - A cited sign or scale derives the value from the number (`VALUE_DERIVED`): "(1,234)" with a
    sign item is -1234, and "1,234" with "in thousands" is 1234000.
  - A part that the value needs and no item supports adds `PART_MISSING`, and the decision lists
    it in `missing`. The value goes to review, not to rejection.
  - A key item can put the key at the value in a table column (`KEY_CITED`). A field item is
    checked against the field's new `aliases`.
- Outside evidence. When the value has no value item in the document or a reference, the new
  `policy.sources` decides. An external URL on the allow-list, `"*"` or `"document-domain"`
  admits with `ADMITTED_BY_POLICY`. Other external quotes and knowledge go to review
  (`EVIDENCE_QUOTED`, `EVIDENCE_STATED`) or are rejected (`SOURCE_REJECTED`). The defaults are
  review.
- The receipt names the document source and the SHA-256 of each reference. Each decision lists
  its source and its checked parts. `admit`, `verify` and the CLI take `references` and
  `document_source`. The HTML report shows each part.
- The LangExtract adapter maps the attributes `sign_text`, `scale_text`, `unit_text`,
  `field_text` and `key_text` to role items, and `source_url` and `knowledge` to outside items.
- `gg.candidate_schema()` and `candidate.schema.json`: a JSON Schema for one candidate, for an
  extractor's output format (#147). Every candidate in the vectors that step 1 accepts passes it.
- 45 vectors and 35 invalid packets.
- The measure (#144, `bench/evidence/results.json`). On 20 new 10-K filings, spec 0.5 admits 26
  right values with 0 escapes, and spec 0.4 admits 23 with 1 escape. On the IRS filing-status
  set, both admit 28 right values with 0 escapes. Without the unit check, spec 0.5 admits 33 on
  the 10-K set. That rule and the case of scale quotes are open for 0.6 (#145).
- Not in 0.5. Keyed claims (#129) gave way to the key role of the evidence list. The label-line
  rule (#86) let a wrong key reach 2 more amounts on the status set, so it does not ship.

## 0.4.0 (2026-10-06)

Spec 0.4. Receipts name `"groundgate": "0.4"` and every digest uses the `groundgate/0.4:` prefix, so all
hashes differ from 0.3.0. With no `judge` in the policy, every decision is the 0.3 decision: all
earlier vectors and every bench set rescore unchanged.

- Recorded judgments (#116). A packet can carry `judgments`: answers that a judge gave about one
  candidate, recorded before the decision. The policy's new `judge` block names the one judge and
  model version whose answers apply, and their thresholds. groundgate never calls the judge.
  - `key`: on a candidate flagged `KEY_NOT_AT_VALUE`, the candidate's key at or above
    `clear.KEY_NOT_AT_VALUE` removes the flag and records `MODEL_CLEARED`; another key or none at
    that probability adds `MODEL_DOUBT`.
  - `field_match`: a probability below `doubt.field_match` adds `MODEL_DOUBT`.
  - A judgment never overturns a rejection and never admits a candidate with another flag. The
    receipt lists each judgment that applied, and `verify` takes the same judgments.
  - Vectors `18-judgments-key`, `18b-judgments-field`, `18c-judgments-both`, and 8 invalid
    packets.
- The judge block is experimental. Its one measure on real extractor output is the key clear on
  10-K filings (`bench/sec/results.json`, #120): of 51 right `KEY_NOT_AT_VALUE` flags on the test
  part, the built-in judge at 0.5 cleared 34 with 0 escapes, and 0.5 is also the threshold that
  the FDA labels gave (#100). The test part held only 2 wrong flags, so the escape side rests on
  little data. The field doubt caught no wrong value on the same filings. groundgate ships no
  thresholds: a threshold belongs to one model and one kind of document.
- `groundgate-calibrate` (#112, #115, #119) is a separate package in `calibrate/`. It measures a
  judge's thresholds on your own documents, writes the policy's `judge` block, and writes the
  recorded judgments for production. One judge is built in at this time. Other judges come in as
  plug-ins (entry point group `groundgate.judges`, #124). It is not on PyPI yet (#122).

## 0.3.0 (2026-10-05)

Spec 0.3. Receipts name `"groundgate": "0.3"` and every digest uses the `groundgate/0.3:` prefix,
so all hashes differ from 0.2.0. Each rule that changes how real text reads was measured on a new
set of documents that no rule was written from, labeled blind before scoring: the pattern, dots,
caps, India, keys and tables sets in `bench/`. The digit rule (#94) takes values away only, and
every set rescores unchanged under it. Every number below comes from the `results.json` of its
set.

- Set 2 is rescored on the released 0.2.0 wheel, the way the v0.1 set is rescored on 0.1.0, so
  its published numbers stay spec 0.2's.
- Changes (#51): a change word may stand up to six words before `from`, and every form of it
  counts. "reducing the annual fee from $1,200 to $950" and "the limit increases from $70,000 to
  $72,000" are now changes, so the new value is no longer flagged as a range end. The words
  between must start with a determiner and hold no digit, punctuation, preposition or range word,
  so "increased body weight from 20 to 40 kg" stays a range. Vector `07e-change-at-a-distance`.
- Sentence ends (#63): for the qualifier window, the dot of a listed abbreviation such as `Rs.`,
  `approx.`, `p.m.` or `U.S.` no longer ends a sentence when a lowercase letter, a digit or a
  currency sign follows. "up to Rs. 50,000" is now qualified, and in "from 6 p.m. to 8 p.m." 8 is a
  range end. A wider qualifier window can only add a flag. Key scope and the unit search still end
  at every such dot, so a join never lets a key or unit of one sentence reach a value in the next.
  `approx` joins the `approx` qualifiers, so "approx. 5 mg" is flagged. Vector
  `07f-abbreviation-dots`. Measured on 116 abbreviation dots in documents no rule was written from
  (`bench/dots`): of the 107 where the sentence goes on, spec 0.2 cuts all 107 and 0.3, with the
  #77 rule below, cuts 10. 0.3 joins none of the 9 real sentence ends.
- Sentence ends (#77): for the qualifier window, the dot of `U.S.` no longer ends a sentence, and
  the dot of `No.` or `Nos.` no longer ends one before a code such as `DEA-1086`. A blank line
  still ends the sentence. Vector `07g-us-and-number-dots`, and `07f-abbreviation-dots` a5 is now
  qualified. Measured on 105 such dots in documents no rule was written from (`bench/caps`): of
  the 102 where the sentence goes on, 0.3 before this rule cut all 102 and now cuts 3, and 0.3
  joins none of the 3 real sentence ends.
- Blank lines (#63): a blank line may hold a carriage return, so `\r\n\r\n` ends a sentence
  too.
- Keys (#52): when a value's sentence mentions no key, the key of the nearest earlier mention no
  longer reaches it past a label line: a short line of its own between blank lines, such as
  "Treatment of DVT and PE:" or "Adults". The value is at no key, so a keyed candidate goes to
  review. A heading that is a key mention still reaches past its blank line. Vector
  `17c-label-lines`. Measured on 100 doses in 17 FDA labels no rule was written from
  (`bench/keys`), 93 of them labeled: the rule stops a wrong key at as many doses as it sends a
  right key to review. Half of the right keys it loses are a bullet on a line of its own (#86).
  With the table rule below, a wrong key reaches 4 of those doses, down from 28 with spec 0.2, and
  every right key reaches 38, down from 58.
- Keys (#87): a sentence with 3 or more line breaks that mentions 2 or more keys is a table
  sentence. A value in it is at the keys mentioned on its own line, or at no key when the line
  mentions none, so a key swapped within a flattened table goes to review. Before, every value
  in such a table was at every key it mentioned. Vector `17d-table-sentences`, and in
  `17b-keyed-tables` 40 mg on the hypertension row is no longer at heart failure. Measured on all 62
  doses in such tables in the FDA labels of the Part D ranking that no rule was written from
  (`bench/tables`): a wrong key reaches 0 of them, down from 60 with spec 0.2, and every right key
  reaches 3, down from 55. In these tables a value's line rarely names its condition, so the right
  keys go to review with the wrong ones.
- Digits (#94): in the number rules a digit is an ASCII digit, 0 to 9. Python's `\d` matched
  every Unicode digit, so `२०००` was read as 2000, and an implementation in a language whose `\d`
  is ASCII decided the same document differently. A number in other digits now has no token, nor
  do ASCII digits next to it, and a candidate value in them is invalid. Where a digit only stops a
  reading or adds a flag, as in a per-unit, any Unicode digit still counts, so other digits can
  block a value but never make one. Vector `03c-ascii-digits`. The 322 benchmark documents
  hold no other digits, so every set rescores unchanged.
- Numbers (#59): a number grouped the Indian way, the last three digits and then pairs, has its
  value: `2,00,000` is 200000 and `1,00,00,000` is 10000000, in the document and in a candidate's
  `value`. A mix of the two groupings, such as `1,23,456,789`, still has none. Vector
  `03b-indian-grouping`. Measured on the India set (#76): 101 tokens with a comma in 41 SEBI
  circulars, labeled before scoring. Spec 0.2 rejects 14 of the 88 tokens that are one number,
  and spec 0.3 rejects 0. Both specs give a value to 1 of the 13 tokens that are not one
  number, the same token.

## 0.2.0 (2026-10-03)

Spec 0.2. Receipts name `"groundgate": "0.2"` and every digest uses the `groundgate/0.2:`
prefix, so all hashes differ from 0.1.0. The rules came from the v0.1 escapes, so they were
measured on a second set of 101 documents picked before anyone read them (`bench/set2`). Pooled
over 14 runs on the 74 documents checked in full, wrong extractions admitted without review fell
from 30.7% (253/823) under spec 0.1 to 8.8% (72/823), correct extractions rejected from 11.3%
(690/6080) to 0.5% (28/6080), and extractions sent to a person rose from 28.2% (1950/6903) to
39.6% (2730/6903).

- `verify` reports a receipt decided under another spec version as one problem, instead of a
  list of hash mismatches.
- Qualifiers (#5): where two overlap, only the longer applies, so "no more than" is `le` and no
  longer also `gt`. In 0.1 it flagged `le` fields on the spec's own `le` phrase. A negation
  directly before a `gt`, `lt`, `ge` or `le` qualifier inverts it: "must not be more than" and
  "may not exceed" are `le`, "cannot be less than" is `ge`. `exceed` joins `gt`, so an `eq` field
  is now flagged on "do not exceed". Vector `07b-negated-qualifiers`.
- Ranges (#14): one unit or scale word between the first number and `to`, `through`, `thru` or
  `and` no longer hides the upper end. In 0.1, "30 mg to 45 mg" flagged 30 as a range but
  admitted 45. Vector `07c-range-unit-words`.
- Changes (#4): after a change word such as "increased" or "reduced", "from X to Y" is a change.
  Y is the new value and no longer flagged as a range end; X keeps the range flag, so a field
  that takes the old value still goes to review. "run from 7 to 8 hours" is still a range.
  Vector `07d-change-not-range`.
- Scale words (#6): a number followed by a scale word also has its scaled value, so 1000000
  matches "$1 million" and is admitted with no flag. In 0.1 it was rejected. A candidate that
  gives the written value (1) keeps `SCALE_WORD`. Vector `08b-scaled-values`.
- Per-units (#3): the first suffix after a number decides its unit, and a suffix followed by a
  body-size or volume denominator (`/kg`, `/m2`, `per kilogram`, `/5 mL`) is not that unit. In
  0.1, "1.6 mcg/kg/day" passed as 1.6 mcg, and "10 mg/kg (maximum 500 mg)" passed as 10 mg
  through the later "500 mg". "200 mg/day" is still mg. A weight-based dose needs its own unit
  code, such as `mg/kg`. Vector `04b-per-units`.
- First unit (#26): the first suffix of any unit in the table, built-in or the schema's, decides
  a number's unit. In 0.1, "10 mcg (maximum 500 mg)" passed as 10 mg, because the `mg` of 500
  was within 24 code points, and "2 L in 4 hours" passed as 2 hours. "25 or 50 mg" still gives 25
  its mg. Vector `04c-first-unit`.
- Keyed fields (#2): a field can list `keys`, the conditions its values belong to (such as a
  drug's indications), and each candidate names one as `key`. A missing or unknown key rejects
  `KEY_INVALID`, a new step 7, so evidence checks are now steps 8 to 11. A key is at a value when
  the value's sentence mentions it, or, when the sentence mentions none, when it is the nearest
  key mentioned before the value, such as a heading. Otherwise the new flag `KEY_NOT_AT_VALUE`
  applies. `CONFLICTING_CANDIDATES` works per field and key, decisions echo the `key`, and the
  LangExtract adapter passes a `key` attribute through. In 0.1, a dose that differs by
  indication was one field, where the doses conflicted, or one field per indication, where
  nothing checked the indication. Vectors `17-keyed-fields` and `17b-keyed-tables`.
- `extract` (#30): the same PDF always gives the same text. pdfminer broke ties between equally
  distant text boxes by memory address, so a chart on one IRS page came out in two orders. All 90
  PDF texts in both benchmark sets are unchanged.
- A second benchmark set (#1): 101 public-domain FDA labels, NTSB reports, IRS publications and
  Federal Register rules, picked by rules frozen before anyone read them, with person-checked
  gold and the same seven models. `bench/score.py --set bench/set2` decides every candidate under
  spec 0.2 and, through `bench/decide.py`, under the released 0.1.0 wheel, side by side. Tables
  and every escape are in `bench/set2/RESULTS.md`.

## 0.1.0 (2026-09-29)

First release. Implements spec v0.1.

- `admit` and `verify`: deterministic admission with ten rejection codes, five flags, required
  field coverage and re-anchoring, and receipts hashed over RFC 8785 canonical JSON.
- `groundgate extract`: PDF (with `[pdf]`), HTML, XML and text to NFC text, with page and word
  boxes for PDFs. Text a reader can't see is dropped, and superscripts are marked.
- A LangExtract adapter that checks each extraction's value and unit at the place LangExtract
  aligned it.
- `groundgate report`: a self-contained HTML review page that re-derives the receipt before it
  renders.
- 16 conformance vectors and 6 invalid packets, language-neutral, so another implementation can
  prove it agrees.
- A benchmark on 30 public-domain FDA, NTSB and IRS documents with person-checked gold and seven
  models: [bench/RESULTS.md](https://github.com/mohanraj00/groundgate/blob/main/bench/RESULTS.md).
