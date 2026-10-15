# The extraction runner

Status: approved for #268. This note changes no core decision. The implementation of #270
and #271 stays in the Runner lane PR. The PR stays a draft until that work and its required
checks are complete. The runner is experimental; its held-out measure awaits #269.

I put the extraction loop in `groundgate.run`, outside `admit`. The runner controls the request,
the evidence repairs and the stopping rules. A model supplies candidates. Only `admit` decides
whether those candidates pass. A run can still admit a wrong field: a location check does not
prove meaning. The measure of #269 must report that error.

## 1. The boundary and the client

The proposed entry point is `from groundgate.run import RunPolicy, run`. Its call is:

```python
result = run(
    text,
    schema,
    client=client,
    model_id="extractor-version-1",
    policy=None,
    run_policy=RunPolicy(),
    document_id=None,
    document_source=None,
    references=None,
)
```

The app gives one synchronous function, `client(prompt: str) -> str`. It receives the complete
prompt and returns the raw JSON reply, with no Markdown fences. It owns credentials, network
access, timeout and provider transport. The runner adds no provider SDK or dependency. The
app supplies a non-blank `model_id` that identifies the model version. The runner records that
claim with every call; it cannot authenticate it. There is no hidden model call or judge call.

`text`, `schema`, `policy`, document metadata and references have the meanings of `admit`.
The runner copies and validates them before the first client call. It never changes them.
The core policy remains separate from `RunPolicy`; runner keys do not enter the core policy.
This version does not accept or create recorded judgments. An app that needs a judge keeps
using `admit` with recorded judgments until that interface has a separate design.

`RunResult` holds a final core receipt and its exact candidate list, the run record, and the
prompt and reply artifacts needed to replay it. The result also has `complete: bool`. A core
receipt can verify even when an interrupted run did not search all fields. Consumers must read
both the receipt and `complete`.

## 2. Bounded work

The proposed defaults are settings for this runner, not measured operating points:

| `RunPolicy` member | Default | Meaning |
|---|---:|---|
| `chunk_chars` | 12000 | Maximum Unicode code points per document chunk. |
| `overlap_chars` | 1000 | Maximum overlap with the preceding chunk. |
| `max_repair_rounds` | 2 | Extra calls per original candidate after its first proposal. |
| `targeted` | true | Search once for each field without a first-pass candidate. |
| `search_context_chars` | 1000 | Context on either side of a search match. |
| `max_target_regions` | 8 | Maximum regions sent for one field. |
| `max_calls` | 128 | Total calls, including initial, targeted and repair calls. |
| `max_prompt_chars` | 65536 | Maximum size of one complete prompt. |
| `max_reply_bytes` | 1048576 | Maximum UTF-8 reply size accepted for JSON parsing. |
| `max_candidates_per_reply` | 256 | Maximum proposals parsed from one reply. |
| `max_total_candidates` | 1024 | Maximum active proposals, including changed-value proposals. |
| `max_admission_bytes` | 8388608 | Total canonical bytes of stored admission packets and receipts. |

Counts must be integers, not booleans. Limits other than overlap and repair rounds are positive;
those two can be zero. Overlap must be less than chunk size. `targeted` must be a boolean.
Invalid settings fail before a call. There is no automatic transport retry, JSON retry,
model fallback, second targeted search or adaptive increase of a limit.

All calls are sequential. The order is document chunks, targeted fields in sorted field-name
order, then repairs in candidate creation order. Each eligible candidate gets at most one call
in a repair round, before the next round starts. Every call consumes the total budget, including
a failed client call. A changed-value proposal consumes its parent's call and gets zero more.

The runner plans initial chunks before it calls the client. It bounds the plan as it builds
it: when it reaches `max_calls + 1` chunks, it stops and refuses the input. It never allocates
a complete oversized plan before checking that bound. If the initial pass alone
exceeds the call budget, it refuses the input before any model work. If the budget ends after
the initial pass, it makes no targeted or repair call beyond that limit. A later budget limit
ends the run with `complete=false` and records the calls or fields it did not reach. A field
whose targeted call was not run stays unsearched; it is not recorded as targeted not found.
A repair limit is an ordinary terminal state, with the last core outcome retained. It does
not mean absence.

The aggregate candidate cap includes duplicate proposals. Active candidate payloads are also
limited to half `max_admission_bytes`, before admission. An overflow stops the run incomplete.
The admission-history budget covers the canonical JSON of each stored candidate-list/receipt
pair. When the next pair cannot fit, the runner retains the last recorded packet and receipt
and stops incomplete. It rolls back both new values and same-value evidence replacements from
that unrecorded admission, so returned candidates and receipt describe the same last packet.
Final admission records a receipt digest instead of another full copy.

