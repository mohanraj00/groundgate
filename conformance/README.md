# Conformance vectors

Each file in `vectors/` is a complete, language-agnostic test case:

- `document`: NFC text;
- `schema` and `policy`: inputs as in SPEC §2 (`policy` may be `null`);
- `candidates`: the candidates exactly as proposed; an evidence item has UTF-8 byte offsets, or
  only a quote;
- `judgments`, `references` and `document_source` (optional): inputs as in SPEC §2.1 and §2.6;
- `packs` (optional): the vocabulary packs and kind packs that the caller gives, as in SPEC §4.8
  and §4.9. Each one is a parsed pack file. The schema names each one in its `packs` member, or
  a kind pack that the schema names needs it;
- `expected.decisions`: one `{outcome, codes}` per candidate, in input order, and `missing` where
  a part is missing. `parts` (optional) gives the `role` and `passed` of each listed part, in
  order;
- `expected.coverage`: the coverage findings.
- `expected.relations` (optional): the receipt's relation results (SPEC §5), in receipt order.
  A vector without it has a schema with no relations.
- `completeness` (optional): the packet's completeness (SPEC §4.16). `expected.completeness` is
  then the receipt's `completeness` member. A vector without it expects a receipt with no such
  member.
- `outline` (optional): the packet's outline (SPEC §4.17). `expected.outline_sha256` is then
  the receipt's `outline_sha256` member. An expected decision of a `passage` field has
  `passage_sha256`: the digest of the passage text, or null for a rejected decision. Both
  digests are computed in `build.py` from the text that the vector states.

Files in `profiles/` are profile vectors (SPEC §4.10). Each one has a `profile` in place of
`schema`, `policy` and `packs`. `expected.profile` is the receipt's `profile` member, with the
digest written by hand in `build.py`, and `expected.error` true marks an invalid packet.

Files in `pins/` are source pin vectors (SPEC §4.14). Each one has a `pin` beside the other
inputs. `expected.pin` is the receipt's `pin` member, with the digest written by hand in
`build.py`, and `expected.error` true marks an invalid packet.

Files in `places/` are places vectors (SPEC §4.15). Each one has a `places` list beside the
other inputs. Each expected decision has its `locator`, and `expected.places_sha256` is the
digest of the places, both written by hand in `build.py`. `expected.error` true marks an
invalid packet.

Files in `exports/` are export vectors (SPEC §5.2). Each one has a packet, a `review_policy`
and the `answers` of the reviewers. An answer names its slot, its reviewer and its verdict, with
`choice`, the id of the chosen candidate, or `candidate`, the candidate of a correction.
`expected.facts` and `expected.open` give the facts and the open slots of the `facts@2` export,
in order, written by hand in `build.py`. A fact gives its `answers` as the reviewer and the
verdict of each one, and its `selector` in code points. A runner adds the keys and the digests
from its own store. `task` in an open slot is true when the slot has a task.

Files in `audit/` are blind audit vectors (SPEC §4.18). `kind` names what a vector checks:

- `pick`: a `seed` and the lines of a `log`. `expected.pick` is the pick, and
  `expected.hashes` gives the first 8 bytes of the hash of each document entry.
- `log`: the lines of an invalid log, with `expected.error` true.
- `tasks`: a `profile` and a `document`. `expected.tasks` lists the document, the field and the
  key of each task. A runner adds the format member and the digest of the profile.
- `label`: one `label`, with `expected.valid`.
- `rate`: the routes of a measure and `covered`, the count of the admitted values that the audit
  labels cover. Each route has `admitted`, the count of its admitted values with a label,
  `unscored`, the count of its admitted values with no label, and its `status`. `expected.rate`
  is the next rate.

Files in `review-api/` are review API vectors (SPEC §4.20). `kind` names what a vector checks:

- `claim`: the `issuers` of a service, each with its secret in base64url, the time `now`, and
  the value of the `Authorization` header, or null for no header. `expected` gives the `actor`
  or the `error` code.
- `token`: the static `token` and the `reviewer` of a service, and the `Authorization` value.
- `task`: one `task@1` object, and `sources`: the `source` and the `ref` of each decision of
  the task in the receipt, by its index. `blind_packet` is true when the packet of the task has
  a task with the mode `audit`. `expected.served` is false for a task that is not a
  task of the API. If not, `expected` gives the members of the task response that come from the task. The
  `body` has no key of the store and no index of the receipt, and a blind task has a null
  `body`.
- `task-id`: the `key` of a service in hex and a `task` key. `expected.id` is the task ID.
- `statements`: one `model-text@1` object. `expected.statements` is the `statements` member of
  the task response.
- `page`: the tasks of the API in one store as `entries`, each with its task ID in `task` and
  with `open`, and the `query` of the list. `expected` gives the task IDs of the page and
  `next`, or the `error` code.
- `answer`: the `body` of an answer and `blind`, true for a blind task. `expected.valid` is
  true, or `expected.error` is the code. The vector checks the form of the body and the
  verdicts of a blind task. It does not check the answer against a task.
- `request`: one request to a service with the static token of the `token` vectors, the reviewer
  `ana` and an empty store. A runner puts the port in place of `{port}`. A `body` goes with its
  `Content-Length` unless `headers` gives one. `expected` gives the `status`, and the `error`
  code or the response `body`.
- `errors`: the HTTP status of each error code.

Files in `invalid/` are invalid packets. An implementation must refuse them (SPEC §2) and emit no
receipt.

The expectations are written by hand in `build.py`. The script only converts quotes into byte offsets,
independently of groundgate. After editing a vector, re-run it and commit the JSON:

```bash
uv run python conformance/build.py
```

CI rebuilds the vectors and fails if the committed JSON differs.

Every reason code appears in at least two vector files; `tests/test_conformance.py` enforces this.
