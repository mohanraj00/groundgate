# groundgate

**LLMs propose facts. groundgate decides which ones you can trust.**

groundgate is a deterministic admission layer for LLM document extraction. You give it a
document, a schema, and the facts an extractor proposed. Every fact comes back with one of three
outcomes:

- **admitted**: every check passed;
- **needs_verification**: nothing failed, but a person should look, and the decision says where;
- **rejected**: a check failed, with a stable reason code.

Every run writes a receipt with hashes of every input. Anyone can re-derive it byte for byte.

![The groundgate review page for IRS Publication 590-A. Left: a Roth IRA limit flagged QUALIFIED_VALUE because the model cited the spousal-deduction sentence ("more than $236,000"). Right: the source text, with that citation outlined in amber and the correct Roth sentence, admitted, highlighted in green below it.](docs/report.png)

## Why this exists

Grounded extraction tools check that the quoted **text** exists in the source. They don't check
the **value** you asked for.

LangExtract is the clearest example, and a good tool. It aligns each `extraction_text` to the
source and reports `MATCH_EXACT`, `MATCH_FUZZY` and so on. It never looks at the attributes that
hold the typed value. So this passes as an exact match:

```text
extraction_text: "$8,000"     found in the source: MATCH_EXACT
value:           "80000"      not what the source says
```

Here is what that looks like on a real document. I ran Gemini 3.6 Flash and GPT-OSS 120B through
LangExtract on two pages of IRS Publication 590-A. LangExtract aligned all 48 extractions as
`MATCH_EXACT`. groundgate then:

- **rejected** Gemini's reading of a misprinted `$252,0000` as 2,520,000;
- **flagged** two GPT-OSS facts that took a Roth IRA limit from the spousal-deduction sentence;
  the numbers match, but the text says "more than" where the field says "at least";
- **listed** a required field both models missed;
- **admitted** 44 facts, all with the right value.

One admitted fact still cites the wrong rule. Its number is correct, its comparator matches, and
no span check can tell. I checked every decision by hand; the details are in
[examples/irs-590a](examples/irs-590a), which is also the page in the screenshot.

I measured the gap on purpose before writing the library. On 51 facts from two public-domain
government documents, LangExtract's strictest setting (`MATCH_EXACT` only) accepted **100%** of
planted value and unit errors whose quote was correct. groundgate caught **all** of them and
rejected **none** of the correct facts. The method and full tables are in
[spikes/m0_5](spikes/m0_5/README.md).

To be clear about scale: current models rarely get a value wrong. In the benchmark below, 117 of
4,350 real extractions were wrong. The point is not that models are bad. It is that when
one is wrong, nothing downstream should have to trust it, and every fact that is admitted comes
with proof you can re-check.

LangExtract verifies the text. groundgate verifies the value.

## Benchmark

Seven models (Gemini, GPT and Claude, each through its own CLI) ran through LangExtract on 30
public-domain FDA drug labels, NTSB accident reports and IRS publications, at two chunk sizes. A
person checked every gold fact. Of 4,350 extractions, 117 were wrong: the wrong value, a value
for a field the document doesn't state, the wrong unit, or not a number.

![Pooled over all 14 runs: MATCH_EXACT accepted 98% of wrong extractions without review, groundgate 6.8%. MATCH_EXACT rejected 4.6% of correct extractions, groundgate 0.3%. groundgate sent 12% of extractions to a person.](bench/charts/summary.svg)

| | LangExtract, `MATCH_EXACT` | groundgate |
|---|---:|---:|
| wrong extractions accepted without review | 98.3% (115/117) | 6.8% (8/117) |
| correct extractions rejected | 4.6% (194/4,233) | 0.3% (14/4,233) |
| extractions sent to a person | 0% | 12.1% (526/4,350) |

Most catches (84 of 109) were `CONFLICTING_CANDIDATES`: a model proposed two values for a
single-valued field, and groundgate sent both to review instead of picking one.

