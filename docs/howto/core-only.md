# Use only the core: admit, verify and the receipt

groundgate is one package, but you do not need all of it. If your app already has a reader, a
model loop and a review queue, you need three things: `admit`, `verify` and the receipt. They are
in the core, and the core has no dependencies. This page uses only them.

## 1. Install with no extra

```bash
pip install groundgate
```

This installs groundgate and nothing else. Each part that needs another package is behind an
extra (`[pdf]`, `[ocr]`, `[langextract]`) and imports it only when you call it. The package
metadata shows that the core requires no package:

```python
from importlib.metadata import requires

print([r for r in requires("groundgate") or [] if "extra ==" not in r])
```

```text
[]
```

## 2. Admit your model's candidates

Your app gives three inputs: the text, the schema and the candidates. The text is a Python `str`
in Unicode NFC. Your reader makes it, so normalise it yourself. The candidates are what your
model returned, in the shape of [the extractor's output](../guide.md#the-extractors-output).

```python
import unicodedata

import groundgate as gg

text = unicodedata.normalize(
    "NFC",
    "INVOICE 4471\nNet amount: $12,400. Tax: $992.\nTotal due: $13,392 within 30 days.\n",
)
schema = {
    "fields": {
        "net_amount": {"type": "integer", "unit": "USD", "required": True},
        "tax": {"type": "integer", "unit": "USD"},
        "total_due": {"type": "integer", "unit": "USD"},
    }
}
candidates = [  # what your model returned
    {"field": "net_amount", "value": "12400", "unit": "USD", "evidence": [{"text": "$12,400"}]},
    {"field": "tax", "value": "992", "unit": "USD", "evidence": [{"text": "$992"}]},
    {"field": "total_due", "value": "13932", "unit": "USD", "evidence": [{"text": "$13,392"}]},
]
```

If your reader gives a confidence for each word, as OCR does, give `admit` the doubt list too.
It is the list of spans that the reader read with a low confidence, in UTF-8 byte offsets, in
text order (SPEC §2.1). groundgate cannot make this list from the text: only your reader knows
it. Here the reader doubted `$992`:

```python
start = text.encode("utf-8").index(b"$992")
doubt = [{"start": start, "end": start + len(b"$992"), "confidence": 0.62}]

receipt = gg.admit(text, schema, candidates, document_id="invoice-4471", doubt=doubt)
for d in receipt.decisions:
    print(f"{d.outcome:<19} {d.field:<11} {d.value:<6} {' '.join(d.codes)}".rstrip())
```

```text
needs_verification  tax         992    READ_DOUBT
rejected            total_due   13932  VALUE_NOT_IN_EVIDENCE
admitted            net_amount  12400
```

The model swapped two digits of the total, so the quote does not hold its value. The tax is in
the text, but the reader doubted it, so a person checks it. Send `needs_verification` to your
review queue, and store only `admitted` values. If your reader has no confidences, leave out
`doubt`.

## 3. Keep the receipt with its inputs

A receipt is a JSON object. `verify` re-derives it from the same inputs, so keep the inputs with
it. A folder for each document is enough:

```python
import json
import tempfile
from pathlib import Path

folder = Path(tempfile.mkdtemp()) / "invoice-4471"
folder.mkdir()
(folder / "doc.txt").write_text(text, encoding="utf-8")
for name, obj in [
    ("schema", schema),
    ("candidates", candidates),
    ("doubt", doubt),
    ("receipt", receipt.to_dict()),
]:
    (folder / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
```

Write `doc.txt` as UTF-8 and read it back the same way. Do not let the platform change the line
ends: the receipt holds the digest of the exact text.

## 4. Verify the receipt later

```python
def load(name):
    return json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))


kept = (folder / "doc.txt").read_text(encoding="utf-8")
check = gg.verify(load("receipt"), kept, load("schema"), load("candidates"), doubt=load("doubt"))
print(check.ok)

no_doubt = gg.verify(load("receipt"), kept, load("schema"), load("candidates"))
print(no_doubt.ok, no_doubt.problems[0])
```

```text
True
False document differs from the re-derived receipt
```

Give `verify` every input that you gave `admit`. Without the doubt list, the receipt does not
re-derive: the receipt names the digest of the doubt list in `document.doubt_sha256`.
[Review and keep receipts](review.md) covers a receipt from an older spec version and how to pin
the groundgate version.

## What you can ignore

A core-only app never imports or runs these parts:

| Part | What it does | Use instead |
|---|---|---|
| `groundgate.read`, `groundgate read` | Turns a PDF, HTML, DOCX or XLSX file into NFC text | Your reader |
| `groundgate.extract` | Runs a model and repairs its evidence | Your model loop |
| `groundgate.store`, `groundgate store`, `--store` | Keeps inputs, receipts and packets in a folder | Your own storage, as in section 3 |
| `groundgate.review`, `groundgate review`, `groundgate report` | Makes review tasks, pages and answers | Your review queue |
| `groundgate.calibrate`, `groundgate calibrate` | Measures a judge's thresholds | Not needed without a judge |
| `groundgate.adapters` | Reads LangExtract output | Your own candidates |

The command line has `admit` and `verify` too, but `admit` there does not take a doubt list yet
(#711). If your reader gives confidences, call `gg.admit` from Python.
