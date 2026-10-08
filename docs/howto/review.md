# Review flagged facts and keep receipts

groundgate admits what it can check and sends the rest to a person. This page shows how to give
that person a review page, how to keep the receipts, and how to verify a receipt later. The lease
text and the numbers are made up.

## 1. Admit the candidates

The examples on this page use one document, one schema and four candidates. One candidate is
admitted, two are flagged and one is rejected.

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg
from groundgate.report import render

text = (
    "Lease summary\n\n"
    "The monthly rent is $2,450. The security deposit is about $4,900. "
    "A late fee of $75 applies after the due date.\n"
)
schema = {
    "fields": {
        "monthly_rent": {"type": "integer", "unit": "USD", "required": True},
        "security_deposit": {"type": "integer", "unit": "USD"},
        "late_fee": {"type": "integer", "unit": "USD"},
    }
}
candidates = [
    {
        "id": "rent",
        "field": "monthly_rent",
        "value": "2450",
        "unit": "USD",
        "evidence": [{"text": "$2,450"}],
    },
    {
        "id": "deposit",
        "field": "security_deposit",
        "value": "4900",
        "unit": "USD",
        "evidence": [{"text": "$4,900"}],
    },
    {"id": "fee", "field": "late_fee", "value": "57", "unit": "USD", "evidence": [{"text": "$75"}]},
    {
        "id": "fee-web",
        "field": "late_fee",
        "value": "75",
        "unit": "USD",
        "evidence": [
            {
                "source": "external",
                "url": "https://leases.example.org/terms/",
                "retrieved": "2026-09-30",
                "text": "The late fee is $75.",
            }
        ],
    },
]
receipt = gg.admit(text, schema, candidates, document_id="lease-0417")
for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
    print(f"{d.candidate_id:<8} {d.outcome:<19} {' '.join(d.codes)}".rstrip())
```

```text
deposit  needs_verification  QUALIFIED_VALUE
fee      rejected            VALUE_NOT_IN_EVIDENCE
fee-web  needs_verification  EVIDENCE_QUOTED
rent     admitted
```

## 2. Render the review page

`groundgate.report.render` returns one HTML page. Write it to a file and open it in a browser.

1. Pass the receipt as a dict, the text and the candidates.
2. Pass `schema=` and every other input that you gave `admit`: `policy=`, `judgments=`,
   `references=` and `document_source=`.
3. Write the result to a `.html` file.

```python
work = Path(tempfile.mkdtemp())
receipt_dict = receipt.to_dict()
html = render(receipt_dict, text, candidates, schema=schema, title="Lease 0417")
page = work / "report.html"
page.write_text(html, encoding="utf-8")
print("receipt verified" in html, "receipt does not match" in html)
```

```text
True False
```

With `schema=`, the page re-derives the receipt first. Its header says "receipt verified" when
every byte matches, or "receipt does not match its inputs". Without `schema=`, it says "receipt
not verified".

The page shows:

- the counts of admitted, flagged and rejected facts, and the required fields with no fact;
- one card for each decision, grouped by outcome: the field, the value, the codes with one
  sentence each, the cited text, each role item and whether it passed, and the missing parts;
- the source of an outside decision: the reference id, the external URL, or "from the extractor's
  knowledge", with the quoted or stated text;
- the document, with each value span marked in the color of its outcome and each role item
  underlined.

A checkbox for each outcome hides or shows its cards. The page has no scripts and loads nothing.
For a PDF, pass `layout=` from `extract`, and each card shows its page number.

## 3. Use the command line

The CLI does the same steps with files. `report` verifies the receipt first, and it does not
render a receipt that does not match.

```bash
groundgate extract lease.html -o doc.txt
groundgate admit doc.txt schema.json candidates.json --document-id lease-0417 -o receipt.json
groundgate verify receipt.json doc.txt schema.json candidates.json
groundgate report receipt.json doc.txt schema.json candidates.json -o report.html
```

Give `verify` and `report` the same `--policy`, `--judgments`, `--references` and
`--document-source` that you gave `admit`. `verify` prints "receipt verified" and exits 0, or
prints each problem and exits 1. Invalid input exits 2.

## 4. Store receipts as JSON

`receipt.to_dict()` is the JSON receipt. Store it as UTF-8 JSON.

```python
stored_path = work / "receipt.json"
stored_path.write_text(json.dumps(receipt_dict, indent=2, ensure_ascii=False), encoding="utf-8")
stored = json.loads(stored_path.read_text(encoding="utf-8"))
print(stored["groundgate"], stored["document"]["id"], stored["summary"])
print(stored["receipt_sha256"][:23])
```

```text
0.5 lease-0417 {'admitted': 1, 'needs_verification': 2, 'rejected': 1}
sha256:51710015b22c3de8
```

A receipt holds digests of its inputs, not the inputs. To verify it later, you need the same
document text, schema, candidates, policy, references, judgments and document source. Store them
with the receipt, or store where to find each one.

## 5. Verify a stored receipt

`gg.verify` decides again from the inputs and compares the result with the stored receipt, byte
for byte:

```python
check = gg.verify(stored, text, schema, candidates)
print(check.ok, check.problems)
```

```text
True ()
```

If one input changed, `verify` lists each difference. Here the stored candidate for the rent has
a different value:

```python
import re