This byte limit covers admission history. Call count limits the number of artifacts and
`max_prompt_chars` limits generated prompts. `max_reply_bytes` limits parsing, not retention:
an oversized raw reply is kept for replay. Search match records have the cap in section 6.
These controls are not a byte cap on the entire returned result.

## 3. Chunks and prompts from the schema

The runner takes NFC text as input. It does not read a file, extract a PDF or fetch a URL.
It splits the document at code-point boundaries. From each start, it takes a window of at
most `chunk_chars` characters. If that window reaches the document end, it emits the chunk
through the document end and stops. It creates no suffix chunk after that point. Otherwise,
it ends at the last line end in the final half of the window, or at the window boundary when
there is no such line end. The next start is the prior chunk end minus the allowed overlap,
clamped to move forward at least one character relative to the previous start. An empty
document has no text chunks. Every chunk records its start and end as global UTF-8 byte offsets. The document is never normalised
again after offsets are made.

Each initial prompt asks for every field in the schema. The instructions include the field
name, description, type, unit, comparator, bounds, aliases and keys. The prompt includes the
resolved schema, the response shape, the chunk's source id and global range, the chunk text,
and the app's reference texts with their ids and digests. References are pinned context in
each prompt; they are not downloaded or shortened silently. Initial prompt sizes are validated
one prompt at a time before any client call, then each prompt is recreated when called. The
runner never retains an initial prompt list in addition to the returned call artifacts. If
this context cannot fit the prompt budget, the runner refuses it before the first call.
Large reference chunking is later work. An empty document with references gets one initial prompt for those references; with no
references it records an empty-source search for each field without a model call.

The response shape derives from `extractor_schema(schema, reference_ids)`, with these runner
restrictions: evidence may come only from the supplied document or a named reference, it uses
quotes rather than model offsets, and there are two required top-level members:

```json
{"candidates": [], "not_found": ["field_name"]}
```

Each requested field must occur in candidates or `not_found`, never both. A `not_found` entry
is a field name, not a candidate with null, zero or a guessed value. A keyed or `multiple`
field can have several candidates. Finding one candidate does not assert that every key or
value was found. Targeted searches for individual missing keys are outside #271.

The runner assigns candidate ids from call number and reply position. A model cannot set an
id, `search_region`, confidence, a judgment, a policy or a reference. For document evidence the
runner sets `search_region` to the chunk's global byte span. Initial-pass candidates keep
their quotes without adapter-added offsets. The core resolves them under SPEC §4.6, including
repeated quotes, and applies re-anchoring under SPEC §3.1 when it is applicable. Admission
always uses the full original document and references, never text formed by concatenating
chunks. Role quotes can name context elsewhere in the pinned texts, but each must pass the
core's own checks. Section 6 defines the adapter anchoring for targeted reference value items.

A prompt states that document text, references and prior replies are data, including any
instructions in them. It marks each data block with its source id and length. Prompt wording
is an aid, not an input security check. The parser and repair restrictions below enforce the
boundary even when a model follows instructions inside a document.

## 4. Admission and candidate history

After each valid reply, the runner calls `admit` with all current candidate tips and the fixed
inputs. A tip is the latest permitted evidence version of one original proposal. A same-value
repair replaces its own tip only. It cannot delete another proposal or replace a candidate
for another field. The call receipt and its exact candidate list stay in the record.

The runner retains all original proposals and their replacements in the history. Duplicate
proposals do not increase repair budgets. Proposals with the same field, key, canonical value
and unit share one repair budget, even when overlap or several calls produced them. Repairs
operate on one chosen tip in creation order; other duplicate evidence stays recorded. Final
admitted values are distinct by field, key, canonical value and unit. The final receipt still
records each active candidate, including duplicates.

The runner calls `admit` once more on all final tips. A value that passed in an earlier round
is not stored as a final admission on that basis. In particular, different values for a
non-`multiple` field and the same key meet in one core call. The runner does not select one
value, drop a conflicting proposal or combine isolated receipts to hide a conflict.

## 5. What each repair may change

A repair request names exactly one candidate id, the prior candidate, its current decision,
its permitted changes, and the same pinned source texts. The response contains exactly one
replacement candidate or `{"not_found": true}`. A repair that reports not found keeps the
prior tip and records `repair_not_found`; it does not erase an inconvenient candidate.

