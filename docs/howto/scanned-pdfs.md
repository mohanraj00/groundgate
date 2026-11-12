# Read scanned PDFs

A scanned page is an image. It has no text layer, so `groundgate read` gives no text for it
until OCR reads the image. An OCR word can be wrong, and the text is then the reader's text, not
the printed page. This page shows how to read a scan, what groundgate does with the words that
OCR is not sure of, and how a person checks them. The lease and the numbers are made up.

The [guide](../guide.md) has the limits of OCR. SPEC §2.1 and §3.3 in [SPEC.md](../../SPEC.md)
are the normative rules for doubt.

## 1. Install the OCR program

OCR needs the `ocr` extra and the `tesseract` program:

```bash
pip install 'groundgate[ocr]'
brew install tesseract          # or: apt install tesseract-ocr
```

If one of them is not installed, `read --ocr` stops with an error that names the fix.
groundgate finds `tesseract` only in the absolute folders of `PATH`, never in the current
folder.

## 2. Read the scan with --ocr

OCR is off by default. Without `--ocr`, a page with no text layer gives a warning and no text:

```bash
groundgate read lease.pdf
```

```text
groundgate: warning: page 1 has no text layer; OCR the PDF first (for example with ocrmypdf), or read it with --ocr
```

With `--ocr`, groundgate renders each page with no text layer and an image at 300 dpi, and runs
`tesseract` on it. Add `--document` to keep the confidence of each word:

```bash
groundgate read lease.pdf --ocr -o doc.txt --document doc.json
```

`doc.txt` holds the text of the engine, one line of words on each line and a blank line between
two paragraphs:

```text
LEASE SUMMARY

Annual fee: $500 per year.
Deposit: $1,200.
```

OCR gives no tables. A scanned table reads as lines of words, with no tab between the cells.
So a table value on a scan has no column rule (see [Check values in financial tables](tables.md)).

groundgate runs `tesseract` with no shell, in English (`-l eng`), with one thread and a time
limit of 120 seconds for each page. So the same tesseract version gives the same text. One read
sends at most 200 pages to OCR. For a longer scan, read fewer pages with `--pages`.

The reader in `doc.json` names both versions, for example:

```json
{"name": "groundgate.read+tesseract", "version": "0.14.0+tesseract.5.5.2"}
```

So a new tesseract version gives a new reading key in a store. `read --store --ocr` does not use
the reading cache.

## 3. The doubt of an OCR word

`tesseract` gives each word a confidence from 0 to 100. The `doubt` member of `doc.json` lists
the byte span of each word with a confidence below 100, and the confidence from 0 to 1. On this
scan, each word is there, from 0.9614 to 0.9667:

```json
[{"confidence": 0.9614, "end": 5, "start": 0}, {"confidence": 0.9615, "end": 13, "start": 6},
 {"confidence": 0.9666, "end": 21, "start": 15}, {"confidence": 0.9666, "end": 26, "start": 22},
 {"confidence": 0.9653, "end": 31, "start": 27}, {"confidence": 0.9657, "end": 35, "start": 32},
 {"confidence": 0.9667, "end": 41, "start": 36}, {"confidence": 0.9642, "end": 50, "start": 42},
 {"confidence": 0.9667, "end": 58, "start": 51}]
```

