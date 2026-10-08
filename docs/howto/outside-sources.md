# Use references, web sources and the model's knowledge

Some right values are not in the document. A notice says "your standard deduction is in the rate
table", and the number is in the table. groundgate accepts three other sources of evidence:

| `source` | Who supplies the text | What groundgate checks | Default outcome |
|---|---|---|---|
| `reference` | the app | everything, as for the document | as for the document |
| `external` | the extractor | that its quote holds the value | `needs_verification` |
| `knowledge` | the extractor | nothing | `needs_verification` |

The policy decides what happens to external and knowledge evidence. This page shows each source
and each policy setting with real output. The documents, the tables and the URLs are made up.

## 1. Pass a reference

A reference is a source text that your app supplies, such as a rate table. groundgate checks a
reference item as it checks a document item. Use a reference when your app has the text.

1. Give each reference a unique `id`, its `text` in NFC, and its `source` URL or `None`.
2. Pass the references to `admit` with `references=`.
3. Give the reference ids to `gg.extractor_schema`, so the extractor can cite them.
4. Ask the extractor for a `reference` item with the `ref` and a quote of the value.

```python
import groundgate as gg

text = (
    "Notice of filing status\n\n"
    "Tax year 2026. Your filing status is married filing jointly. "
    "Your standard deduction is in the rate table for that status.\n"
)
rate_table = (
    "Rate table 2026\n\n"
    "Standard deduction\n"
    "Single\t$ 15,700\n"
    "Married filing jointly\t$ 31,400\n"
    "Married filing separately\t$ 15,700\n"
    "Head of household\t$ 23,550\n"
)
references = [
    {"id": "rates-2026", "text": rate_table, "source": "https://rates.example.org/2026/"},
]
schema = {
    "fields": {
        "standard_deduction": {
            "type": "integer",
            "unit": "USD",
            "keys": [
                "single",
                "married filing jointly",
                "married filing separately",
                "head of household",
            ],
        }
    }
}


def candidate(cid, item):
    return {
        "id": cid,
        "field": "standard_deduction",
        "key": "married filing jointly",
        "value": "31400",
        "unit": "USD",
        "evidence": [item],
    }


def show(receipt):
    for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
        where = d.ref or d.url or ""
        print(f"{d.candidate_id:<9} {d.outcome:<19} {' '.join(d.codes) or '-'}")
        print(f"{'':<9} source={d.source} {where}".rstrip())


from_table = candidate(
    "table",
    {"source": "reference", "ref": "rates-2026", "role": "value", "text": "$ 31,400"},
)
show(gg.admit(text, schema, [from_table], references=references))
```

```text
table     admitted            -
          source=reference rates-2026
```

The value is admitted with no code. The table has one row on each line, so the key on the value's
line is "married filing jointly". A role item can cite the same reference with the same `ref`.
`search_region` does not apply to a reference.

If an item cites a reference that is not in the packet, the candidate is rejected with
`CANDIDATE_INVALID`. If the quote is not in the reference, the value is rejected with
`QUOTE_NOT_FOUND`, as in the document.

## 2. Cite an external source

An external item has a `url`, a `retrieved` date and a `text`: the passage that the extractor
quotes from the page. groundgate never fetches the URL. It can check only that the quote holds
the value with its unit.

```python
web = {
    "source": "external",
    "url": "https://rates.example.org/2026/standard-deduction/",
    "retrieved": "2026-09-14",
    "text": "For 2026, the standard deduction for married filing jointly is $31,400.",
}
wrong_quote = dict(web, text=web["text"].replace("$31,400", "$31,500"))
show(gg.admit(text, schema, [candidate("web", web), candidate("web-wrong", wrong_quote)]))
```

```text
web       needs_verification  EVIDENCE_QUOTED
          source=external https://rates.example.org/2026/standard-deduction/
web-wrong rejected            VALUE_NOT_IN_EVIDENCE
          source=None
```

The default policy sends a quote that holds the value to review with `EVIDENCE_QUOTED`. A quote
that does not hold the value is rejected. No item supports that decision, so its `source` is
`None`. A person who reviews `web` opens the URL and finds the quoted passage.

## 3. Accept the model's knowledge

A knowledge item has only a `text`: the extractor's statement of the value and its basis.
groundgate cannot check it, so a knowledge item always holds the value.

```python
known = {
    "source": "knowledge",
    "text": "The 2026 standard deduction for married filing jointly is $31,400.",
}
show(gg.admit(text, schema, [candidate("known", known)]))
```

```text
known     needs_verification  EVIDENCE_STATED
          source=knowledge
```

The default policy sends it to review with `EVIDENCE_STATED`.

## 4. Configure the policy

`policy["sources"]` says what happens to external and knowledge evidence:

```json
{"sources": {"external": {"allow": [], "other": "review"}, "knowledge": "review"}}
```

- `external.allow`: a list of entries. An external item whose URL matches an entry is admitted.
- `external.other`: `review` or `reject`, for an external item that matches no entry.
- `knowledge`: `admit`, `review` or `reject`.

These settings apply only to a candidate with no value item from the document or a reference. A
candidate with a value item takes the checked path, and its outside items change nothing.

### Allow a URL prefix

An entry other than `"*"` and `"document-domain"` is a URL prefix. End it with `/`. Without the
`/`, the entry also matches a different host that starts with the same name.

```python
mirror = dict(web, url="https://rates.example.org.mirror.example.net/2026/")
candidates = [candidate("web", web), candidate("mirror", mirror)]
prefix = {"sources": {"external": {"allow": ["https://rates.example.org/"]}}}
show(gg.admit(text, schema, candidates, prefix))
```

