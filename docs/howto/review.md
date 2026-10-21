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
- the packs that the receipt names, each with its type, its version, its digest and its status.
  A route that nobody measured is `draft`, and no pack has a measured route yet. Each admitted
  value that read a pack has the mark "draft pack". The mark says that groundgate read the pack
  for the value. It does not say that the pack changed the outcome;
- the document, with each value span marked in the color of its outcome and each role item
  underlined.

A checkbox for each outcome hides or shows its cards. The page has no scripts and loads nothing.
For a PDF, pass `layout=` from `read`, and each card shows its page number.

## 3. Use the command line

The CLI does the same steps with files. `report` verifies the receipt first, and it does not
render a receipt that does not match.

```bash
groundgate read lease.html -o doc.txt
groundgate admit doc.txt schema.json candidates.json --document-id lease-0417 -o receipt.json
groundgate verify receipt.json doc.txt schema.json candidates.json
groundgate report receipt.json doc.txt schema.json candidates.json -o report.html
```

Give `verify` and `report` the same `--policy`, `--judgments`, `--references` and
`--document-source` that you gave `admit`. `verify` prints "receipt verified" and exits 0, or
prints each problem and exits 1. Invalid input exits 2.

With a store, you keep one key, not five files. `read --store` writes the source, the text and
the layout, and prints the key of the reading. `admit --store` writes the inputs, the receipt and
a packet, and prints the packet key. `verify --store` and `report --store` get each input from
the packet:

```bash
reading=$(groundgate read --store store lease.html -o doc.txt)
packet=$(groundgate admit --store store --reading "$reading" doc.txt schema.json candidates.json --document-id lease-0417)
groundgate verify --store store "$packet"
groundgate report --store store "$packet" -o report.html
```

`--reading` is optional. With it, the packet names the reading, and `report` shows page numbers
for a PDF. Section 8 shows the store in Python.

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
0.11 lease-0417 {'admitted': 1, 'needs_verification': 2, 'rejected': 1}
sha256:6c8ccda778d114b1
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
decision for candidate sha256:01e4953e2e062e04... differs
decision for candidate sha256:2c2fb9194ff7f452... differs
decision for candidate sha256:5e5ae947faf916ff... differs
```

The changed rent is not in the text, so it is rejected. The required field `monthly_rent` then
has no fact, so the coverage and the summary differ too. Decisions are sorted by the digest of
their candidate. A changed candidate gets a new digest and can move other decisions. Here it
moves two other decisions, so three decisions differ.

`verify` does not say which input changed. It says which part of the receipt differs. To find
the changed input, compare the digest of each stored input with the receipt. For a candidate,
`gg.digest("candidate", candidate)` is its `candidate_sha256`.

## 6. Pin the groundgate version

A receipt names the spec version that decided it, in its `groundgate` member. `verify` accepts
only the spec version that it implements. The released groundgate 0.10.0 implements spec 0.10,
groundgate 0.9.0 implements spec 0.9, groundgate 0.8.0 implements spec 0.8, groundgate 0.7.0
implements spec 0.7, groundgate 0.6.0 and 0.6.1 implement spec 0.6, and groundgate 0.5.0, 0.5.1
and 0.5.2 implement spec 0.5.
This is a receipt from another spec version:

```python
older = dict(stored, groundgate="0.4")
check = gg.verify(older, text, schema, candidates)
print(check.ok)
print(check.problems)
```

```text
False
('receipt was decided under spec 0.4; this groundgate implements 0.11',)
```

`verify` checks nothing more. So pin the groundgate release that decided the receipts in the
environment that keeps them. For spec 0.10, that is:

```bash
pip install "groundgate==0.10.0"
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

## 8. Keep the inputs in a store

A store keeps each input of a receipt by its digest (see the
[store note](../design/store.md)). `admit_packet` runs `admit`, writes the inputs and the
receipt, and returns the key of a packet. The packet names each input. Keep that key:

```python
from groundgate.store import FolderStore, StoreError, key
from groundgate.store.packets import admit_packet, load_packet

store = FolderStore(work / "store")
packet, receipt = admit_packet(store, text, schema, candidates, document_id="lease-0417")
print(packet[:23])
```

```text
sha256:3e0c27fa9861a3cb
```

The same inputs give the same key. Later, `load_packet` gets each input back, and `verify`
decides again:

```python
found = load_packet(store, packet)
check = gg.verify(found.receipt, found.text, found.schema, found.candidates, **found.inputs())
print(check.ok, found.receipt["document"]["id"])
```

```text
True lease-0417
```

If you must delete the document, `forget` removes its text and records the time and the reason.
The receipt and the packet stay. `verify` then cannot decide again, and the error says why. It
does not report a mismatch:

```python
store.forget(key("text@1", text.encode("utf-8")), "the tenant asked")
try:
    load_packet(store, packet)
except StoreError as gone:
    print(str(gone).split(" sha256:")[0])
store.close()
```

```text
input deleted: the text@1 object
```

The command line prints the same message with the key, the time and the reason, and exits 2.
An object that is not in the store and has no deletion record gives "input missing".

## 9. Answer the tasks on the review page