changed = [dict(candidates[0], value="2540"), *candidates[1:]]
check = gg.verify(stored, text, schema, changed)
print(check.ok)
for problem in check.problems:
    print(re.sub(r"(sha256:\w{16})\w+", r"\1...", problem))
```

The digests in the output are cut to 16 digits:

```text
False
coverage differs from the re-derived receipt
summary differs from the re-derived receipt
decision for candidate sha256:19825d4b06d24061... differs
decision for candidate sha256:2f6ca877cb802b17... differs
decision for candidate sha256:581fb509c670b30d... differs
```

The changed rent is not in the text, so it is rejected. The required field `monthly_rent` then
has no fact, so the coverage and the summary differ too. Decisions are sorted by the digest of
their candidate. A changed candidate gets a new digest and can move other decisions, so three
decisions differ.

`verify` does not say which input changed. It says which part of the receipt differs. To find
the changed input, compare the digest of each stored input with the receipt. For a candidate,
`gg.digest("candidate", candidate)` is its `candidate_sha256`.

## 6. Pin the groundgate version

A receipt names the spec version that decided it, in its `groundgate` member. `verify` accepts
only the spec version that it implements. groundgate 0.5.0 and 0.5.1 both implement spec 0.5.
This is a receipt from another spec version:

```python
older = dict(stored, groundgate="0.4")
check = gg.verify(older, text, schema, candidates)
print(check.ok)
print(check.problems)
```

```text
False
('receipt was decided under spec 0.4; this groundgate implements 0.5',)
```

`verify` checks nothing more. So pin the groundgate version in the environment that keeps the
receipts:

```bash
pip install "groundgate==0.5.1"
```

To verify an old receipt, install the release for its spec version in a separate environment.
For spec 0.4, that is `groundgate==0.4.0`.

## 7. What a person checks

The card gives the codes and the cited text. For each common code, the person checks this:

| Code | What the person checks |
|---|---|
| `QUALIFIED_VALUE` | The words around the value, such as "about" or "up to". If the field is a limit, set its `comparator`. If not, the value is not exact: correct it or reject it. |
| `SCALE_WORD` | The scale word after the number. The right value is the scaled value. |
| `PART_MISSING` | Each part in `missing`: the brackets or the loss word for `sign`, the "in thousands" heading for `scale`, the unit for `unit`. |
| `SIGN_CITATION_INVALID`, `SCALE_CITATION_INVALID`, `UNIT_CITATION_INVALID` | That the part applies to this value. The underlined item is in the wrong place, or the part is not necessary. |
| `FIELD_CITATION_INVALID` | That the row label or the sentence names this field. If it does, add its words to the field's `aliases`. |
| `KEY_NOT_AT_VALUE` | The row, the column or the heading above the value. The key must be the candidate's key. |
| `KEY_CITATION_INVALID` | That the cited key is the candidate's key, in the value's text. |
| `NON_VERBATIM_EVIDENCE` | The quote on the card against the text at the span. |
| `EVIDENCE_QUOTED` | The page at the URL. It must hold the quoted passage, and the page must apply to this document. |
| `EVIDENCE_STATED` | A source for the extractor's statement. The statement alone is not evidence. |
| `CONFLICTING_CANDIDATES` | The text, to choose one of the values. groundgate never chooses. |
| `LOW_CONFIDENCE`, `MODEL_DOUBT` | The whole fact: the value, the field and the key. |
| `REQUIRED_FIELD_MISSING` | The document, for the value that no extractor found. |

If the same code comes back on many facts, change the input, not the review. The
[guide](../guide.md#when-a-fact-is-rejected-or-flagged) says what to change for each code. The
page [Send reasons back to the extractor](feedback.md) shows how to ask the extractor for the
missing parts.