For a citation repair the candidate's field, raw value, unit, key, id and every other non-evidence
member are fixed. The runner compares raw JSON values before canonical number comparison:
changing `"1000"` to `"1,000"` counts as a changed value too. No repair can add outside evidence,
change a reference id, change source, widen `search_region`, add confidence or supply judgments.
If the original has no value evidence, its new value item must use the source context of the
call that created it. The complete diff is recorded before admission.

The following table is the full allowlist. Informational codes do not grant changes. With more
than one non-informational code, every code must be eligible and changes are the union of their
listed evidence roles. Every non-listed member and role stays fixed. `SCALE_WORD` adds no
evidence role. With `SCALE_WORD` and another eligible code, the reply may repair the union of
those evidence roles while keeping the value, or change the value with those same evidence
changes as one terminal proposal. A value change never grants another role or another round.

| Decision code | Permitted change |
|---|---|
| `NO_EVIDENCE` | Add a quoted value item in the original source, plus needed sign, scale, unit, field or key evidence. |
| `QUOTE_NOT_FOUND`, `NON_VERBATIM_EVIDENCE` | Replace the value quote or its location, keeping the proposed value and source fixed. |
| `PART_MISSING` | Add or replace only roles named by `missing`. A missing unit or key also permits a field item, and requires schema aliases. |
| `SIGN_CITATION_INVALID` | Replace or remove the sign item. |
| `SCALE_CITATION_INVALID` | Replace or remove the scale item. |
| `UNIT_CITATION_INVALID` | Replace or remove the unit item; a field item is also permitted when the field has aliases. |
| `FIELD_CITATION_INVALID` | Replace or remove the field item. |
| `KEY_CITATION_INVALID` | Replace or remove the key item. |
| `KEY_NOT_AT_VALUE` | Only when key is in `missing`, aliases exist, and the value's line has a tab: add a key item and a field item. The candidate's key stays fixed. |
| `SCALE_WORD` | A scaled numeric value is permitted as a new terminal proposal, as below. Evidence changes require their own eligible codes. |

All other rejecting or flag codes end repairs for that candidate. Examples are
`VALUE_NOT_IN_EVIDENCE`, `UNIT_NOT_IN_EVIDENCE`, `QUALIFIED_VALUE`, `KEY_INVALID`,
`LOW_CONFIDENCE`, `MODEL_DOUBT`, outside-source codes and `CONFLICTING_CANDIDATES`.
A code added by a later spec version is terminal until this allowlist explicitly names it.
`feedback_message` can supply the reason text; it does not enforce the diff or grant permission
to change a value. The runner owns these checks.

A no-op repair ends that candidate's loop. A change to a locked field, key, unit, source or
other member is a protocol failure: record the reply, retain the prior tip and stop that loop.
It never enters `admit` as an approved repair. A changed value has the separate handling below.

### A changed value is a new, terminal proposal

A repair that changes only the value, or the value plus otherwise allowed evidence, is not an
evidence repair. The runner records `changed_value`, keeps the old tip, assigns a fresh id to
the new proposal and calls `admit` with both. The new proposal gets zero repair rounds even
if it has a citation code. The original's repair loop also ends. A change to another locked
member remains a protocol failure; changing the value does not excuse it.

This rule applies whether a citation prompt unexpectedly changes the value or `SCALE_WORD`
requested a scaled value. It does not automatically admit or automatically reject the new
value. The core decides once. If the old and new proposals both pass with different values,
the final core call flags their conflict. If the old proposal is rejected, a supported new
value can pass. The history says which path produced it. There is no new budget, recursion,
second changed-value call or use of the targeted pass to retry that field.

## 6. Not found and the targeted pass

The initial pass records one entry for each call and requested field: proposed candidate ids
or explicit `model_not_found`, with the chunk ranges and source digests. An omitted field is
a malformed reply, not an absence label. A field gets no document-level not-found assertion
until all planned initial chunks for it completed successfully without a candidate.

After the initial pass, the targeted set is the fields with no candidate from any initial
reply. A rejected candidate is still a candidate, so it does not trigger #271. Neither do a
missing key in an otherwise represented field, a repair failure or an exhausted repair budget.
If any initial reply failed or was malformed, the runner stops incomplete before targeted
calls; it does not turn a transport failure into a silent miss.

The targeted search is a fixed script. A field's title is its schema field name with each
underscore replaced by a space. Queries come in this order: the full title, each full alias in
schema order, individual words of the title in text order, then individual words of the
description in text order. If aliases or the description are absent, their step adds no
queries. An individual word is a maximal run of Unicode letters or digits with at least three
code points. The minimum length applies to individual words, not full titles or aliases.

