# Conformance vectors

Each folder holds one kind of language-agnostic vector:

| Folder | Vectors | SPEC |
|---|---|---|
| `vectors/` | Packets and their decisions. Each reason code is in at least two of them. | §2, §3 |
| `invalid/` | Invalid packets that an implementation must refuse. | §2 |
| `profiles/` | Profile vectors. | §4.10 |
| `pins/` | Source pin vectors. | §4.14 |
| `places/` | Places vectors. | §4.15 |
| `exports/` | Export vectors. | §5.2 |
| `audit/` | Blind audit vectors. | §4.18 |
| `events/` | Calibration event vectors. | §4.19 |
| `review-api/` | Review API vectors. | §4.20 |
| `receipts/` | Packets with their full receipts. | §5 |
| `store/` | The store contract, in one file. | §9 |

`uv run python conformance/build.py` writes every folder except `store/`, and prints how many
vectors of each kind it wrote. `store/` has its own script and its own
[README](store/README.md). The sections below define the files of each folder.

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

Files in `events/` are calibration event vectors (SPEC §4.19). `kind` names what a vector checks:

- `event`: one `event`. `expected.valid` is true for a valid event.
- `log`: a `profile` and the `records` of its events log, without the chain members.
  `expected.valid` is true for a valid log, and `expected.counted` lists the origin id of each
  event that counts, in log order. An invalid log has an empty `counted`.

Files in `review-api/` are review API vectors (SPEC §4.20). `kind` names what a vector checks:

- `claim`: the `issuers` of a service, each with its secret in base64url, the time `now`, and
  the value of the `Authorization` header, or null for no header. `expected` gives the `actor`
  or the `error` code.
- `token`: the static `token` and the `reviewer` of a service, and the `Authorization` value.
- `task`: one `task@1` object, and `sources`: the `source` and the `ref` of each decision of
  the task in the receipt, by its index. `expected.served` is false for a task that is not a
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
- `group`: the `tasks` of the API of one packet, each with its ID in `task`, `field`, `key` and
  `blind`, the records of each actor in `logs` with the `task` and the `verdict`, the `actor` and
  `agree`. `expected.group` gives the tasks of the group of the actor, in the order of `tasks`.
- `start`: `recorded_agree` is null before the first start. `agree` is the value for the new
  start. `answer_log` is true when there is an answer log. `expected.agree` gives the value in
  the store after the start or refusal. `expected.error` gives the message for a refusal.
- `left-out`: the `count` of the decisions of the receipt, the `tasks` of one packet in the
  store, each with `task`, `mode` and the receipt indexes of its `decisions`, and the `task` of
  a correction. `expected.decisions` gives the indexes that the check leaves out, in addition to
  those of its own slot, in order.
- `request`: one request to a service with the static token of the `token` vectors, the reviewer
  `ana` and an empty store. A runner puts the port in place of `{port}`. A `body` goes with its
  `Content-Length` unless `headers` gives one. `expected` gives the `status`, and the `error`
  code or the response `body`.
- `errors`: the HTTP status of each error code.

Files in `receipts/` are receipt vectors (SPEC §5). Each one is a packet with its full receipt:

- the inputs of `vectors/`, and `document_id`, `doubt`, `profile`, `pin` and `places` where a
  vector gives them. A vector with a `profile` has no `schema`, `policy` or `packs`;
- `expected.receipt`: the receipt, with each member and `receipt_sha256`. An implementation
  gives the same object. The order of the members in the file is not part of the contract.

Each member of the receipt is written by hand in `build.py`: each decision with its spans, the
schema and the policy after defaults, and the lists in receipt order. The script does four
things, and none of them is a run of groundgate:

- it adds the digests of SPEC §6, the profile digest (§4.10) and the pin digest (§4.14) with
  `hashlib`;
- it sorts the decisions and the judgments by `candidate_sha256`;
- it copies `document.id` and `document.source` from the packet;
- it applies four presence rules of SPEC §5: `answer` only for the question `key`, a null
  `doubt_sha256` for an empty list, and `places_sha256` and `outline_sha256` only when the
  packet gives the input.

The vectors hold each member of the tables of SPEC §5. `receipt-01-required-members` has only
the members that are always present.

A receipt vector does not change. `receipts/SHA256SUMS` lists the SHA-256 of each file, and
`tests/test_conformance.py` fails when a file changes, is not in the list, or is removed while
its line stays. The test cannot see a file that is removed together with its line: the review
of this level 1 path sees that. Check a copy with `shasum -a 256 -c SHA256SUMS` in `receipts/`.
A release that keeps the spec version only adds vectors: add the file and one line to the list,
and change no other line. Do not write the list from a script.

Files in `invalid/` are invalid packets. An implementation must refuse them (SPEC §2) and emit no
receipt.

`store/vectors.json` is the store contract (SPEC §9.7) as vectors. [store/README.md](store/README.md)
defines the file, the runner and the report.

The expectations are written by hand in `build.py`. The script only converts quotes into byte offsets,
independently of groundgate. After editing a vector, re-run it and commit the JSON:

```bash
uv run python conformance/build.py
```

CI rebuilds the vectors and fails if the committed JSON differs.

Every reason code appears in at least two vector files; `tests/test_conformance.py` enforces this.
