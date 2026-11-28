# groundgate.report.render()

Release: main, before 1.0.0 (spec 0.13).

`render` gives one self-contained HTML page for a receipt. The page shows the document with each
evidence span marked by outcome, and one card for each decision with its codes.

## Call

```text
render(receipt, text, candidates, *, schema=None, policy=None, layout=None, title=None,
       judgments=None, references=None, document_source=None, packs=(), pack_dir=None,
       doubt=None, pin=None, places=None, completeness=None, outline=None) -> str
```

- `receipt`: the receipt as a dict, `Receipt.to_dict()`.
- `text`, `candidates`: the inputs of `admit`. The candidates give the quotes on each card.
- `schema`: with it, `render` runs `verify` first, and the page says if the receipt matched.
  Without it, the page says `receipt not verified`.
- `policy`, `judgments`, `references`, `document_source`, `packs`, `doubt`, `pin`, `places`,
  `completeness`, `outline`: give the values that `admit` got, so that `verify` can match.
- `pack_dir`: a folder of pack files for `verify`.
- `layout`: the `Layout` of a PDF reading, for page numbers.
- `title`: the page title. The default is the document id, or `Admission report`.

## Example

```python
import json
from pathlib import Path

import groundgate as gg
from groundgate.report import render

quick = Path("docs/quickstart")
text = (quick / "doc.txt").read_text(encoding="utf-8")
schema = json.loads((quick / "schema.json").read_text())
candidates = json.loads((quick / "candidates.json").read_text())
receipt = gg.admit(text, schema, candidates).to_dict()
html = render(receipt, text, candidates, schema=schema, title="IRA limits")
print(html[:15], "<title>IRA limits</title>" in html)
print("receipt verified" in html, "<script" in html)
```

```text
<!doctype html> True
True False
```

Write the string to a file and open it in a browser.

## Result

A `str` with one HTML page. The page has no scripts and loads nothing. A Content-Security-Policy
forbids both, so a hostile document cannot run code in the browser. With `schema`, the status
line is `receipt verified` or `receipt does not match its inputs`.

## Errors

`render` raises the errors of `verify` when you give `schema`:

- `PacketError`: `receipt must be a JSON object`.
- `PacketError`: `packs must be a list of pack objects`, and the other faults of an input.

A receipt that does not match its inputs is not an error. The page shows the mismatch.

## See also

- [Guide: Report](../guide.md#report)
- [Review flagged facts and keep receipts](../howto/review.md)
- [Keep pack files with receipts](../howto/keep-packs.md) for `pack_dir`.