Six of the 8 that got through are the case groundgate says it cannot catch (see
[What it does not do](#what-it-does-not-do)). Five models took metoprolol's heart failure maximum
(200 mg) as the hypertension maximum, and one took lisinopril's renal impairment dose as the usual
starting dose. Each number is real and cited correctly; it belongs to another condition. The
other two read levothyroxine's 1.6 mcg/kg/day as a flat 1.6 mcg, which the unit check allows.
Putting all seven models through one gate caught one more, because when they were wrong they
mostly agreed.

The benchmark also found a bug. When LangExtract's chunker cut "29.97" after "29.", groundgate
read the span as 29, which its own spec forbids. It's fixed, and three wrong altimeter settings no
longer get through.

Tables and planted-error results: [bench/RESULTS.md](bench/RESULTS.md). Method and caveats:
[bench/README.md](bench/README.md). The write-up, with what got through and why:
[Grounding is a contract, not a citation](https://mohanraj00.github.io/tech/grounding-is-a-contract/).

## Quickstart

```bash
pip install groundgate
```

```python
import groundgate as gg

text = "The IRA contribution limit is $7,000. The deduction phases out above $79,000."
schema = {
    "fields": {
        "ira_limit": {"type": "integer", "unit": "USD"},
        "phaseout_start": {"type": "integer", "unit": "USD"},
    }
}


def cite(field, value, quote):
    """A candidate citing the first place `quote` appears, as UTF-8 byte offsets."""
    start = text.encode().index(quote.encode())
    span = {"start": start, "end": start + len(quote.encode()), "text": quote}
    return {"field": field, "value": value, "unit": "USD", "evidence": span}


candidates = [
    cite("ira_limit", "7000", "$7,000"),
    cite("ira_limit", "70000", "$7,000"),  # a digit too many
    cite("phaseout_start", "79000", "$79,000"),  # "above" is not "at"
]
receipt = gg.admit(text, schema, candidates)
for d in receipt.decisions:
    print(f"{d.outcome:<19} {d.field:<15} {d.value:<6} {' '.join(d.codes)}".rstrip())

print(gg.verify(receipt.to_dict(), text, schema, candidates).ok)
```

```text
needs_verification  phaseout_start  79000  QUALIFIED_VALUE
admitted            ira_limit       7000
rejected            ira_limit       70000  VALUE_NOT_IN_EVIDENCE
True
```

The core has no dependencies. `groundgate[pdf]` adds pdfminer.six for PDF text, and
`groundgate[langextract]` installs LangExtract. [docs/guide.md](docs/guide.md) covers schemas,
policies, candidates and the Python API.

### With LangExtract

```python
import langextract as lx
from groundgate.adapters.langextract import admit_document

result = lx.extract(text_or_documents=text, prompt_description=prompt, examples=examples)
receipt = admit_document(result, schema)
```

Each extraction's `value` and `unit` attributes are checked at the place LangExtract aligned its
`extraction_text`. An extraction LangExtract could not align is rejected `NO_EVIDENCE`.

### From the command line

```bash
groundgate extract p590a.pdf --pages 1-2 -o doc.txt --layout layout.json
groundgate admit   doc.txt schema.json candidates.json -o receipt.json
groundgate verify  receipt.json doc.txt schema.json candidates.json
groundgate report  receipt.json doc.txt schema.json candidates.json --layout layout.json -o report.html
```

`extract` turns a PDF, HTML, XML or text file into the NFC text everything else reads, and
records the page and box of every word. Text a reader can't see (proof marks drawn off the page,
hidden HTML) is dropped, and superscripts are marked so that 10⁹ reads `10^9`, never `109`. Pass
`-` as the document to read it from a pipe. `report` refuses to render a receipt that doesn't
re-derive from its inputs. [examples/irs-590a](examples/irs-590a) runs the whole pipeline on an
IRS publication with cached model output, so it reproduces without an API key.

## What it checks

Checks run in a fixed order. The first failure rejects the fact.

| Code | Rejects when |
|---|---|
| `CANDIDATE_INVALID` | the candidate is malformed |
| `FIELD_UNKNOWN` | the field is not in the schema |
| `NULL_STRING_LITERAL` | the value is `"null"`, `"none"`, `"n/a"` |
| `TYPE_INVALID` | the value does not parse as the field's type |
| `RANGE_INVALID` | the value is outside the field's bounds |
| `UNIT_INVALID` | the unit is not the field's unit |
| `NO_EVIDENCE` | no evidence is cited |
| `SPAN_INVALID` | the span is outside the document or splits a character |
| `VALUE_NOT_IN_EVIDENCE` | no number in the span equals the value |
| `UNIT_NOT_IN_EVIDENCE` | the value is there, but not with the field's unit |

A fact that passes every check can still be flagged for a person:

| Code | Flags when |
|---|---|
| `NON_VERBATIM_EVIDENCE` | the quote differs from the text at the span |
| `QUALIFIED_VALUE` | "up to", "approximately", "or more" changes the value, and the schema didn't declare it |
| `SCALE_WORD` | "million", "lakh" and similar follow the value |
| `LOW_CONFIDENCE` | the extractor's confidence is below the policy minimum |
| `CONFLICTING_CANDIDATES` | another proposal for the same field has a different value |

Number matching is collision-safe. The span `500 mg` inside `1,500 mg` never reads as 500, a span
that stops at `29.` inside `29.97` never reads as 29, and a malformed number like the `$252,0000`
printed in IRS Publication 590-A never equals 252,000 or 2,520,000. When a span misses the value
but its quote occurs exactly once elsewhere with the right value and unit, groundgate moves the
evidence there and records `EVIDENCE_REANCHORED`.

The rules are in [SPEC.md](SPEC.md). [conformance/](conformance) holds 16 language-neutral
vectors that pin every code, so another implementation can prove it agrees.

## Receipts

```json
{"groundgate": "0.1",
 "document": {"id": "irs-p590a-2025-pages-1-2", "sha256": "sha256:387c5991b989..."},
 "schema_sha256": "sha256:...", "policy_sha256": "sha256:...",
 "decisions": [{"candidate_id": "Gemini_3.6_Flash_Medium/0", "field": "ira_limit_2025",
                "outcome": "admitted", "codes": [], "value": "7000", "unit": "USD",
                "evidence": {"start": 2634, "end": 2640}, "candidate_sha256": "sha256:37e4fbb8..."},
               "..."],
 "coverage": [{"field": "roth_phaseout_joint_2026_end", "code": "REQUIRED_FIELD_MISSING"}],
 "summary": {"admitted": 50, "needs_verification": 0, "rejected": 2},
 "receipt_sha256": "sha256:..."}
```

Hashes are SHA-256 over RFC 8785 canonical JSON, so a receipt means the same thing in any
language. `groundgate verify` re-runs every decision from the inputs and fails on any difference:
a changed document, schema, policy, candidate or outcome.

## What it does not do

- **It does not judge meaning.** If the model reports a number that really is in the sentence but
  belongs to another field, every span check passes: a model that reads an age-50 limit of $8,000
  as the IRA limit cites a real "$8,000" with the right unit. A second proposer plus
  `CONFLICTING_CANDIDATES` catches it only when the models disagree, and in the benchmark they
  mostly agreed: six of the eight escapes were this case.
- **No dates, arrays of records, or cross-document checks** in spec v0.1.
- **No OCR.** Scanned PDFs need a text layer first (for example `ocrmypdf`).
- **No model calls.** groundgate never asks an LLM whether an LLM was right.

## Status

Alpha. groundgate 0.1.0 implements spec v0.1, and a receipt names the spec version it was decided
under. The next spec version starts from what the benchmark found: values that depend on a
condition (a dose per indication, a limit per year) and weight-based units. See
[CHANGELOG.md](CHANGELOG.md).

## License

Apache-2.0.