Give this list to `admit` as `doubt` (spec 0.12, #535). If the value item, or a role item that
passes, shares a byte with a doubt span, the decision gets `READ_DOUBT` and goes to review. The
code below uses the text and the doubt of the scan above, so it runs with no OCR program.

```python
import groundgate as gg

text = "LEASE SUMMARY\n\nAnnual fee: $500 per year.\nDeposit: $1,200."
doubt = [
    {"confidence": 0.9614, "end": 5, "start": 0},
    {"confidence": 0.9615, "end": 13, "start": 6},
    {"confidence": 0.9666, "end": 21, "start": 15},
    {"confidence": 0.9666, "end": 26, "start": 22},
    {"confidence": 0.9653, "end": 31, "start": 27},
    {"confidence": 0.9657, "end": 35, "start": 32},
    {"confidence": 0.9667, "end": 41, "start": 36},
    {"confidence": 0.9642, "end": 50, "start": 42},
    {"confidence": 0.9667, "end": 58, "start": 51},
]
schema = {
    "fields": {
        "annual_fee": {"type": "integer", "unit": "USD", "aliases": ["annual fee"]},
        "deposit": {"type": "integer", "unit": "USD", "aliases": ["deposit"]},
    }
}


def candidate(cid, name, value, quote, label):
    evidence = [
        {"source": "document", "role": "value", "text": quote},
        {"source": "document", "role": "field", "text": label},
    ]
    return {
        "id": cid,
        "field": name,
        "key": None,
        "value": value,
        "unit": "USD",
        "evidence": evidence,
    }


candidates = [
    candidate("fee", "annual_fee", "500", "$500", "Annual fee"),
    candidate("deposit", "deposit", "1200", "$1,200", "Deposit"),
]


def show(receipt):
    for d in receipt.decisions:
        print(f"{d.candidate_id:<8} {d.outcome:<19} {' '.join(d.codes)}".rstrip())


show(gg.admit(text, schema, candidates))
print()
show(gg.admit(text, schema, candidates, doubt=doubt))
```

```text
fee      admitted
deposit  admitted

fee      needs_verification  READ_DOUBT
deposit  needs_verification  READ_DOUBT
```

Without the doubt, both values are admitted: the text holds each quote. With the doubt, both go
to review. The text is what the engine read, and the engine was not sure of these words.

A doubt span counts when its confidence is below `policy.min_read_confidence`. The default is
`1`, so each doubt span counts, and each value on a scan goes to review. You can set a lower
limit:

```python
show(gg.admit(text, schema, candidates, {"min_read_confidence": 0.9}, doubt=doubt))
```

```text
fee      admitted
deposit  admitted
```

That limit is your choice. I have not measured one, and a word with a confidence of 0.96 can
still be wrong. A recorded judgment never removes `READ_DOUBT`.

## 4. Where the doubt goes

- `admit` in Python takes `doubt=`. The receipt names the digest of the list in
  `document.doubt_sha256`, so the receipt shows which doubt it used.
- `extract` takes the doubt of the `Document` that you give it, and gives it to each `admit` of
  the run. See [Read documents](documents.md).
- `admit_packet` takes `doubt=` too. The packet in the store keeps the list, so `verify` from the
  store decides again with it (#573).
- The `admit` command takes no doubt. A receipt from `groundgate admit` on OCR text has no
  `READ_DOUBT`. Use Python or `extract` for scanned documents.

## 5. Check a value against the scan

A person who checks a value on a scan must see the scan, not only the reader's text. The review
page does this (#537). When the packet names a reading by the tesseract reader, the page shows
a crop of the scan next to the text at each place of the task.

- The crop is the box of the place with 24 points of the page on each side, cut at the page
  edge. It renders in gray at 300 dpi.
- The page shows a crop at each place of the document, also where the engine has no doubt. So
  the crop does not tell the person why the task is there.
- The crop is a view. It changes no task, answer or template.
- Without the `ocr` extra, the page shows the text and the line "Install groundgate[ocr] to see
  the scan".
- After `forget` of the source, the page says that the scan is gone and shows the text only.

The packet must name the reading, so give `admit_packet` the reading key that
`read --store --ocr` prints. [Review flagged facts](review.md) shows how to make the tasks and
start the page.

## Checklist

- Install `groundgate[ocr]` and `tesseract`.
- Read the scan with `groundgate read FILE --ocr -o doc.txt --document doc.json`.
- Give the `doubt` of `doc.json` to `admit`, or give the `Document` to `extract`.
- Keep `min_read_confidence` at 1 unless you have measured a lower limit on your scans.
- Store the packet with the reading key, so the review page shows the crop of the scan.