The report page of section 2 shows the flagged facts, but it takes no answer. The review page
takes an answer for each flagged fact and keeps it in the store (see the
[review note](../design/review.md)). First, `write_tasks` writes a task for each flagged fact of
the packet. The `admit_packet` call puts the text back after the `forget` of section 8:

```python
from groundgate.review.resolve import lines, write_resolution
from groundgate.review.serve import Review
from groundgate.review.tasks import write_tasks

store = FolderStore(work / "store")
packet, receipt = admit_packet(store, text, schema, candidates, document_id="lease-0417")
for task_key, task in write_tasks(store, packet).tasks:
    print(task["question"])
```

```text
Is late fee 75 USD (written form not found, positive)?
Is security deposit 4,900 USD (written 4,900, not scaled, positive)?
```

The question names each part that the person checks: the amount in full, the number as written,
the scale and the sign. On the command line, `review tasks` writes the same tasks, and
`review serve` starts the page:

```bash
groundgate review tasks --store work/store sha256:3e0c27fa...
groundgate review serve --store work/store --reviewer ana
```

`review serve` prints a start URL, `http://127.0.0.1:<port>/#<token>`. Open it in a browser. The
page shows one task at a time, in page order. The source is on the left, with the value in a
box. The question and the values are on the right. One key gives each answer:

| Key | Answer |
|---|---|
| `y` | The value is right (`confirm`). |
| `1` to `9` | This value is right, when the task has two or more values (`choose`). |
| `n` | No value is right. Select the right value in the text, then press `Enter` (`correct`). |
| `s` | The value is right, but its span is not. Select the span again, then press `Enter` (`adjust_span`). |
| `x` | The document does not give this field (`not_in_document`). |
| `u` | I cannot tell (`unsure`). Another reviewer gets the task. |
| `r` | Show the codes and the outcome of each value. |
| `k` | Keep the codes of a flagged correction, and save it. |
| `Esc`, the arrow keys | Stop a selection, and go back and forward. |

The page does not show a code or an outcome until you press `r`. A correction goes through the
same `admit` call as `review resolve`, and the page shows the outcome at once. If the gate
rejects the selection, select again. If the gate flags it, press `k` to keep its codes. If a
part is missing, select the part, for example the scale line, and press `Enter`. You can also
type the value in full. After each answer, the next task opens.

The page calls the methods of `Review`, so a script can give the same answers. Offsets count
UTF-16 code units in the text, as a browser selection does:

```python
review = Review(store, "ana")
deposit, fee = (t["task"] for t in review.queue()["tasks"])
answer = {"decision": None, "codes_kept": [], "reason_seen": False, "keys": 1, "ms": 2100}
review.answer({**answer, "task": deposit, "verdict": "confirm"})
at = text.index("$75")
check = review.check({"task": fee, "verdict": "correct", "start": at, "end": at + 3})
print(check["outcome"], check["shown"])
left = review.answer({**answer, "task": fee, "verdict": "correct", "start": at, "end": at + 3})
print(len(left["tasks"]))
```

```text
admitted 75 USD (written 75, not scaled, positive)
0
```

Each answer is a record of the answer log of `ana` for this packet. `review resolve` reads the
logs again, runs `admit` again for each correction, and gives the final value of each field:

```python
resolved = write_resolution(store, packet, reviewers=["ana"])
for line in lines(resolved.resolution):
    print(line)
```

```text
late_fee: 75 USD (corrected)
monthly_rent: 2450 USD (admitted)
security_deposit: 4900 USD (confirmed)
```

`review measures` reads each answer log of the store and gives the measures of the review for
each item kind and each field: the median time, the answers given with one key, the agreement
with blind labels and the escapes that the audit finds. A blind label is an answer to an audit
task with `reason_seen` false. These tasks have no audit, so the last two measures are 0 of 0:

```python
from groundgate.review import measures

for line in measures.lines(measures.measures(store)):
    print(line)
store.close()
```

```text
packets: 1
number: answers 2, median time 2100 ms, one key 2 of 2, agreement with blind labels 0 of 0, escapes 0 of 0 audit slots
  number late_fee: answers 1, median time 2100 ms, one key 1 of 1, agreement with blind labels 0 of 0, escapes 0 of 0 audit slots
  number security_deposit: answers 1, median time 2100 ms, one key 1 of 1, agreement with blind labels 0 of 0, escapes 0 of 0 audit slots
```

On the command line, `groundgate review measures --store work/store` prints the same lines, and
`--json` prints them as JSON. With `--set NAME --split development`, it measures only the
documents that the `splits` log of the set puts in that split, and it counts the packets that it
leaves out.

The page is for one person on one computer. The server binds to `127.0.0.1` and refuses another
`Host`. Each API request must send the token of the start URL, so keep the URL private. Any
holder of the URL can answer as the name that `--reviewer` gives. The server does not
authenticate that name. Thus a lead answer of the review policy is not an authenticated act.

The server reads the answer logs when it starts and after each answer of its own reviewer. If
another reviewer answers while the page is open, the page does not show it. To see the answers
of the other reviewers, restart `review serve`.

The frame shows the original page with one change. Each `http-equiv` and `href` name becomes
`data-equiv` and `data-href`, also in the text, so that the page cannot go to another host.
