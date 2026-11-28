# gg.digest()

Release: main, before 1.0.0 (spec 0.13).

`digest` gives the SHA-256 digest of an object as groundgate computes it (SPEC §6). Use it to
find the candidate that a decision names, or to check a digest in a receipt.

## Call

```text
gg.digest(kind, obj) -> str
```

- `kind`: the domain of the digest, an ASCII string. The receipt uses `candidate`, `document`,
  `schema`, `policy`, `reference` and `receipt`.
- `obj`: a JSON value: a dict, a list, a string, an integer, a float, `True`, `False` or
  `None`.

The digest is SHA-256 over the bytes `groundgate/<spec version>:<kind>`, a zero byte, and the
canonical JSON of `obj` from [`gg.jcs()`](jcs.md) in UTF-8. The spec version is in the prefix,
so the digests change with each spec version.

## Example

```python
import json

import groundgate as gg

text = open("docs/quickstart/doc.txt", encoding="utf-8").read()
schema = json.load(open("docs/quickstart/schema.json", encoding="utf-8"))
candidates = json.load(open("docs/quickstart/candidates.json", encoding="utf-8"))
receipt = gg.admit(text, schema, candidates)
for d in receipt.decisions:
    candidate = next(c for c in candidates if gg.digest("candidate", c) == d.candidate_sha256)
    print(d.outcome, candidate["value"])
print(gg.digest("document", {"text": text}) == receipt.document_sha256)
```

```text
rejected 70000
needs_verification 79000
admitted 7000
True
```

## Result

A string `sha256:` with 64 lowercase hex digits after it.

## Errors

`digest` raises the errors of [`gg.jcs()`](jcs.md#errors) for an object that is not JSON
data. A `kind` that is not ASCII raises `UnicodeEncodeError`.

## See also

- [Python API](../guide.md#python-api) in the guide.
- [`gg.jcs()`](jcs.md) gives the canonical JSON that the digest reads.
