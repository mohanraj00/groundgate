# Locale packs: a design for reading numbers outside US English

Status: draft for discussion, issue #60. No pack exists in 0.7.0. Since spec 0.3, the English
core reads a list of abbreviations (#63), Indian grouping (#59) and only the digits 0 to 9 (#94). This file says how groundgate reads
numbers, number words and currency in any Latin-script language, and how that grows over time.

## 1. The problem

Every text rule in spec 0.2 assumes US English. I ran these on the spec 0.2 core:

| Document | Value | Outcome | Correct outcome |
|---|---|---|---|
| `Take no more than 5 mg a day.` | 5 | needs_verification `QUALIFIED_VALUE` | the same |
| `Take approx. 5 mg a day.` | 5 | admitted | needs_verification |
| `The refund is up to Rs 50,000 a year.` | 50000 | needs_verification `QUALIFIED_VALUE` | the same |
| `The refund is up to Rs. 50,000 a year.` | 50000 | admitted | needs_verification |
| `Limit 2,00,000.` | 200000 | rejected `VALUE_NOT_IN_EVIDENCE` | admitted |
| `Die Dosis beträgt 2.000 mg.` | 2 | admitted | rejected |
| `The fee is $2.5M a year.` | 2500000 | rejected `VALUE_NOT_IN_EVIDENCE` | admitted |

Two of these were escapes in English under spec 0.2. The dot in "approx." and "Rs." ended the
sentence, so the qualifier before it was outside the window. Spec 0.3 fixes both (#63, PR #72) with
an English list of 47 abbreviations, for the qualifier window only. The German row is the worst:
groundgate admits a value that is 1000 times too small.

**Terms.** The *packet* is all the inputs of one run: the document text, the schema, the policy
and the candidates. A *token* is one unit of reading: a run of characters that groundgate reads as
one number, with a start, an end and a value or no value. Almost every rule works on tokens.
Step 10 compares the candidate's value with each token in the span. Step 11 looks for the unit
next to a token. A qualifier window stops at the nearest token on each side. A range is a token,
a connector and a token. So what counts as a token decides what can match and where the windows
stop.

## 2. Goals and non-goals

Goals:

- Read numbers, number words and currency in Latin-script languages: English in all regions,
  German, French, Spanish, and others later.
- Keep every current guarantee. The core is deterministic, dependency-free and never calls a
  model. The receipt names everything that decided it.
- Add a language with data and vectors, not with code.
- When the locale is wrong, fail toward review or rejection, never toward admission.

Not now: non-Latin scripts, unit conversion, dates, locale detection, and documents that mix two
number formats.

## 3. Principles

1. **The locale is an input, never a guess.** "2.000" is 2 in English and 2000 in German. The text
   cannot decide which. The caller declares the locale of each document.
2. **A pack is data, and the algorithm is fixed.** The core has one number reader, one
   number-word evaluator and one qualifier matcher. A pack supplies only lists and settings.
3. **The receipt names the pack.** The receipt records the locale and the digest of the resolved
   pack. If a pack changes, every hash changes.
4. **A rare form gets a flag.** If a token can mean a different value in a common other locale,
   and that form is rare in the declared locale, a person looks at it.
5. **A pack is measured before it is trusted.** A pack has a status. It is `draft` until it is
   measured on documents that nobody used to write it.

## 4. The pack

A pack is a JSON object with a fixed schema. `LOCALES.md` states the pack rules, and each
built-in pack is one JSON file under `spec/locales/`, for example `spec/locales/de-DE.json`.
`SPEC.md` points to both. Another implementation loads the same files. A caller can also define
their own pack (§5).

```json
{"id": "de-DE", "extends": "de", "status": "draft",
 "digits": "0123456789",
 "number": {"decimal": [","], "group": [".", " ", " "], "grouping": [[3]],
            "minus": ["-", "−"]},
 "scale": {"words": {"tausend": 3, "Million": 6, "Millionen": 6, "Milliarde": 9,
                     "Milliarden": 9},
           "abbreviations": {"Tsd.": 3, "Mio.": 6, "Mrd.": 9}},
 "currency": {"EUR": {"prefix": ["€"], "suffix": ["€", "EUR", "Euro"]}},
 "units": {"hours": ["Stunden", "Stunde"], "days": ["Tage", "Tag"]},
 "sentence": {"abbreviations": ["ca.", "z. B.", "bzw.", "Nr.", "Mio.", "Mrd."]}}
```

The language pack `de` holds what all German regions share: the number words, the qualifiers and
the sentence rules. A region pack such as `de-DE`, `de-AT` or `de-CH` holds the number format and
the currency. `en-IN` extends `en` the same way:

```json
{"id": "en-IN", "extends": "en", "status": "draft",
 "number": {"decimal": ["."], "group": [","], "grouping": [[3], [3, 2]]},
 "currency": {"INR": {"prefix": ["₹", "Rs.", "Rs", "INR"], "suffix": ["INR", "rupees"],
                      "words": ["Rupees", "Rupee"], "closers": ["only", "/-"]}}}
```

| Key | Meaning |
|---|---|
| `id`, `extends` | A BCP 47 tag, and the pack that this pack builds on. |
| `status` | `draft` or `measured`. The receipt shows it. Only a built-in pack with a published measurement is `measured`. A custom pack is always `draft`, and a custom pack that says `measured` is invalid. |
| `digits` | The characters that are digits. Latin packs list ASCII 0 to 9 only. |
| `number` | The decimal separators, the group separators, the allowed groupings and the minus signs. |
| `scale` | Scale words and abbreviations, each with its power of ten. |
| `words` | The lexicon for number words (§8). |
| `currency` | For each ISO 4217 code: prefix forms, suffix forms, words and closers. |
| `units` | Words for the built-in unit codes, for example "Stunden" for `hours`. |
| `qualifiers` | For each comparator: the words before and after the value, negations, range connectors, change words and per words. |
| `sentence` | The sentence ends, and the abbreviations that do not end a sentence. |

A key in a pack replaces the same key in the pack it extends. There is no append. A region pack
then shows every value that it changes, and nobody has to work out what a merged list contains.

## 5. Where the locale goes

The locale is split in two. The document carries the locale id, and the policy carries custom
packs.

- **The document carries the id.** `admit(text, schema, candidates, policy, document_id,
  locale="de-DE")`. The default is `"en-US"`. `verify` takes the same argument.
- **The policy can define custom packs by id.** `{"locale_packs": {"xx-YY": {...}}}`. A custom id
  must not be a built-in id. The policy is already hashed, so a custom pack is in
  `policy_sha256`.
- **The receipt records both.** `"document": {"id": ..., "sha256": ..., "locale": {"id":
  "de-DE", "status": "draft", "sha256": "sha256:..."}}`. The digest is over the resolved pack,
  after `extends`.
- An unknown id, or a pack that fails the pack checks (§12), is an invalid packet. There is no
  receipt.

Why this split:

| | Locale in the policy only | Locale with the document only | The split |
|---|---|---|---|
| A mixed set (US and Indian documents) | One policy per locale, so `policy_sha256` no longer means "the same rules" | One policy for the whole set | One policy for the whole set |
| What the receipt says | The language is hidden in the policy hash | "This text, read as `de-DE`" | "This text, read as `de-DE`" |
| A custom pack | One place | Copied next to each document | Defined one time, in the policy |
| A copied `en-US` policy on a German document | Easy to do by accident | Not possible: the locale is per document | Not possible |
| Change to the API | None | A new argument and a new receipt field | A new argument and a new receipt field |

The locale is a fact about the document, so it goes with the document. A pack is configuration,
so it goes in the policy.

## 6. Reading digits

The number token pattern comes from the pack: its digits, its group separators and its decimal
separators. The validity rule stays strict:

- A token has a value when its digits are ungrouped, or when they match one of the pack's
  groupings. `[3]` means groups of three. `[3, 2]` means the last group has three digits and each
  group before it has two, as in 12,34,567.
- The value is the digits with the group separators removed and the decimal separator read as
  a decimal point. The groupings of one pack never give two values for one string, because the
  value does not depend on the grouping.
- In one pack, the decimal separators and the group separators must be disjoint. The pack
  checks reject a pack that breaks this rule.

**A new flag: `NUMBER_FORMAT_AMBIGUOUS`.** A token gets this flag when it has exactly one
separator, that separator is the decimal separator of the pack, and exactly three digits follow
it. "2.000" in `en-US` and "2,000" in `de-DE` are examples. Another common locale reads that
token as a value 1000 times different, and the form is rare in the declared locale. So if the
caller declares the wrong locale, the most dangerous error goes to a person.

**Spaces.** French and Swiss documents group digits with a space: "2 000". A plain space is
dangerous:

- "As Table 2 shows, 100 patients" loses its comma in a PDF and becomes "Table 2 100 patients".
  With plain-space grouping, "2 100" reads as one number, 2100, and the count 100 is lost.
- Text extraction joins the cells of a table row with one space. A dosing row "Week 4 | 250 |
  500" becomes "Week 4 250 500", which reads as 4250500. Set 2 has many tables of this kind.
- "2023 150" has four digits before the space, so the run is one token with no value. Neither
  2023 nor 150 can then match a candidate.

French and Swiss typesetting groups digits with the no-break space (U+00A0) or the narrow no-break
space (U+202F), and text extraction does not put those between cells. So packs use those two only.
A plain space is not a group separator. If a real document needs one later, it comes in as a
decision change, with a flag on every token that uses it.

**The meaning of a digit.** Spec 0.2 says `\d` and does not say which digits that means. Python
matches Devanagari digits and JavaScript does not. A pack lists its digits, so the spec no longer
depends on the regex engine.

## 7. Scale words and abbreviations

The spec 0.2 rule stays: a token followed by a scale word also has a scaled value. A pack lists
its scale words with each inflected form, because the core does no stemming: "Million" and
"Millionen" are two entries. Abbreviations are case-sensitive and can be directly after the
number: "$2.5M", "€3 Mrd.", "₹5 Cr".

An abbreviation must not be a unit suffix in the same table. "L" for lakh is the same as "L" for
litre, so the pack checks reject that pack.

## 8. Number words

A number in words is a token like a digit token. It has a value, or it has no value.

**The lexicon.** Each entry has a surface form, a value and a kind:

| Kind | English examples | Effect |
|---|---|---|
| `unit` | one to nine | adds its value |
| `teen` | ten to nineteen | adds its value |
| `ten` | twenty to ninety | adds its value |
| `hundred` | hundred | multiplies the current group by 100 |
| `scale` | thousand, lakh, crore, million | multiplies the current group by its power of ten and closes the group |
| `connector` | and, a hyphen | no value; allowed only inside a phrase |

**One evaluator for all packs.** A phrase is a maximal run of lexicon entries. The evaluator
keeps a group and a total. Units, teens and tens add to the group. `hundred` multiplies the group
by 100. A scale word adds the group times its power of ten to the total, then clears the group.
"Two Lakh Fifty Thousand" is 2 × 10^5 + 50 × 10^3 = 250000.

**Strict order.** A phrase has a value only when its parts are in descending place order: in a
group, hundreds before tens before units, and the scale words strictly descending. "five five"
and "twenty thirty" have no value. The phrase never gets a value from a guess.

**Language settings.** Three settings cover the Latin languages that I know of:

- `compound`: the number is one word, so the core splits it into lexicon entries by the longest
  match. The whole word must split, or it is not a number. German "zweitausendfünfhundert" is
  2500.
- `unit_before_ten`: a unit, a connector and a ten in that order are one value. German
  "fünfundzwanzig" is 5 + 20 = 25.
- `ten_plus_teen`: a ten followed by a teen is one value. French "soixante-dix" is 60 + 10 = 70.
  "quatre-vingts" is one lexicon entry with the value 80.

**"a" and "one".** "a" counts as 1 only directly before `hundred` or a scale word: "a million".
"one" counts only inside a longer phrase ("one hundred", "one lakh") or directly before a scale
word. A lone "one" is not a token. It could become one later, but it moves the qualifier windows
in current English documents. In "Take up to one 500 mg tablet", 500 gets `QUALIFIED_VALUE` today, because the window
before it reaches "up to". If "one" is a token, the window stops at "one" and 500 is admitted.
That is probably correct here, because the dose is exactly 500 mg, but the same change can remove
a correct flag in another sentence. It moves outcomes in both directions, so it is a separate
decision change with its own measurement.

**The receipt.** A value matched through words records the informational code
`NUMBER_IN_WORDS`. It does not change the outcome. The never-read-a-prefix rule applies, so a
span that cuts "two thousand" after "two" does not read 2.

## 9. Currency

- Currency surface forms move from the built-in unit table into the packs. The candidate's
  `unit` stays an ISO 4217 code.
- Every pack recognises the ISO codes before or after the number: "USD 2,000", "2.000 EUR".
- The pack maps symbols. "$" is USD in `en-US`, CAD in `en-CA` and AUD in `en-AU`. A symbol that
  the pack does not map is not a currency, so groundgate never guesses. "US$", "C$" and "A$" are
  explicit in every English pack.
- A form can come before or after the number: "€2,000" and "2.000 €".
- Currency words count as prefix or suffix forms: "Rupees Two Lakh only".
- Closers are words or marks that end an amount and carry no value: "only" and "/-" in "Rs.
  500/-".
- Minor units ("cents", "paise") are their own unit codes. groundgate does not convert 50 cents to
  0.50 USD, the same as it does not convert grams to milligrams.
- The schema's `units` still extends and overrides the table.

## 10. Words near the value

**Qualifiers.** Each language pack lists its qualifiers for each comparator, its negations, its
range connectors and its change words. German examples: "höchstens", "mindestens", "bis zu",
"mehr als", "zwischen ... und". French examples: "au plus", "au moins", "jusqu'à", "plus de",
"entre ... et".

**Negations.** French splits the negation around the verb: "ne doit pas dépasser". A rule that
inverts a qualifier after a negation does not work there. A pack lists the negated phrases
directly ("pas plus de" is `le`). The inversion rule applies only in a pack that turns it on and
that has a measurement for it.

**Sentence ends.** The pack lists the abbreviations that do not end a sentence: "approx.", "Rs.",
"No.", "e.g.", "vs." in English, and "ca.", "z. B.", "Nr." in German. Spec 0.3 already has the
English list in the core (PR #72), so the `en-US` pack takes that list as it is. PR #72 found three
limits that every pack keeps:

- The list applies to the qualifier window only. A wider window can only add a flag. Key scope
  and the unit search still end at every dot, because two security reviews showed that a join
  there lets the key or unit of one sentence reach a value in the next.
- A dot does not end a sentence only when a lowercase letter, a digit or a currency sign follows
  it, and no blank line.
- An abbreviation must not collide with a common word. English leaves out "ca", because it also
  matches the state code "CA" before a ZIP code. The German pack can list "ca." only if its
  vectors and its measurement show no such collision in German text.

**Letters.** Word boundaries use Unicode letters (category L), not `[A-Za-z]`. "über" and "jusqu'à"
are then whole words. The spec defines a letter and a digit by Unicode category, so Python and
JavaScript agree.

## 11. Changes to the decision procedure

- Step 10: the number tokens come from the pack, and include scaled values and number words.
- Step 11: the unit forms come from the pack and the schema.
- A new flag, `NUMBER_FORMAT_AMBIGUOUS`.
- A new informational code, `NUMBER_IN_WORDS`.
- The receipt names the locale, its status and its digest.
- An unknown locale or a bad pack is an invalid packet.

## 12. How it grows

**Stages.** Each stage has hand-written vectors first, then code, then a measurement. I will
choose which stages share a spec version later.

| Stage | Work | Decision change |
|---|---|---|
| 0 | Move every current English list into a built-in `en-US` pack. | None: all vectors, the v0.1 rescore and the set-2 rescore stay byte for byte. |
| 1 | Digits and letters by Unicode category. The English abbreviation list is already in spec 0.3 (PR #72); this stage moves it into the `en-US` pack. | Yes, in English (digits). |
| 2 | Number formats from the pack: `en-IN`, `de`, `fr`, `es` formats; `NUMBER_FORMAT_AMBIGUOUS`. Indian grouping (#59) goes into spec 0.3 directly (PR #75); this stage moves it into the `en-IN` pack. | Yes. |
| 3 | Currency in packs; scale abbreviations. | Yes. |
| 4 | Qualifier, negation, range and change words for `de`, `fr` and `es`. | Yes, in those packs. |
| 5 | Number words. | Yes. |
| 6 | Custom packs in the public API. | No. |
| 7 | Other scripts: their digits, their sentence ends, and text with no spaces between words. | Yes. |

Mixed forms of digits and words, such as "1 crore 20 lakh" or "2 lakh 50 thousand", come after
stage 5. They need their own vectors, and an Indian measurement set must show that they occur.

**Pack checks.** A pack is valid only when these checks pass:

- The decimal separators and the group separators are disjoint.
- No word is in two comparator lists.
- No scale abbreviation is also a unit suffix.
- Each lexicon entry has one kind.
- The `extends` chain ends at a built-in pack and has no loop.
- A custom pack has `status` `draft`, and its id is not a built-in id.

**Vectors.** Each pack gets its own vectors under `conformance/vectors/locale/<id>/`, written by
hand. A round-trip test formats random decimals with an independent formatter, for example CLDR
data in a test-only dependency, and checks that the pack reads them back. The expectations never
come from groundgate itself.

**Measurement.** Each pack needs a set of documents in its locale, picked by frozen rules before
anybody reads them. EU law on EUR-Lex has the same text in German, French, Spanish and English.
A parallel set compares the packs on the same content. For `en-IN`, public Indian government
documents with amounts in lakh and crore are the source. A pack keeps `draft` status until its
set is scored.

**Reference data.** CLDR is a source for separators, groupings and currency symbols. Its licence
allows that use, and a pack that uses it says so. Each pack is still written and checked by
hand, and the pack is the authority, not CLDR.

## 13. Decisions

These questions were open in the first draft. I decided them as follows.

| Question | Decision | Where |
|---|---|---|
| Does the locale go in the policy or with the document? | The id goes with the document. Custom packs go in the policy. | §5 |
| Can a plain space group digits? | No. Only the no-break space and the narrow no-break space. | §6 |
| Is a lone "one" a token? | No. "one" counts only inside a longer phrase or before a scale word. | §8 |
| Does `extends` replace or append? | Replace only. | §4 |
| Can a custom pack be `measured`? | No. A custom pack is always `draft`. | §4, §12 |
| When do mixed forms such as "1 crore 20 lakh" come in? | After stage 5, with their own vectors and an Indian set. | §12 |
| Where do the packs live? | `LOCALES.md` for the rules, one JSON file per pack under `spec/locales/`. | §4 |