The script collapses whitespace, trims each query, skips empty queries and case-folds for
comparison. It keeps the first query when these forms are duplicates, so an earlier title or
alias wins the tie. It searches whole words or phrases with flexible whitespace. It does not
use a model, stemming, an embedding or words from model output. Keys are included as context
in the prompt, not searched alone: common year headings would match unrelated tables. Every
query and searched source is recorded. Match records are bounded as below.

The script searches the full document and each supplied reference. Query order defines match
priority: title, aliases, title words, then description words. Within one query, document hits
come first, then references by id, then byte position. It streams matches and retains at most
1024 match records in that order. It counts later matches in `omitted_matches` without
allocating records or windows for them. A retained match selects `search_context_chars` characters on either side,
clamped to its source. It merges overlapping regions in the same source and gives each merged
region its best query rank. It selects at most `max_target_regions` by rank, then source and
byte start. `omitted_regions` counts discarded regions from that bounded pool; it does not
estimate regions from omitted matches. Either cap records `search_truncated`. The selected
regions are sent in document, reference-id and byte-start order for stable quote anchoring.

The record cap does not cap search work. Each query scans the supplied sources to count all
hits. The runner builds and caches a casefold once per source across all fields and queries.
Length-preserving folds use identity boundaries; expansions use compact array breakpoints.
Runner byte offsets also use compact multibyte deltas, not a per-character reverse dictionary.
Search memory grows with the supplied texts and cached folds; search CPU grows with source
length and query count. No model-call budget is claimed to bound those scans.

The reply may quote any one retained region but may not combine two regions into a new quote.
For document evidence the runner chooses the first retained region that holds the whole value
quote and sets it as `search_region`. The core then resolves that quote under SPEC §4.6.
For a reference value item, the runner first acts as an adapter: it finds the first whole
occurrence within the retained regions in region order and then byte order, using the quote
matching rules in SPEC §4.6. Its admission packet uses that occurrence's valid global UTF-8
`start` and `end` offsets without `text` on the value item. The raw quote stays in the reply
artifact and history. This produces an explicit-span candidate before `admit`; it does not
redefine the core's choice among quote occurrences. Under SPEC §3.1, an offsets-only value
item cannot re-anchor. The core checks the resulting candidate with the unchanged SPEC rules,
and replay verifies that same packet. This adapter output confines the value location to the
targeted reference region without changing the policy. I accept the cost of pinning the first
permitted occurrence even when initial-pass alias-aware quote resolution would choose a later
one. A two-occurrence fake-client test records the resulting field review. This is an adapter
choice, not a change to the decision on an unchanged packet.
A quote absent from every permitted region is a protocol failure; it cannot expand the search.
Other evidence roles keep their core checks in the pinned text.

One prompt includes all retained regions and asks only for that field. If they do not fit the
prompt limit, the script removes regions from the end until they fit and records that limit.
If none fit, the field is `search_limit` and the run is incomplete. A single-field reply uses
the initial envelope. It can give candidates, or explicit `not_found`. Targeted candidates
have the same repair rules and budget as initial candidates. There is one targeted call per
field, not one per match.

If no query matches, there is no client call: record `search_no_match`, the actual queries,
sources and zero regions. If the model returns no candidate, record `targeted_not_found` with
the searched regions and the call. These are statements about a bounded search, not proof
that a document lacks the value. Truncated searches remain marked as truncated even after
`targeted_not_found`. When no non-empty query remains after trimming, the record says `search_no_terms`. A field
name made only of underscores can reach this state when it has no aliases or description.

## 7. Invalid replies and failures

Model replies are untrusted strings. The parser accepts exactly one JSON object, refuses
trailing text, duplicate object keys, non-finite numbers, integers outside the core's safe
range, wrong top-level members, excessive candidate counts and unknown requested fields.
It validates the envelope and candidate shapes without adding a runtime JSON Schema package.
It rejects model ids, source ids or offsets that the runner did not permit. The runner
refuses the entire envelope on a structural error; it never salvages a candidate from an
invalid reply. The runner never executes code, invokes a tool, opens a path or follows a URL
from a reply.

A structural reply error ends the run incomplete, with its prompt digest, raw reply digest,
error category and completed receipts. It is not retried. A structurally valid candidate that
fails a core content check gets the normal rejected decision and follows the repair table.
A reply over `max_reply_bytes` is hashed and recorded but never JSON-parsed. Its entire raw
string remains in the returned artifacts so replay can reproduce the size failure. Thus a
client can return an artifact larger than that setting. The limit does not bound transport or
reply-retention memory; the app client owns any transport cap before returning. Artifact
storage is owned by the app; the runner creates no paths from model text.

