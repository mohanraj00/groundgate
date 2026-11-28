# gg.admit()

Release: main, before 1.0.0 (spec 0.13).

`admit` decides each candidate against the text that it cites, and returns one receipt. The
decision uses fixed rules and no model.

## Call

```text
gg.admit(text, schema, candidates, policy=None, document_id=None, judgments=None, *,
         references=None, document_source=None, packs=(), doubt=None, profile=None,
         pin=None, places=None, completeness=None, outline=None) -> gg.Receipt
```

- `text`: the document, a `str` in Unicode NFC.
- `schema`, `policy`: dicts or `gg.Schema` / `gg.Policy`. `policy=None` uses the defaults.
- `candidates`: a list of candidate dicts (SPEC §2.5).
- `document_id`: copied into the receipt.
- `judgments`, `references`, `document_source`, `packs`: see the [guide](../guide.md#python-api).
- `profile`: a profile from [`load_profile`](load-profile.md). It gives the schema, the policy
  and the packs, so give `None` for `schema` and no `policy` or `packs`.
- `doubt`, `pin`, `places`, `completeness`, `outline`: the reader outputs of SPEC §2.1 and
  §4.14 to §4.17.

## Example

```python
import json

import groundgate as gg

text = open("docs/quickstart/doc.txt", encoding="utf-8").read()
schema = json.load(open("docs/quickstart/schema.json", encoding="utf-8"))
candidates = json.load(open("docs/quickstart/candidates.json", encoding="utf-8"))
receipt = gg.admit(text, schema, candidates, document_id="ira-2025")
for d in receipt.decisions:
    print(d.field, d.value, d.outcome, d.codes, d.evidence)
print(receipt.coverage, receipt.to_dict()["summary"])
```

```text
ira_limit 70000 rejected ('VALUE_NOT_IN_EVIDENCE',) (30, 36)
phaseout_start 79000 needs_verification ('QUALIFIED_VALUE',) (69, 76)
ira_limit 7000 admitted () (30, 36)
() {'admitted': 1, 'needs_verification': 1, 'rejected': 1}
```

## Result

`admit` returns a `gg.Receipt`. A user reads these attributes:

- `decisions`: a tuple of `gg.Decision`, one for each candidate, sorted by candidate digest.
- `coverage`: a tuple of `(field, "REQUIRED_FIELD_MISSING")`, one for each required field
  with no decision that is not rejected.
- `references`: a tuple of `(id, sha256, source)`, one for each reference text.
- `to_dict()`: the JSON receipt, with `summary` and `receipt_sha256`. Store this object.

A `gg.Decision` has these fields:

- `candidate_id`, `candidate_sha256`: the candidate's `id` and its digest.
- `field`, `key`, `value`, `unit`: the fact that the candidate proposed.
- `outcome`: `admitted`, `needs_verification` or `rejected`.
- `codes`: the reason codes, a tuple of strings. SPEC §5 lists them.
- `evidence`: the UTF-8 byte span `(start, end)` of the value in the text, or `None`.
- `source`, `ref`, `url`: the kind of the item that the decision rests on, and its reference.
- `missing`, `parts`: the parts that the candidate did not cite, and each part that it cited.
- `packs`: the ids of the packs that the decision read.

## Errors

`admit` raises `gg.PacketError` (a `ValueError`) when an input is invalid. Then it makes no
receipt. Some messages:

- `document text must be a string in Unicode NFC`
- `candidates must be a list`
- `schema must be an object with a 'fields' object`
- `give the schema, the policy and the packs in the profile`

A malformed candidate is not an error. It gets a `rejected` decision with `CANDIDATE_INVALID`.

## See also

- [Python API](../guide.md#python-api) in the guide.
- [`gg.verify()`](verify.md) checks a stored receipt.
- [Send reasons back to the extractor](../howto/feedback.md).
