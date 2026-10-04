# Hybrid decisions: scripts, a System 1 model and a person

Status: draft for discussion, issue #66. The measurement that it depends on is #67. No spec
version yet. The locale design (#60) is separate and works with or without this one.

## 1. The goal

groundgate's goal is data quality at the lowest total cost. Three costs count:

- **Escapes:** a wrong value admitted without review. This is the most expensive cost, because
  nobody sees it.
- **Reviews:** a person examines a value. This costs time on every flagged value, correct or
  wrong.
- **Lost recall:** a correct value rejected, or never extracted. The dataset is then smaller.

Today two deciders share the work: the scripts in the core, and a person. This design adds a
third decider, a small local model, and a router that sends each question to the cheapest
decider that can answer it safely. The user chooses how much of this to use. Core only stays a
complete product.

## 2. Where people work today

### Live use (set 2, spec 0.2, 14 runs pooled)

All numbers are from `bench/set2/RESULTS.md`.

| Measure | Value |
|---|---|
| Extractions sent to a person | 39.6% (2730/6903) |
| Wrong extractions admitted without review | 8.8% (72/823) |
| Correct extractions rejected | 0.5% (28/6080) |
| Gold facts admitted, by run | 45.1% to 58.1% of 401 |

The review load is the largest human cost. The report does not yet split it into correct and
wrong values (#67 adds that). A bound follows from the published numbers: 823 values were wrong
and 72 of them were admitted, so at most 751 wrong values were in review. At least 1979 of the
2730 reviews were of correct values that a person only confirmed.

The 72 escapes were wrong for three reasons: 34 wrong value, 28 field absent, 10 wrong key. No
script can see most of these, because the number is in the document and at the cited place. It
is only the wrong number for the field. In the v0.1 benchmark, six of the eight escapes were
this case.

The planted errors (Track A) show which flags cost the most review on correct values:

| Planted case | Sent to review under 0.2 |
|---|---|
| Correct value inside "from X to Y" | 91.5% |
| Right value, another key of the field | 83.8% |
| Correct value, paraphrased text | 58.1% |
| Correct value written with a scale word | 38.6% |
| Correct value after "not more than" and similar | 18.6% |

And one planted case that escapes: "a nearby number with the same unit" is admitted 27.3% of the
time.

### Development

| Task | Human cost now |
|---|---|
| Gold for a benchmark set | Set 2: 74 documents, 401 facts, 93 absences, 6 exclusions, 2.5 hours by one person |
| Control items | Judged one by one in the labeling app |
| Reading escapes | Every escape read one by one for `RESULTS.md` |
| Pattern sets for a rule change | Rules written and frozen before the documents are read (#58) |
| Rules and vectors | Written by hand. Expectations never come from groundgate. |
| Locale packs (#60) | Word lists, number words and currency forms for each language |

## 3. Three deciders

| Decider | Strength | Weakness | Cost |
|---|---|---|---|
| Scripts (the core) | Proofs. Deterministic. Anyone can audit them. | Sees only what a pattern can see. One language at a time. | Almost zero |
| System 1 model | Reads meaning. Many languages. Typed answers with a probability. | Wrong some of the time. Needs a measurement for each question. | Low |
| Person | The final authority. | Slow and expensive. | High |

### Why a System 1 model

A System 1 model answers a typed question in one forward pass, with no generated text. The two
examples that I looked at offer the same three primitives:

- `choice`: pick one option from a list, with a probability for each option.
- `score`: a rating against criteria.
- `noul`: the probability that a statement is true.

groundgate's questions are typed and closed. "Which comparator does the text state?" is a choice
among seven options. "Does this sentence state this field?" is a statement. A generative LLM
answers these too, but slower, at a higher cost, and as text that must be parsed. Also, a
question answered by the same kind of model that made the extraction repeats its errors more
often.

| | Laya | Jev |
|---|---|---|
| Source | Open source, Apache-2.0 | TypeSafe |
| Model | ModernBERT-large, 421M parameters; mmBERT-base, 322M | Not in the pages I read |
| Where it runs | Locally, on a CPU, a GPU or Apple Silicon. Offline after the first download of the weights. | A hosted API with an API key. There is no local option. |
| Speed | 7.2 ms per question in a batch on a T4 GPU (README); 140 ms to 365 ms for one question on my Mac | About 120 ms for one question, network included |
| Determinism | The same answers and probabilities in each run, on Apple Silicon and on the CPU | The same answers in two runs; 9 of 32 probabilities moved, by up to 0.06 |
| Languages | 51 tested (README) | Not stated |
| Versions | A Hugging Face revision and a weights digest | `jev-latest` and `jev-preview` are moving names. Each response names the real version, for example `jev-1.13.0`, and a request for that name returns it. |

I took the Laya figures from its README and did not verify them. Jev is hosted only, and the
maintainer can get an API key. Jev's pages do not document its licence, data handling or model
versions.

Which judge to use depends on the use. Development work on public documents, such as gold checks
and escape sorting, uses Jev: it was much more accurate in the first check, and public documents
can leave the machine. The default judge for live use is chosen after the measurement in #67.
Live use weighs accuracy against two costs of a hosted judge: the text leaves the machine, and
the probabilities vary between runs.

### A first check

I ran Laya 0.3.26 locally and Jev through its API on the same 32 sentences. I wrote the sentences
and the expected answers by hand. None came from set 2 or the v0.1 set. This is a quick check, not
a measurement (#67). The sentences are short and clean, unlike real documents.

| Question | Jev | Laya `english` | Laya `typed-decisions` | Laya `multilingual` |
|---|---|---|---|---|
| Comparator, 18 (4 in German) | 18 | 12 | 11 | 1 |
| Key, 4 | 4 | 3 | 3 | 3 |
| Does this sentence state this field? 6 | 6 | 6 | 5 | 2 |
| Quote and span state the same fact, 4 | 4 | 3 | 3 | 2 |
| Total, 32 | 32 | 24 | 22 | 8 |

`jev-latest` and `jev-preview` gave the same answers, and both reported `jev-1.13.0`.

- Laya `english` was wrong with high confidence on cases that a script already gets right: the
  old value of "increased from $120 to $150" as the new value (0.941), "Do not take more than
  4,000 mg" as "more than" (0.690), and "höchstens 4.000 mg" as "more than" (0.770). Jev answered
  all three correctly with 1.00. A different judge can make the same kind of error on other text,
  so rule 8 in §4 stays.
- On the field-match question, Jev gave 0.96 to 0.98 to the true values and 0.01 to 0.02 to the
  wrong ones. Laya `english` gave 0.646 and 0.486 for one pair.
- Jev's lowest confidences were on ranges and on "under 12": 0.65 to 0.78, all correct. A
  threshold near 0.98 does not clear those.
- Laya repeated its probabilities exactly. Jev repeated its answers, but its probabilities moved
  by up to 0.06. Only recorded answers make a receipt re-derive byte for byte (rule 7 in §4).
- Laya's default call loaded the latest weights, not the revision that the package pins. The API
  rejects `jev-1.12.0` as an unknown model. I do not know if that version existed. If old
  versions are retired, a pinned threshold stops working with its version. Rule 9 in §4 covers
  both.
- Each Jev response reports output tokens, for example 88 for one question. I do not know what
  these are, for a model described as System 1 (§12).

The Laya README says that its answers have the same schema as Jev's, so a Jev client needs only a
different base URL. One adapter can then serve both: Laya on the local machine and Jev on the
hosted API.

## 4. The rules that keep the guarantees

The decision stays a pure function. A model's answer is an input to it, like a candidate.

1. **A model never overturns a proof.** A rejection from steps 1 to 11 stays a rejection. If the
   value is not in the span, no probability changes that.
2. **A model clears a flag only where the policy says so.** The policy names the flag, the
   locale, the model digest and the threshold. The default policy names none, so the default
   behaviour is the current behaviour.
3. **A model can always add doubt.** A model answer can send an admitted value to review. That
   costs review time, never an escape.
4. **A model can propose a location, and the scripts prove it.** If a model points to a different
   span, steps 10 and 11 run again on that span. The model finds; the script proves.
5. **Every model decision is visible.** A decision that a model changed carries a code that says
   so. An audit can select all of them.
6. **People always audit a sample.** The policy sets a rate of admitted values that go to a
   person at random. The escape rate is then always measured, not assumed.
7. **The receipt records the answer, not the run.** The receipt holds each model answer: the
   question, the model id and digest, the answer and the probability. `verify` re-derives the
   receipt byte for byte from those recorded answers. A separate replay check runs the model
   again and accepts a small difference in probability. The tolerance comes from a measurement
   for each judge: Jev's probabilities moved by up to 0.06 between two runs.
8. **A model cannot clear a flag where a script has a specific reading.** The old value of a
   change and a negated qualifier are examples. The script's rule exists because these cases are
   dangerous, and a model reads them wrong with high confidence (§3, "A first check"). A model can
   clear only the general flags that the scripts cannot resolve.
9. **The model is pinned.** The policy names one model revision and the digest of its weights, or
   one version of a hosted model. A default such as "the latest weights" or `jev-latest` is
   invalid, because the thresholds belong to one model. For Jev, the policy names the version
   that the response reports, for example `jev-1.13.0`. When a hosted version is retired, its
   thresholds go with it, and the new version needs a new measurement.

The vectors can include model answers as inputs. Another implementation then proves that it
agrees on the decision function without the model.

## 5. Check by check

This is the main analysis. For each check: what a person does now, the question for a System 1
model, and what the answer can do.

### Steps 1 to 9: no model

`CANDIDATE_INVALID`, `FIELD_UNKNOWN`, `NULL_STRING_LITERAL`, `TYPE_INVALID`, `RANGE_INVALID`,
`UNIT_INVALID`, `KEY_INVALID`, `NO_EVIDENCE` and `SPAN_INVALID` are proofs about the candidate
itself. They cost no review, because they reject. A model adds nothing to a decision here.

A model can help recall, not the decision. For `FIELD_UNKNOWN` ("max_dose_daily" for
"max_daily_dose") a choice among the schema's fields can propose a repair to the extractor. The
extractor then sends a new candidate, and the scripts decide it. groundgate never edits a
candidate.

### Steps 10 and 11: the model locates, the script proves

`VALUE_NOT_IN_EVIDENCE` and `UNIT_NOT_IN_EVIDENCE` are proofs. Re-anchoring already recovers a
candidate when the quote occurs exactly once. When the quote occurs zero times or more than once,
the candidate is rejected now.

- **Question:** choice. "Which of these places states {field} as {value}?" The options are the
  places in the search region where the value occurs, each with its sentence.
- **Effect:** the chosen place goes through steps 10 and 11 again, and the decision records
  `EVIDENCE_LOCATED`. The model never admits a value by itself.
- **Gain:** recall. Fewer correct values lost to bad offsets. No human work removed or added.

### `QUALIFIED_VALUE`: the largest flag

A person reads the sentence and decides whether the qualifier changes the value for this field.
The flag fires on "up to", "between", "from X to Y" and the other phrases in §4.2 of the spec.

- **Question:** choice. "What relation does the text state for {value} in {field}?" Options:
  exact, at most, at least, more than, less than, about, range, old value of a change, new value
  of a change.
- **Effect:** if the answer equals the field's comparator with a probability above the
  threshold, the flag clears and the decision records `MODEL_CLEARED`. If the answer differs,
  the flag stays.
- **Evidence:** the planted "from X to Y" case goes to review 91.5% of the time. The change rule
  in the scripts is narrow (#51), and a model reads the looser wording that the scripts miss. The
  old value of a change must stay flagged: 96.3% go to review now, and that is correct.
- **Languages:** this is where the model does the most for #60. In a language with no measured
  qualifier list, the scripts cannot see a qualifier at all. The model's answer can add the flag
  that the scripts cannot.

### `KEY_NOT_AT_VALUE`

A person decides which condition, for example which indication of a drug, the value belongs to.

- **Question:** choice among the field's keys, with the value's sentence and the nearest heading.
- **Effect:** if the answer is the candidate's key, the flag clears. If the answer is another
  key with a high probability, the decision gets `MODEL_DOUBT`.
- **Evidence:** "right value, another key" goes to review 83.8% of the time. Wrong key is also 10
  of the 72 escapes. A key swapped inside a flattened table is a known gap in the scripts (spec
  §4.5), and a model reads tables better than a sentence rule.

### `NON_VERBATIM_EVIDENCE`

A person compares the model's quote with the text at the span.

- **Question:** noul. "The quote '{quote}' and the text '{span}' state the same fact."
- **Effect:** clear the flag above the threshold.
- **Evidence:** "correct value, paraphrased text" goes to review 58.1% of the time.

### `SCALE_WORD`

A person decides whether the candidate wrote 1.2 for "$1.2 million" by mistake.

- **Question:** choice. "{field} is {value} or {value} × {scale}?"
- **Effect:** usually none. The candidate wrote the number as written, and the field needs the
  scaled value. That is a real error, and the flag must stay. A model helps only when the schema
  says that the field is in millions. This code is a poor first target.

### `CONFLICTING_CANDIDATES`

Two candidates for the same field give different values, and a person picks one.

- **Question:** choice among the candidate values, each with its sentence.
- **Effect:** the winner's flag clears; the others get `MODEL_DOUBT`. If the model is not sure,
  all stay flagged.

### `LOW_CONFIDENCE`

The extractor's own confidence is low. A model gives a second opinion with the field-match
question below. If the model agrees with a high probability, the flag clears.

### `NUMBER_FORMAT_AMBIGUOUS` (from #60)

"2.000" under `en-US`. A choice between the two readings, or a choice of the document's locale,
can clear it. The caller still declares the locale. The model only checks it.

### New check: does this sentence state this field?

This is the check that the scripts cannot make, and it is a non-goal of the spec today
("semantic correctness"). It targets the largest group of escapes.

- **Question:** noul. "This sentence states the {field description} of {document kind} as
  {value} {unit}."
- **Effect:** on an admitted value, a low probability adds `MODEL_DOUBT` and the value goes to
  review. It never admits anything.
- **Evidence:** 34 of the 72 escapes are a wrong value, and 28 are a field that the document does
  not have. "A nearby number with the same unit" escapes 27.3% of the time.
- **Cost:** it adds review. The policy sets the threshold where the escapes that it catches are
  worth the reviews that it adds.

### Coverage: `REQUIRED_FIELD_MISSING`

A required field has no admitted candidate. A person now searches the document.

- **Question:** noul for each chunk. "This text states {field}." Then a choice among the places
  with a high probability.
- **Effect:** a field that the model finds goes back to the extractor with that place. A field
  that the model does not find, with a low probability in every chunk, gets the note
  `MODEL_FOUND_NONE`. A person can examine those last.

### The review itself

Even when a value goes to a person, a model can make the review faster:

- **Order:** sort the review queue by the model's probability of an error. The person sees the
  likely errors first.
- **A suggestion:** show the model's answer next to the value. The person confirms it or changes
  it. This changes the time for each review, not the number of reviews.
- **Audit:** sample admitted values in proportion to the model's doubt, with weights in the
  estimate. The same escape-rate precision then needs fewer audits.

## 6. Development use

Each of these reduces the maintainer's time. None of them puts a model inside a published
number.

| Task | How a model helps | The guard |
|---|---|---|
| Gold labeling | After the blind pass, a model answers the same questions. A person checks again only where the model and the gold disagree. | The model never shows an answer before the blind pass is done. The person keeps reviewing blind. |
| Reading escapes | A choice among the causes (wrong value, field absent, wrong key, qualifier missed, wrong unit) sorts the escapes before a person reads them. | A person confirms each cause in `RESULTS.md`. |
| Pattern sets | Count-only feasibility before the rules freeze: how many documents in a pool have a qualifier, a key or a change. | The model counts. It does not choose documents or rules. |
| Locale packs | The model drafts the word lists and the number-word lexicon. Then it answers noul questions on sample sentences, and a person checks the disagreements. | Vectors are still written by hand, and each pack is measured. |
| Vectors | The model proposes difficult sentences for a rule. | A person writes every expected outcome by hand. Expectations never come from groundgate or the model. |
| New rules | Clusters of person decisions from live reviews show patterns that repeat. A repeated pattern becomes a script rule. | A new rule is measured on documents that it was not written from. |

The last row is how the mix improves over time. Work moves from the person to the model, and
from the model to the scripts, where it costs nothing.

## 7. Modes and plug-ins

A user chooses a mode. Every mode gives verifiable receipts.

| Mode | What runs | For whom |
|---|---|---|
| A. Core | The scripts and the built-in packs. | Users who want no model, or who must not use one. |
| B. Core and packs | A, plus plug-in locale packs. | Users with documents in other locales. |
| C. Core, packs and a judge | B, plus a System 1 model for the questions in §5, under the policy's thresholds. | Users who want less review. |
| D. Full loop | C, plus a review tool that records each person's decision as a judgment. | Users who want the mix to improve over time. |

### Plug-in packs

There are three ways to add a pack. All of them use only the standard library.

1. **In the policy.** `"locale_packs": {"de-DE-x-acme": {...}}`, as in the locale design.
2. **From a file.** `gg.load_pack("packs/de-DE-x-acme.json")` returns a pack that the caller puts
   in the policy.
3. **From an installed package.** A package declares an entry point in the group
   `groundgate.locale_packs`. groundgate finds it with `importlib.metadata`. Then `pip install`
   a pack and use its id.

The rules are the same for all three. Built-in ids are reserved, so a plug-in id carries a
private-use suffix (`-x-name`). The pack checks run on load. A plug-in pack is always `draft`.
The receipt records the pack's digest.

### Plug-in judges

A judge is any object with one method:

```python
class Judge(Protocol):
    id: str  # for example "laya-typed-decisions"
    digest: str  # the digest of the weights, or the version of a hosted model

    def answer(self, questions: Sequence[Question]) -> Sequence[Answer]: ...
```

A `Question` is a primitive (`choice`, `score` or `noul`), the text, and the options. An `Answer`
is the answer and its probability. Judges ship as extras that import lazily:
`groundgate[laya]` for local Laya. Because the two answer schemas are the same, one HTTP
adapter serves a local Laya server and the hosted Jev API. Only the base URL and the key differ.
The key comes from the environment (`TYPESAFE_API_KEY` for the Jev SDK), never from the policy or
the receipt. Other packages can
register a judge in the entry point group `groundgate.judges`. A hosted judge sends document text
out of the machine, so it runs only when the policy names it.

### The policy for a judge

```json
{"judge": {"id": "laya-typed-decisions", "digest": "sha256:...",
           "clear": {"QUALIFIED_VALUE": 0.98, "NON_VERBATIM_EVIDENCE": 0.95},
           "doubt": {"field_match": 0.20},
           "audit_rate": 0.02}}
```

A threshold belongs to one model digest. A new model version needs a new measurement and new
thresholds.

## 8. Changes to the receipt

- A `judgments` list: for each answer, the candidate id, the question kind, the question's
  digest, the judge id and digest, the answer and the probability. A person's decision in mode D
  is a judgment too, with `judge: "person"`.
- New codes: `MODEL_CLEARED` (a flag that a model cleared), `MODEL_DOUBT` (doubt that a model
  added), `EVIDENCE_LOCATED` (a place that a model found and the scripts proved), and
  `MODEL_FOUND_NONE` in coverage.
- The outcomes stay the same three. A model never makes a fourth.

## 9. How to choose the thresholds

For each flag, locale and model digest:

1. Take a new gold set. Split it into a calibration part and a test part before anybody reads
   it. Set 2 does not choose thresholds, because it already chose the 0.2 rules.
2. On the calibration part, find the lowest threshold where the 95% upper bound of the escape
   rate among cleared values is below the ceiling that the user sets.
3. Report the escape rate and the cleared fraction on the test part only.
4. Check the calibration: a probability of 0.9 must mean about 90% correct. Laya says that it is
   trained against proper scoring rules. That is a claim to measure, not to assume.

The total cost is then a choice for each user: escapes × the cost of an escape + reviews × the
cost of a review. A team that pays a lot for an escape sets high thresholds. A team with many
documents and a high review cost accepts lower ones.

## 10. Risks

- **Correlated errors.** The extractor is a model too. If the judge misreads the same sentence in
  the same way, it clears exactly the errors that matter. Use a judge of a different kind from
  the extractor, and measure how often both are wrong on the same item (#67).
- **Drift.** A new kind of document or a new language moves the calibration. The audit sample in
  rule 6 shows that. If the agreement between the judge and the person falls, the thresholds must
  go up.
- **Misleading text.** A document can contain text that misleads a classifier. A judge never
  overturns a proof, so the worst case is a cleared flag, and the audit measures that.
- **Privacy.** A hosted judge sends text out. It runs only when the policy names it.
- **Licences and suppliers.** Laya is Apache-2.0. Jev's terms are not documented in the pages I
  read. The `Judge` interface keeps any one supplier replaceable.
- **Conformance.** The thresholds and the recorded answers are inputs, so the decision stays
  testable with vectors. The model itself is not part of the spec.

## 11. Stages

| Stage | Work | Human work removed |
|---|---|---|
| 0 | The judgment record, the `Judge` interface and recorded answers in the receipt. No model ships. | None |
| 1 | Development tools with Jev on public documents: escape sorting, the gold check after the blind pass, pack drafts. | Maintainer time |
| 2 | The measurement in #67. | None, but it sets every later number |
| 3 | Live clearing for the measured flags, probably `QUALIFIED_VALUE`, `KEY_NOT_AT_VALUE` and `NON_VERBATIM_EVIDENCE`. | Reviews of correct values |
| 4 | The field-match doubt check. | Escapes, for more reviews |
| 5 | Locate and repair: `EVIDENCE_LOCATED`, coverage help. | Lost recall |
| 6 | The review tool, review order, suggestions and weighted audits. | Time for each review |

## 12. Open questions

1. Do the thresholds live in the policy, as in §7, or in a separate judge file that the policy
   names by digest?
2. In mode D, does a person's decision change the original receipt, or does it make a second
   receipt that names the first one?
3. Does stage 0 need its own spec version? It adds receipt fields but changes no decision.
4. Which judge is the default for live use, Jev or Laya? #67 decides it. Development work on
   public documents uses Jev (§3).
5. Is the field-match check (§5) worth its added review? #67 answers this with numbers.
6. What are the output tokens in a Jev response, and do they affect cost or repeatability? This
   is a question for TypeSafe.
7. How long does TypeSafe serve an old Jev version?
