# Packs: the format, and the move of the current knowledge

Status: design for approval, issue #320. Nothing in this file is built, and it changes no
decision. The maintainer approves this note before any pack code. It answers the open points of
[extensions.md](extensions.md) for vocabulary packs (§5.1) and kind packs (§5.2), and it plans
the move of §9. The last section lists the code issues for 0.10.

## 1. The answers in short

| Question (#320) | My answer | Section |
|---|---|---|
| The format of a vocabulary pack | A closed JSON object with a format number, an id, a version, a status table and word lists that add to the base pack `en`. | 4 |
| The format of a kind pack | The same envelope, with field templates, the vocabulary packs that it needs, and relations (#321). It holds no reading words. | 5 |
| The version and the digest | A pack version never changes after release. The digest is over the canonical JSON of the pack, with a prefix of the pack format, not of the spec version. | 6 |
| Where the digest goes in the receipt | A new receipt member `packs`: the id, type, version and digest of each pack that applied, except the base pack. SPEC gives the digest of the base pack. | 6 |
| Where packs live (§13, question 1) | Built-in packs are data files in this repository and in the wheel. The app's own packs are files that the app gives. No separate package in 0.10. | 7 |
| How a kind pack and a vocabulary pack combine (§13, question 3) | A kind pack names vocabulary packs. Every vocabulary pack adds to the base. A word that two packs give two meanings makes the packet invalid. | 8 |
| When a pack becomes `measured` (§13, question 4) | A route becomes `measured`, not a pack: a bound from blind labels on at least 60 held-out documents of its kind, at or below the limit in its status row. | 9 |
| The move of §9 | Four stages. First every core list moves into the base pack `en`, with every receipt byte for byte the same. Then the loader, kind packs and the bench templates come with no decision change. Last, the loss words move into `finance`: the one change, and it goes toward review. | 10 |
| How `verify` finds the pack of an old receipt | By the id, version and digest in the receipt: built-in versions stay in the wheel, and the app gives its own pack files or a folder of them. | 11 |
| What a pack cannot do (§6) | Thirteen checks that the loader runs. Each limit of §6 maps to one or more of them. | 12 |

## 2. Terms

- A **pack** is a JSON object that groundgate loads before the decision. It is data, not code
  (extensions.md, rule 1).
- A **vocabulary pack** gives words that the reading rules of SPEC §4 read: scale words, unit
  forms, qualifier words and other lists.
- A **kind pack** gives knowledge about one kind of document: field templates, relations between
  fields, and the vocabulary packs that the kind needs.
- The **base pack** is the vocabulary pack `en`. It holds every word list that is in the core
  code today. It always applies, and no pack can remove a word from it.
- A **guard word** is a word whose reading can flag or reject a value, for example a qualifier or
  a scale word. A **reading word** only helps to admit a value, for example a loss word that
  makes a sign item pass.
- A **route** is one pack, check or judge question, on one kind of document, one field and one
  code (extensions.md, §8 and §10).

## 3. The rules that the format follows

The two rules of extensions.md §4 hold. I add four rules that make them checkable:

1. **The base always applies.** A packet with no pack reads the base pack `en`. A packet with
   packs reads the base pack and its packs.
2. **A pack only adds.** The format has no member that removes, replaces or turns off a word, a
   check or a limit. Every list in a pack is a union with the same list of the base pack.
3. **No silent choice.** If two packs give one word two meanings, the packet is invalid. The
   loader never picks one.
4. **The schema decides.** A field that the app writes wins over a field template, as
   extensions.md §5.2 says. A conflict on a type or a unit makes the packet invalid.

Rules 1 and 2 are the reason why a guard word stays in the base pack. If a guard word leaves the base,
a packet with no pack loses a flag. For example, "lakh" is Indian English, but without it,
"5 lakh" with the candidate value 5 gets no `SCALE_WORD` flag and the core admits a value
100,000 times too small. So the move of section 10 takes a word out of the base only when the word only
helps to admit. Without it, a value goes to review, as a strict gate does with an unfamiliar
document.

## 4. The vocabulary pack

A vocabulary pack is one JSON object:

```json
{"groundgate_pack": 1,
 "type": "vocabulary",
 "id": "finance",
 "version": "1.0.0",
 "description": "Words of financial statements in English.",
 "status": [],
 "sign": {"loss": ["loss", "losses", "deficit", "deficits"]}}
```

| Member | Meaning |
|---|---|
| `groundgate_pack` | The pack format. It is `1` in 0.10. A loader refuses any other number. |
| `type` | `vocabulary` or `kind`. |
| `id` | Lowercase letters, digits and single `-` between them, at most 64 characters. Built-in ids are reserved. The id of the app's own pack ends with `-x-` and a name, for example `finance-x-myapp`. |
| `version` | `MAJOR.MINOR.PATCH`, each a non-negative integer with no leading zero. Each change of content gives a new version. |
| `description` | Optional text. It is in the digest and has no effect on a decision. |
| `status` | The status table of extensions.md §8, one row for each route that the pack qualifies (section 9). It is empty in every 0.10 pack. |
| the lists | The word lists below. Each one is optional, and an absent list is empty. |

Format 1 has these lists. The base pack `en` gives all of them. Another vocabulary pack can give
only the lists in the last column marked "yes".

| List | What the core reads it for | Another pack can add to it |
|---|---|---|
| `scale.words` | scale words and their power of ten (SPEC §4.1) | yes |
| `scale.suffixes` | scale suffixes after a currency sign, as in `£5m` (§4.1) | yes |
| `scale.currency` | the forms after a currency sign in a currency scale, as in `£'000` (§4.1) | yes |
| `currency_signs` | the currency signs (§4.1, §4.2) | yes |
| `units` | unit codes with their prefix and suffix forms (§4.3) | yes |
| `per_units` | the body-size and volume units after `/` or `per` (§4.3) | yes |
| `qualifiers.before`, `qualifiers.after` | qualifier words for each comparator (§4.2) | yes |
| `qualifiers.negations` | the words that invert a qualifier (§4.2) | no |
| `ranges.connectors` | `to`, `through`, `thru`, `-` and `–` (§4.2) | yes |
| `ranges.pair` | `between` and `and` (§4.2) | no |
| `changes.words`, `changes.determiners` | change words and determiners (§4.2) | no |
| `changes.stop_words` | the words that end a change phrase (§4.2) | yes |
| `sentence.abbreviations` | the dots that do not end a sentence for the qualifier window (§4.2) | yes |
| `sentence.join_always`, `sentence.join_before_code` | `u.s.`, `no.` and `nos.` (§4.2) | no |
| `sign.loss` | loss words (§4.6) | yes |
| `sign.gain`, `sign.negations` | gain words, and `no`, `not` and `without` before a loss word (§4.6) | yes |
| `null_literals` | the values that step 3 rejects (§3) | yes |
| `heading_units` | the words of a currency statement, after #315 (section 13) | yes |

A list that another pack cannot add to has words that cancel a flag: a negation inverts a
comparator, and a change word ends a range reading. A wrong entry there removes a flag for every
field. These lists stay with the base pack in format 1. The locale stages of
[locale-packs.md](locale-packs.md) can open them later, each with vectors and a measure.

Each list is a list of words, or an object from a word to a number (`scale.*`) or to forms
(`units`). A word is plain text, never a pattern. The core escapes it and matches it with the
fixed rules of SPEC §4: whole words, the same case rules, the same windows.

## 5. The kind pack

```json
{"groundgate_pack": 1,
 "type": "kind",
 "id": "us-10k",
 "version": "1.0.0",
 "description": "Annual reports on Form 10-K of U.S. public companies.",
 "needs": [{"id": "finance", "version": "1.0.0"}],
 "fields": {"revenue": {"type": "number", "unit": "USD",
                        "aliases": ["revenue", "revenues", "total revenue", "net sales"]},
            "net_income": {"type": "number", "unit": "USD",
                           "aliases": ["net income", "net loss", "net income (loss)"]}},
 "relations": [],
 "status": []}
```

| Member | Meaning |
|---|---|
| `needs` | The vocabulary packs that the kind needs, by id and version. A kind pack cannot name a kind pack, so there is no loop. |
| `fields` | Field templates. A template can hold only `type`, `unit`, `comparator`, `aliases` and `description`, with the rules of SPEC §2.3. |
| `relations` | Relations between the template fields. #321 defines their form (section 13). |
| `status` | As in a vocabulary pack. |

A template holds no `keys`, `required`, `multiple`, `minimum` or `maximum`. These depend on the
app and on the document: the keys of a 10-K are its years, and the app decides what is required.
A template can leave out `unit`. Then the app's schema gives the unit, for example the reporting
currency of an annual report from outside the U.S.

A kind pack holds no reading words. A unit form, a scale word or a loss word goes in a vocabulary
pack, and the kind pack names that pack in `needs`. So one word has one home, and question 3 of
extensions.md §13 has a simple answer (section 8).

### 5.1 How the app takes a template

The schema gets two optional members: `packs` at the top, and `template` in a field.

```json
{"packs": [{"id": "us-10k", "version": "1.0.0"}],
 "fields": {"revenue": {"template": "us-10k/revenue", "keys": ["2025", "2024"],
                        "multiple": true}}}
```

- `packs` names each kind pack and vocabulary pack that the schema uses, by `id` and `version`.
  An entry can also give `sha256`. Then the loaded pack must have that digest, or the packet is
  invalid. This pin is optional.
- `template` is `<pack id>/<field name>`, and the pack must be in `packs`.
- The template fills each member that the field does not give. A member that the field gives
  wins, also `aliases`: the pack does not add to the app's aliases.
- If the field gives a `type` or a `unit` that differs from the template's, the packet is invalid.
  An absent `type` takes the template's type before the default `number` applies.

The **resolved schema** is the schema after this step and after the defaults. It keeps `template`
in each field, and its `packs` entries carry the digest of each pack. `schema_sha256` is the
digest of the resolved schema, so a changed pack changes it (extensions.md, rule 1).

## 6. Version, digest and the receipt

**Version.** A built-in pack version never changes after a release. A change of a word, a
template or a status row is a new version. A test in CI compares each released pack file with a
list of digests in the package, so a changed released file fails CI. The meaning of MAJOR and
MINOR for packs is part of the stable format of 1.0 (extensions.md §11). In 0.10 the version is
a name only.

**Digest.** The digest of a pack is

```text
pack_sha256 = "sha256:" + hex(SHA-256("groundgate-pack/1:" + type + "\0" + JCS(pack)))
```

where `pack` is the pack object after defaults (each absent list empty, each absent text
empty), and JCS is SPEC §6. The prefix names the pack format, not the spec version. So one pack
file has one digest under spec 0.10 and spec 0.11, and the app's pin stays valid after an
upgrade. The receipt digest still binds the spec version.

**The receipt.** The receipt gets one new member after `references`:

```json
{"packs": [{"id": "finance", "type": "vocabulary", "version": "1.0.0", "sha256": "sha256:..."},
           {"id": "us-10k", "type": "kind", "version": "1.0.0", "sha256": "sha256:..."}]}
```

It lists each pack that applied, sorted by `id`: the packs of the schema and the packs in their
`needs`. It does not list the base pack. SPEC gives the digest of `en` for each spec version,
and a conformance test checks that the implementation loads a base pack with that digest. So the
spec version names the base. In stage 1 of section 10.3, a packet with no pack keeps its receipt
byte for byte. From stage 2, its receipt holds `"packs": []`.

The digest of each pack is in two places: in `packs`, and in `schema_sha256` through the
resolved schema. The policy does not change. The document digest and the candidate digests do
not change.

Rule 2 of extensions.md asks that the receipt names the pack that each check used. In 0.10 the
receipt names the packs, and the resolved schema names the template of each field. So a field
from a template is known for each decision. A decision does not yet say which vocabulary word
helped it. That needs the route measure of 0.11, and I add it to a decision there, with its own
vectors.

## 7. Where packs live

- **Built-in packs** are JSON files in this repository, under `src/groundgate/packs/<id>/`, one
  file for each version, for example `src/groundgate/packs/en/1.0.0.json`. They ship in the
  wheel as package data and load with the standard library. The core stays dependency-free.
- **The format rules** go into SPEC.md as a new section, with the base pack as a normative file.
  Another implementation loads the same files.
- **The app's own packs** are files that the app keeps. The app gives them to `admit` as pack
  objects (`admit(..., packs=[...])`) or to the CLI as `--pack FILE`. `groundgate.load_pack(path)`
  reads a file and runs the checks of section 12.

I do not make a separate package in 0.10. A pack changes outcomes, so a receipt must name its
exact bytes. A separate package with its own release cycle adds a matrix of versions, and no
user needs it yet. The entry points of [hybrid-decisions.md](hybrid-decisions.md) §7 wait too.
If the built-in packs grow faster than the core, I move them to their own package and keep the
digests.

## 8. How packs combine

1. The loader takes the base pack `en`.
2. It adds each vocabulary pack in the schema's `packs`, and each pack in the `needs` of each
   kind pack there. A pack named twice with one version loads once. One id with two versions makes
   the packet invalid.
3. Each list is the union of the same list in all loaded vocabulary packs. A word that is in two
   packs with one meaning is one entry.
4. A conflict after the union makes the packet invalid (check L6, section 12). For example, a
   scale word with two powers of ten, or one unit form under two unit codes.
5. The schema's `units` still extends and overrides the unit table, as SPEC §2.3 says. It is the
   app's own input. A pack cannot override a unit; it can only add forms.
6. The core orders each list longest first, then by code point. So the order of the packs never
   changes a match.

So when a kind pack and a vocabulary pack both seem to give a scale word, only the vocabulary
pack can give it. When two vocabulary packs give one scale word with one power, the word is one
entry. With two powers, there is no receipt.

## 9. When a route becomes `measured`

A status belongs to a route, not to a pack (extensions.md §8). A status row is:

```json
{"kind": "us-10k", "field": "revenue", "code": "FIELD_CITATION_INVALID", "status": "measured",
 "documents": 60, "bound": "0.0487", "limit": "0.05", "results": "bench/example/results.json"}
```

This row is an example, not a measure: its bound is the bound with no error in 60 documents.

I propose that a route becomes `measured` only when all of these hold:

1. The bound comes from blind labels or from the audit sample of whole documents (extensions.md
   §10). Review answers never count.
2. Nobody used the documents to write the route.
3. At least 60 documents of that kind are in the measure. With no error in 60 documents, the
   exact one-sided 95% bound on documents is 4.87%. With 58 documents or fewer, a result with no
   error cannot pass a limit of 5%. I round the minimum up to 60.
4. The larger of the two bounds of extensions.md §10 is at or below the `limit` of the row, and
   no `limit` is above 0.05.
5. The row names the `results.json` that gives the bound. A test in CI checks the bound against
   that file, as AGENTS.md requires of every benchmark number.

A route is for one kind of document, so the number of kinds does not qualify a route. The 1.0
claim of at least three kinds (#277) is a claim about the core and the set, not about one route.

Only a built-in pack can have a `measured` row. The app's own pack has only `draft` rows, the
same rule as in locale-packs.md §4. `retired` is not a row: it marks a whole built-in version in
the package's list of digests. `admit` refuses a retired version, and `verify` still loads it.

In 0.10 no pack has a `measured` row. The format holds the table now, so that 0.11 can add rows
in a new pack version when the tools of extensions.md §7 give the bounds. The base pack has no
status table: its routes are the routes of the core, and the core's own measures apply to them.

## 10. The move of the current knowledge

### 10.1 What leaves the code

Every list below leaves the core code. The column "Goes to" is its new home. `text.py` is
`src/groundgate/text.py`, and `admit.py` is `src/groundgate/admit.py`.

| List | File and symbol | Goes to | Why there |
|---|---|---|---|
| qualifier words before the value | `text.py` `_BEFORE` | `en` `qualifiers.before` | guard |
| qualifier words after the value | `text.py` `_AFTER` | `en` `qualifiers.after` | guard |
| negations of a qualifier | `text.py` `_NEGATION_END` | `en` `qualifiers.negations` | can remove a flag; base only |
| range connectors | `text.py` `_RANGE_NEXT`, `_RANGE_PREV`, `_UNIT_WORD`, `_strip_unit_suffix` | `en` `ranges.connectors` | guard |
| `between` and `and` | `text.py` `_AND_NEXT`, `_AND_PREV`, `_BETWEEN_END`, `_BETWEEN` | `en` `ranges.pair` | base only |
| change words | `text.py` `_CHANGE` | `en` `changes.words` | can remove a flag; base only |
| determiners | `text.py` `_DETERMINER` | `en` `changes.determiners` | can remove a flag; base only |
| words that end a change phrase | `text.py` `_NOT_BETWEEN` | `en` `changes.stop_words` | guard |
| abbreviations | `text.py` `_ABBREVIATIONS` | `en` `sentence.abbreviations` | guard: a wider window only adds a flag |
| `u.s.`, `no.`, `nos.` | `text.py` `_ends_sentence` | `en` `sentence.join_*` | base only |
| currency signs | `text.py` `_CONTINUES` | `en` `currency_signs` | guard and reading |
| scale words | `text.py` `_SCALE`, `_SCALE_EXP`, `_ITEM_SCALE`, `_IN_SCALE` | `en` `scale.words` | guard: `SCALE_WORD`, the heading scale |
| scale suffixes | `text.py` `_SUFFIX_EXP`, `_SCALE_SUFFIX` | `en` `scale.suffixes` | guard: `SCALE_WORD` |
| currency scales | `text.py` `_CURRENCY_FORM`, `_CURRENCY_SCALE` | `en` `scale.currency` | guard: the heading scale |
| the unit table | `text.py` `_CURRENCY`, `_SELF`, `_TIME`, `builtin_units` | `en` `units` | guard: the first suffix decides |
| per-unit denominators | `text.py` `_PER_UNIT` | `en` `per_units` | guard |
| gain words | `text.py` `_GAIN` | `en` `sign.gain` | guard |
| negations before a loss word | `text.py` `_NEGATION` | `en` `sign.negations` | guard |
| null literals | `admit.py` `NULL_LITERALS` | `en` `null_literals` | guard |
| loss words | `text.py` `_LOSS` | `finance` `sign.loss` | reading only |
| currency statement words | the list that #315 adds | `finance` `heading_units` | reading only (section 13) |
| aliases of the 10-K sets | `bench/sec2/schema.json`, `bench/sec3/schema.json` | kind `us-10k` | field templates |
| aliases of the government report sets | `bench/afr/schema.json`, `bench/acfr/schema.json`, `bench/acfr2/schema.json` | kind `us-government-reports` | field templates |
| the annual report request | `bench/requested/manifest.json` `schemas.annual` | kind `annual-reports` | field templates, no unit |
| the datasheet request | `bench/requested/manifest.json` `schemas.component` | kind `component-datasheets`, and its `units` in vocabulary `electronics` | field templates |
| the benefit summary request | `bench/requested/manifest.json` `schemas.sbc` | kind `benefit-summaries` | field templates |

The time units are in the base pack as data, each with its code, its singular and
`-<singular>`. The pack writes each form out, so the core has no rule that makes forms.

The 0.10 runs of `bench/requested2` use the same request schemas, with a reporting currency for
each annual report. A template with no unit lets each document schema give its currency without
a conflict.

### 10.2 What stays in the code

These are rules and limits, not lists. A pack that changes them changes a check, which §6 forbids:

- the number token and its groupings: `text.py` `_TOKEN` and `_VALID` (number formats go to the
  locale stage 2, not to 0.10);
- the sentence ends, the blank line and the key break: `text.py` `_SENTENCE_END`,
  `_BLANK_LINE`, `_KEY_BREAK`, and the code test before `no.`, `_CODE`;
- the windows and reaches: `text.py` `_WINDOW` (40), `_LOSS_REACH` (4), `_LABEL_MAX_WORDS`
  (12), the reach of 2 whitespace code points in `_SCALE`, the 4-character gap and the six-word
  limit of a range, and the unit word of at most 12 characters;
- `admit.py` `MAX_FIELD_ITEMS` (8) and `_SCALES`, the powers of ten that a missing scale tries;
- the codes and their orders in `codes.py` and `admit.py`.

### 10.3 How every vector and every bench outcome stays the same

**Stage 1: the base pack (no decision change).** The core builds every pattern from `en` 1.0.0.
The proof has five parts:

1. For one PR, a test keeps the old patterns. It compares their matches with the matches of the
   new patterns on every conformance document and on every bench document text in the
   repository. If one match differs, the issue stops and reports it. It shows a rule that
   depends on the order of a list.
2. No file under `conformance/` changes.
3. Every bench check in CI passes with no change of a file.
4. `examples/irs-590a/build.py` rebuilds byte for byte.
5. A receipt of a packet with no pack is byte for byte the same, because the base pack is not in
   the receipt. I checked: no `results.json` under `bench/` holds a receipt digest.

**Stage 2: the loader and kind packs (no decision change).** A packet with no pack decides as
before. The receipt gets `"packs": []`, so receipt digests change, but no outcome, code, `missing`
or `parts` changes. The new vectors that use packs are new files, written by hand.

**Stage 3: kind packs from the bench schemas (no decision change).** The bench sets keep their
own schema files, so their results do not change. A test writes each set's schema in the
template form and checks that it resolves to the same `fields`, member by member. That proves
that the templates hold the sets' knowledge with no change.

**Stage 4: the `finance` pack (a decision change toward review).** The loss words leave the
base. A packet with no pack then gives no sign from a loss word, and such a value goes to review
with `sign` in `missing`. That is the one decision change of the move. It goes into SPEC 0.10
with vectors written by hand before the code:

- Today 9 vector files hold a loss word. The issue lists the ones where a loss word passes a sign
  check. Each of them names `finance` in its schema, with the same expected outcomes.
- New vectors show the outcome without `finance`: review, not a wrong admit.
- The bench scripts of the financial sets name `finance`, and every check stays the same. The
  issue also reports, for each set, how many decisions change without `finance`. That number
  shows how much the current results depend on finance words.

If an outcome changes even with the pack, the issue reports it as a rule that was tuned, as §9
says. It does not hide it.

## 11. How `verify` finds the packs of an old receipt

The receipt names each pack by id, version and digest. `verify` takes the same inputs as `admit`,
with the packs, and then:

1. For each entry in the receipt's `packs`, it looks for a built-in pack with that id and version,
   then for a given pack with that id and version. With `--pack-dir DIR`, it also reads each pack
   file in `DIR` and takes the one with the receipt's digest.
2. If no pack matches, `verify` gives one problem that names the id, the version and the digest,
   and no further checks. The app then knows which file to find.
3. If a pack matches by id and version but not by digest, `verify` gives one problem that names
   both digests, and no further checks.
4. Then it resolves the schema and re-derives the receipt, as today.

A built-in version stays in every later wheel of the same spec version, also when it is retired.
A receipt of an older spec version needs the wheel of that version, as today (SPEC, intro). That
wheel holds its own built-in packs, so `pip install groundgate==X` is enough for them. The rule
for old receipts after an upgrade is gap 9 of #277, and it is not in this note.

For its own packs, the app keeps each pack file that a receipt names. I advise a folder of files
with the digest in the name, next to the receipts. The how-to of issue 6 shows this.

## 12. What a pack cannot do: the loader checks

The loader runs these checks on each pack, and then on the union. A pack that fails one is an
invalid packet: `admit` raises `PacketError` and makes no receipt.

| Check | The loader refuses |
|---|---|
| L1 closed format | a key that the format of its `type` does not list, or a `groundgate_pack` other than `1` |
| L2 data only | a value that is not a string, an integer in its stated range, a list or an object of these. No string is a pattern: the core escapes every word. |
| L3 words | a word that is not NFC, is blank, has whitespace at an end, holds a line break or a tab, or has more than 64 code points |
| L4 size | a pack of more than 256 KiB as canonical JSON, a list of more than 2,000 entries, or more than 200 field templates |
| L5 add only | a list in a non-base pack that section 4 marks "no", and any member that names a window, a reach, a threshold, a code, a step or a policy member |
| L6 no conflict | after the union: a word in two comparator lists; a scale word, suffix or currency scale with two powers; a power other than 3, 5, 6, 7, 9 or 12; a scale suffix that is also a unit suffix; a unit form under two unit codes; a loss word that is also a gain word; a qualifier phrase from a pack that holds a phrase of another comparator, or is held in one |
| L7 ids and versions | an id or a version with the wrong form; a given pack with a built-in id; an id of the app's own pack with no `-x-` name; one id with two versions in one packet |
| L8 status | a malformed row; a `measured` row in a pack that is not built in; a built-in `measured` row with no `results` file or no `bound` |
| L9 kind pack | a template member other than the five of section 5; a template that fails SPEC §2.3; a `needs` entry that names a kind pack or a pack that does not load |
| L10 schema | a `template` whose pack is not in `packs`, or whose field is not in that pack; a `type` or `unit` conflict; a pinned `sha256` that differs |
| L11 digest | nothing to refuse: the loader computes each digest itself and never reads one from the pack |
| L12 no text | a member that holds document text, a span, a value or an evidence item. `description` never enters a decision. |
| L13 relations | after #321: a relation that names a field that is not a template of its pack |

The qualifier rule of L6 has a reason. SPEC §4.2 applies the longer of two qualifiers that
overlap. A pack phrase that holds a base phrase of another comparator then replaces the base
reading. For example, "less than or equal to" as `le` would hide "less than" as `lt`. The loader
refuses that, so an added qualifier can only add a reading.

Each limit of extensions.md §6 maps to these checks:

| Limit (§6) | Checks |
|---|---|
| Turn off or weaken a check in SPEC §3 or §4 | L1, L5, L6, and rule 1 of section 3: the base always applies |
| Add code that runs during the decision | L2, L4, and no entry points in 0.10 |
| Change the meaning of a code, an outcome or a receipt field | L1, L5 |
| Change the result of `verify` without a change of its digest | L11, the pin of L10, the digest list of section 6 |
| Add a value to the document text or the evidence | L12 |

L4 also keeps the work of one packet bounded, as the limit of 8 field items does (SPEC §3). The
security review of the pack loader is an exit condition of 1.0 (#277).

## 13. Relation checks and the heading unit

**Relations (#321).** A relation can come from a kind pack. The member `relations` is in format 1
now, and #321 defines what it holds. A pack relation applies only when every field that it names
is in the resolved schema from that pack's templates. So a relation of `us-10k` never applies to
an app field with the same name and another meaning. A failed relation sends its fields to
review, and a relation that holds admits nothing more (extensions.md §5.3). So a relation only
adds reviews, and it is safe while its route is `draft`. If #321 also lets the schema give
relations, both apply: a union of checks that only add reviews is safe. The digest of the pack
covers its relations.

**The heading unit (#315).** #315 reads a currency unit from a column header or a statement such
as "presented in Australian dollars". The statement words and the currency names only help to
admit: without them, a value under such a statement goes to review, as in 0.9. So they can be
the first item of a vocabulary pack: `finance`, list `heading_units`. #315 is in lane 3 and
merges before the pack code. I ask that #315 keeps its words in one named list in `text.py`, so
that issue 5 below moves that one list. The review when `$` and a statement disagree is a rule
of #315, and it stays in the core. If the maintainer decides on #315 that the words stay in the
core list, issue 5 puts them in `en` instead. The format does not change.

## 14. Changes to other design notes

- [locale-packs.md](locale-packs.md) §4 says that a key in a pack replaces the same key in the
  pack that it extends. For word lists, this note decides a union with the base instead, because
  a replace can remove a guard word. `extends` with replace stays for the number format settings
  of locale stage 2. I edit locale-packs.md when that stage starts.
- A locale pack (#60) is a vocabulary pack with more lists in a later pack format. Its id still
  goes with the document (locale-packs.md §5).
- The entry points of hybrid-decisions.md §7 are not in 0.10 (section 7).
- Question 2 of extensions.md §13 is for #321. Question 5 is for #269 and #323.

## 15. Code issues for 0.10

I open these after the maintainer approves this note, in this order. Issues 1, 2, 3 and 5 change
SPEC.md and `conformance/build.py`, so they merge one at a time with the other spec lanes of #326.

1. **Spec 0.10: the core lists move into the base vocabulary pack `en`.**
   Write `src/groundgate/packs/en/1.0.0.json` with each list of section 10.1 that goes to `en`.
   `text.py` and `admit.py` build their patterns from it. SPEC points to it and gives its digest.
   The proof of stage 1 (section 10.3): vectors, bench checks, example and receipts stay the same.
2. **Spec 0.10: the pack loader, its checks and the pack digest.**
   `groundgate.load_pack`, the checks L1 to L12, the digest of section 6 and the union of section 8.
   The schema member `packs`, `admit(..., packs=)`, the CLI `--pack` and the receipt member `packs`.
   An invalid packet for each check under `conformance/invalid/`, written by hand before the code.
3. **Spec 0.10: kind packs and field templates.**
   The kind pack format, `needs`, the schema member `template`, and the resolved schema and its
   digest (section 5.1). Vectors by hand first: a template fills, the schema wins, a conflict of
   type or unit is invalid, a pin that differs is invalid. #321 adds `relations` after this issue.
4. **Kind packs from the current bench schemas.**
   `us-10k`, `us-government-reports`, `annual-reports`, `component-datasheets` with the vocabulary
   pack `electronics`, and `benefit-summaries`, all `draft`. The bench sets keep their schemas.
   A test shows that the schema of each set in template form resolves to its current `fields`.
5. **Spec 0.10: the `finance` pack takes the loss words and the currency statement words.**
   The decision change of stage 4: SPEC text, and vectors with and without `finance`, by hand first.
   The bench scripts of the financial sets name `finance`, and every check stays the same.
   The issue reports, for each set, how many decisions change without `finance`.
6. **`verify` finds the packs of a receipt.**
   The steps of section 11, `--pack-dir`, and the problems for a missing pack or another digest.
   The list of digests of the released built-in versions, its CI test, and `retired`.
   A how-to page: how the app keeps its pack files next to its receipts.
7. **The report names the packs of a receipt and their status.**
   `groundgate report` lists each pack with its version and digest, and says that it is `draft`.
   A mark on each value that a draft route helped to admit needs the route measure of 0.11.