```text
mirror    needs_verification  EVIDENCE_QUOTED
          source=external https://rates.example.org.mirror.example.net/2026/
web       admitted            ADMITTED_BY_POLICY
          source=external https://rates.example.org/2026/standard-deduction/
```

`ADMITTED_BY_POLICY` says that the policy admitted the value, not a check. The mirror URL does
not start with the prefix, so it gets `external.other`.

### Allow every URL

`"*"` matches every URL:

```python
every = {"sources": {"external": {"allow": ["*"]}}}
show(gg.admit(text, schema, candidates, every))
```

```text
mirror    admitted            ADMITTED_BY_POLICY
          source=external https://rates.example.org.mirror.example.net/2026/
web       admitted            ADMITTED_BY_POLICY
          source=external https://rates.example.org/2026/standard-deduction/
```

Use `"*"` only when a person or another step checks the external sources before they reach
groundgate.

### Allow the document's own host

`"document-domain"` matches a URL whose host is the host of the document source. Give the
document source with `document_source=`. Without it, the entry matches nothing.

```python
same_host = {"sources": {"external": {"allow": ["document-domain"]}}}
show(
    gg.admit(
        text,
        schema,
        candidates,
        same_host,
        document_source="https://rates.example.org/notices/2026/0417",
    )
)
print()
show(gg.admit(text, schema, candidates, same_host))
```

```text
mirror    needs_verification  EVIDENCE_QUOTED
          source=external https://rates.example.org.mirror.example.net/2026/
web       admitted            ADMITTED_BY_POLICY
          source=external https://rates.example.org/2026/standard-deduction/

mirror    needs_verification  EVIDENCE_QUOTED
          source=external https://rates.example.org.mirror.example.net/2026/
web       needs_verification  EVIDENCE_QUOTED
          source=external https://rates.example.org/2026/standard-deduction/
```

The host is compared whole and without its port. A subdomain is a different host.

### Reject other URLs

Set `external.other` to `reject` when an unknown source must never reach a person:

```python
strict = {"sources": {"external": {"allow": ["https://rates.example.org/"], "other": "reject"}}}
show(gg.admit(text, schema, candidates, strict))
```

```text
mirror    rejected            SOURCE_REJECTED
          source=external https://rates.example.org.mirror.example.net/2026/
web       admitted            ADMITTED_BY_POLICY
          source=external https://rates.example.org/2026/standard-deduction/
```

### Admit the model's knowledge

Set `knowledge` to `admit` when you trust the extractor's statements for this field:

```python
trusting = {"sources": {"knowledge": "admit"}}
show(gg.admit(text, schema, [candidate("known", known)], trusting))
```

```text
known     admitted            ADMITTED_BY_POLICY
          source=knowledge
```

The policy applies to every field. If you trust the extractor for some fields only, split the
schema in two. Give each `admit` call a schema with only its fields, the candidates of those
fields and its policy. Do not give both calls the full schema: each receipt then reports the
required fields of the other call as `REQUIRED_FIELD_MISSING`.

### Several outside items

A candidate can have several outside items. groundgate uses the first item with the best action:
`admit`, then `review`, then `reject`. At the same action, an external item comes before a
knowledge item. The receipt names that item's source and URL.

```python
both = dict(candidate("both", known), evidence=[known, mirror, web])
show(gg.admit(text, schema, [both], prefix))
```

```text
both      admitted            ADMITTED_BY_POLICY
          source=external https://rates.example.org/2026/standard-deduction/
```

## 5. Read the receipt

The receipt records which source each decision rests on. It also records the document source,
and the digest and source of each reference. So a later `verify` detects a change to a reference
text.

```python
import json

mixed = [from_table, candidate("web", web), candidate("known", known)]
receipt = gg.admit(
    text,
    schema,
    mixed,
    prefix,
    references=references,
    document_source="https://rates.example.org/notices/2026/0417",
).to_dict()
print(json.dumps(receipt["document"]["source"]))
for r in receipt["references"]:
    print(r["id"], r["sha256"][:23], r["source"])
for d in sorted(receipt["decisions"], key=lambda d: d["candidate_id"]):
    print(d["candidate_id"], d["source"], d["ref"], d["url"], d["evidence"])
```

```text
"https://rates.example.org/notices/2026/0417"
rates-2026 sha256:33f174eaa2e43eb6 https://rates.example.org/2026/
known knowledge None None None
table reference rates-2026 None {'start': 75, 'end': 83}
web external None https://rates.example.org/2026/standard-deduction/ None
```

- `source` is `document`, `reference`, `external` or `knowledge`.
- `ref` is the reference id, and `url` the external URL. Each is `None` (JSON `null`) otherwise.
- `evidence` is the value span in the text of the value item: here in the reference, not the
  document. An outside decision has no span.
- `references` lists each reference with its SHA-256 digest and its source, sorted by id.

Pass the same `references` and `document_source` to `gg.verify` and to the report. The page
[Review flagged facts and keep receipts](review.md) shows how.

## Why the defaults are review

groundgate admits what checked evidence supports, plus what your policy allows. It cannot check a
web page or a model's statement. The app owns the pipeline, so the app decides whether to trust
them. The default sends both to a person, so an app that changes nothing never admits a value
that groundgate did not check. `ADMITTED_BY_POLICY` in the receipt shows each value that your
policy admitted.

groundgate does not trust the document's own host by default. One host holds many pages, some of
them old, and the extractor still supplies the quote. A reference is different: your app supplies
its text, so groundgate checks it like the document. The decision record is
[ADR 0001](../adr/0001-admit-by-policy.md).