Invalid caller inputs raise `PacketError` or a runner input error before the first call,
without a core receipt. A client exception is recorded as `client_error`; the runner stops
incomplete and retains completed work. It records a fixed error category and the exception
type, not an arbitrary exception string that may contain a secret. A runtime core packet
error or unexpected internal failure raises `RunnerError` with its `record` set to the partial
run record. It is never converted to a not-found result or an admitted candidate. A call timeout belongs to the
client; the synchronous interface cannot force an uncooperative client to return.

The final result distinguishes ordinary no candidate, final review, final rejection, repair
limit, protocol failure and incomplete run. The last three do not claim that the field is
absent. Field states are a history of attempted work, not an active candidate inventory.
`proposed` can precede a resource rollback. A limit entry lists retained and dropped candidate
ids and ids whose evidence version was reverted. Rollback restores the last accepted raw
candidates as well as their admission packet. The returned candidate list and core receipt
are the active inventory. No history state overrides a core outcome.

## 8. The run record and replay

The core receipt format stays unchanged. A separate `groundgate-run/1` record holds the runner
version, core spec version, document and reference digests, resolved schema and policy digests,
model id, every `RunPolicy` setting, chunk plan, search plan and terminal field states.

For each call the record holds its sequence number, phase, field or candidate ids, repair
round, preceding entry digest, complete prompt digest, model id, raw reply digest and length,
parse or client error, permitted and actual diff, exact admission packet candidate list,
and the core receipt or its digest. Search-only and final-admission steps have entries too.
Raw prompts and replies live in the returned artifacts; the record refers to their digests.
Raw-reply digests cover exact UTF-8 bytes, including whitespace. Prompt digests cover the
exact string given to `client`, encoded as UTF-8. Client errors have no reply digest.

Runner digests use their own prefix, `groundgate-run/1:<kind>` followed by a zero byte and the
canonical JSON or exact UTF-8 artifact bytes. They do not reuse a spec-dependent core digest
prefix. The run manifest covers every entry digest and the final core receipt digest. There
are no wall-clock times, host paths, credentials or random ids in this deterministic content.
An app may keep times separately. The chain detects a changed or removed entry when checked
against the saved manifest; it is not a signature or proof of the model's identity.

`replay(record, artifacts, text, schema, policy, references)` makes no model call. It checks
input digests, rebuilds chunks and prompts, verifies artifact and chain digests, re-parses
replies, enforces the same diffs and budgets, and runs `verify` for each core receipt and the
final receipt. Before building any prompt, replay bounds the initial chunk plan by the
recorded chunk-plan length or call and limit entries, as well as the declared budget. An untrusted header cannot
authorize a plan larger than those saved entries. The recorded chunk plan also bounds replay
of an initial pass interrupted before every planned call ran. It validates each saved chunk
and compares the regenerated source and byte ranges before constructing prompts. Replay
allocation ceilings for candidates and admission history are further bounded by the actual
canonical record and artifact byte counts, even when the header declares larger budgets.
It checks not-found and search-only entries too. Missing artifacts, changed
settings, unknown runner versions or a different core version fail replay. A client-error
entry can verify the record of the attempted call, not reproduce the external failure.
Replaying recorded replies is deterministic; a fresh model run need not produce those replies.

## 9. Checks and the release measure

Tests use a fake client for chunk boundaries, schema prompts, source quoting, every permitted
repair role, forbidden diffs, no-ops, mixed terminal codes, changed-value stopping, cross-round
conflicts, duplicates, limits, not-found states, targeted search order, malformed replies,
client failures and byte-for-byte replay. Tests need no keys, network or model. The how-to
in `docs/howto/feedback.md` replaces the application loop with the runner.

Search terms, region sizes and budgets can be chosen on the development part of #269 only.
I freeze them before running its held-out part. The baseline, final admitted error rate with
both one-sided bounds, reviews, silent misses, miss rate and escapes come from that set's
`results.json`, using its field and document units. I publish no measure from this design note.
The held-out measure waits for the kinds, field lists, downloads and blind labels of #269.
No pack, relation check, judge route, router or reader from the later design is built here.

## 10. Approval

The maintainer approved this design on 2026-10-15 before implementation of #270 and #271.
The approval covers evidence-only repairs, one admission and no further repairs for a changed
value, a final admission over all active proposals, and one scripted targeted pass. The design
and implementation stay in the same Runner lane PR.
