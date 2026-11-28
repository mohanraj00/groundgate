# gg.verify()

Release: main, before 1.0.0 (spec 0.13).

`verify` decides the candidates again from the same inputs, and compares the result with a
stored receipt byte for byte. Use it to show that a receipt matches its inputs.

## Call

```text
gg.verify(receipt, text, schema, candidates, policy=None, judgments=None, *,
          references=None, document_source=None, packs=(), pack_dir=None, doubt=None,
          profile=None, pin=None, places=None, completeness=None, outline=None)
          -> gg.Verification
```

- `receipt`: the JSON object that `Receipt.to_dict()` returned, or the stored JSON.
- The other arguments: the same inputs that you gave to [`admit`](admit.md).
- `pack_dir`: a folder of pack files. `verify` reads it as untrusted input, and uses a file
  only when its digest is the digest in the receipt. Give the schema as a dict with it.
- `profile`: give no `schema`, `policy`, `packs` or `pack_dir` with it.

## Example

```python
import json

import groundgate as gg

text = open("docs/quickstart/doc.txt", encoding="utf-8").read()
schema = json.load(open("docs/quickstart/schema.json", encoding="utf-8"))
candidates = json.load(open("docs/quickstart/candidates.json", encoding="utf-8"))
stored = gg.admit(text, schema, candidates).to_dict()
print(gg.verify(stored, text, schema, candidates))
print(gg.verify(stored, text.replace("7,000", "8,000"), schema, candidates).problems[0])
```

```text
Verification(ok=True, problems=())
document differs from the re-derived receipt
```

## Result

`verify` returns a `gg.Verification` with two fields:

- `ok`: `True` when each byte of the receipt re-derives.
- `problems`: a tuple of strings, one for each difference. It is `()` when `ok` is `True`.

A receipt from another spec version gives one problem, and `verify` checks nothing more. The
problem names the release that implements that version, when there is one (SPEC §8.6). A pack
that `verify` cannot find also gives one problem and no more checks.

## Errors

`verify` raises `gg.PacketError` when an input is invalid:

- `receipt must be a JSON object`: `receipt` is not a mapping.
- The messages of [`admit`](admit.md#errors), for an invalid text, schema, policy or other
  input.

## See also

- [Python API](../guide.md#python-api) in the guide, "Verify a receipt with packs".
- [Keep pack files with receipts](../howto/keep-packs.md).
