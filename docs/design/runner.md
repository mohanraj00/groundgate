# The extraction runner

Status: approved for #268. This note changes no core decision. The implementation of #270
and #271 stays in the Runner lane PR. The PR stays a draft until that work and its required
checks are complete. The runner is experimental; its held-out measure awaits #269.

I put the extraction loop in `groundgate.extract`, outside `admit`. The runner controls the request,
the evidence repairs and the stopping rules. A model supplies candidates. Only `admit` decides
whether those candidates pass. A run can still admit a wrong field: a location check does not
prove meaning. The measure of #269 must report that error.

## 1. The boundary and the client

The proposed entry point is `from groundgate.extract import RunPolicy, extract`. Its call is:

```python
result = extract(
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

`RunResult` holds a final core receipt and its exact candidate list, the run log, and the
objects needed to replay it (section 8). The result also has `complete: bool`. A core
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
| `drop_rounded` | false | Drop a rounded figure beside the exact figure (section 4, #319, #331). |
| `max_region_chars` | 6000 | Maximum size of one search region. A larger region is cut (section 6, #382). |
| `max_sweep_calls` | 2 | Calls of the second sweep for one field after `search_limit` (section 6, #382). |

Counts must be integers, not booleans. Limits other than overlap, repair rounds and sweep calls
are positive; those three can be zero. Overlap must be less than chunk size. `targeted` and `drop_rounded` must
be booleans. Invalid settings fail before a call. There is no automatic transport retry, JSON
retry, model fallback or adaptive increase of a limit. The only second targeted search is the
second sweep of section 6.

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

The runner can also take a `Document` of `groundgate.read.document` (#508,
[document-model.md](document-model.md) §10). The runner checks it as the loader checks an
untrusted object, and the text of the document is the text of the run. A document with no nodes
gets the windows above, so its prompts are the prompts of its text. A document with nodes gets
node chunks. The runner packs whole top-level nodes into chunks of at most `chunk_chars` code
points, in text order, with no overlap. The text between two nodes goes with the node before it,
and the text before the first node goes with the first node. A node that is too large splits at
its children: a list at its items, a table between its rows. A row, or a node with no children,
that is too large gets the windows above inside its span. Each part of a table that starts after
its header rows sends them as a second region. The header rows are the rows at the start of the
table in which each cell is a header cell. Each chunk also sends each top-level heading whose
section holds its start, one region for each heading. The chunk is the first region of its
prompt, and the context regions follow in text order. The plan records the chunk, not its
context regions. The prompt digests cover them.

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

The instructions also say that a field item quotes the label before the value, such as a row
label or a column header, and that it must not hold the value (#318). The core rejects both
other forms under SPEC §4.6.

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
value or combine isolated receipts to hide a conflict.

There is one exception, for a rounded figure beside the exact figure (#319). It is opt-in: it
applies only when `drop_rounded` is true, and the default is false (#331). A narrative can give
"£17.3bn" and a table 17,284 in millions. I drop a candidate A only when all of these hold:

1. A's decision in the core call over all tips has `CONFLICTING_CANDIDATES`.
2. A's field is numeric. A's token is the first number token in its evidence span whose value,
   times a power of ten, is A's value. A's **precision** is one unit in the last written digit of
   that token, times that power of ten. "17.3" for 17300000000 states 100000000. A zero token
   is A's token only when A's value is zero: "0.0" for 0 states 0.1.
3. A second candidate B has the same field, key and unit, and a different value. The difference
   between the two values is at most half of A's precision.
4. B is admitted in a core call over all tips without the dropped candidates.

When a drop does not meet rule 4, it is cancelled, and the check runs again over the other drops
until it is stable. So a third value that conflicts with B keeps A in the final receipt. A drop
does not change a decision of the core: it changes the candidates that the runner sends. The
record keeps a `rounding` line before the final admission. That line names the admission packet
with all tips, and each dropped candidate id with the kept ids and the precision.

The check uses exact integer arithmetic. It reads only numbers with at most 1000 digits and an
exponent of at most 1000. A larger number fails closed: it is never dropped, and no decimal
error ends the run.

**Threat.** This rule trusts the document to hold a more exact figure. Without it, a second
value always sends the field to review. With it, the author of a document or a reference can
choose the admitted value inside half of the rounded figure's precision. Beside "£17.3bn", a line
"Revenue was 17,299 million" drops the rounded figure and admits 17299000000. The shift is
bounded by that half precision, and the `rounding` line records the drop. A value outside it
stays a conflict. For this reason the rule is off by default (#331). With the default, the runner
keeps both candidates, and admit gives `CONFLICTING_CANDIDATES` to each. Set `drop_rounded` only
when you trust the authors of your documents and references. The header of the run record keeps
the setting, so replay gives the same result.

## 5. What each repair may change

A repair request names exactly one candidate id, the prior candidate, its current decision,
its permitted changes, and the same pinned source texts. The response contains exactly one
replacement candidate or `{"not_found": true}`. A repair that reports not found keeps the
prior tip and records `repair_not_found`; it does not erase an inconvenient candidate.

For a citation repair the candidate's field, raw value, unit, key, id and every other non-evidence
member are fixed. The runner compares raw JSON values before canonical number comparison:
changing `"1000"` to `"1,000"` counts as a changed value too. No repair can add outside evidence,
change a reference id, change source, widen `search_region`, add confidence or supply judgments.
If the original has no value evidence, its new value item may cite the document or any
reference in the source context of the call that created it. Other changed roles use that
same source. A source outside that context is a protocol failure. The complete diff is
recorded before admission.

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
| `FIELD_CITATION_INVALID` | Replace, add or remove field items. The feedback names the cause of a field item that holds the value or comes after it (#318). |
| `KEY_CITATION_INVALID` | Replace or remove the key item. |
| `KEY_NOT_AT_VALUE` | Only when key is in `missing`, aliases exist, and the value's line has a tab: add a key item and a field item. The candidate's key stays fixed. |
| `SCALE_WORD` | A scaled numeric value is permitted as a new terminal proposal, as below. Evidence changes require their own eligible codes. |

A candidate can cite up to 8 field items (spec 0.10, #300). The runner compares the field items
as one list, in list order. When a repair may change `field`, the reply can add, remove, replace
or reorder field items. When it may not change `field`, the list stays the same. Every other role
holds one item at most. A reply with a ninth field item, or with two items of another role, is a
protocol failure.

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
An individual word is also not one of 78 English function words, such as "the", "and" and
"for" (#466). The comparison is case-folded. The list is `_STOP_WORDS` in the runner. Its
words come from English grammar: articles, conjunctions, prepositions, pronouns and auxiliary
verbs. No benchmark set selected them. Before #466, each "the" and "and" of a description was
a query, and their windows merged into one region of the whole document. The full title and
the aliases keep their function words.

The script collapses whitespace, trims each query, skips empty queries and case-folds for
comparison. It keeps the first query when these forms are duplicates, so an earlier title or
alias wins the tie. It searches whole words or phrases with flexible whitespace. It does not
use a model, stemming, an embedding or words from model output. Keys are included as context
in the prompt, not searched alone: common year headings would match unrelated tables. Every
retained query and searched source is recorded. The first 64 distinct nonempty queries are
searched; `omitted_queries` counts later distinct queries without scanning the sources for them.
This hard internal cap applies to live runs and replay and cannot be raised by a saved header.
Query truncation records `search_truncated`. Match records are bounded as below.

A word query can be a common word (#494). An individual word of the title or the description
is common when the merged windows of all its matches cover more than half of the characters of
the supplied sources and more than `max_region_chars`. The search leaves a common word out: it
retains no match of it and makes no window for it. The search entry lists each common word in
`common_queries`, with its number of matches. A common word does not make the search
`search_truncated`. The full title and the aliases are names of the field and are never common.
The second limit keeps every word of a short document. Before #494, words such as "year",
"report" and "total" occurred on most pages of an annual report, and their windows merged into
one region of the whole document. The limits come from the issue: "most" of a document is more
than half of it, and a region larger than `max_region_chars` is cut. No benchmark set selected them.

The script searches the full document and each supplied reference. Query order defines match
priority: title, aliases, title words, then description words. Within one query, document hits
come first, then references by id, then byte position. It visits each match and retains at
most 1024 match records in that order. It counts later matches in `omitted_matches` without
allocating records or windows for them. A retained match selects `search_context_chars` characters on either side,
clamped to its source. It merges overlapping regions in the same source and gives each merged
region its best query rank and its best match: the match with that rank that comes first. A
merged region longer than `max_region_chars` is cut to a window of that size around its best
match, clamped to the region (#382). The runner does not drop it. The search entry lists each
cut in `cut_regions`, with the byte span of the merged region, the byte span that it keeps and
`cut_matches`, the number of retained matches of the region that are not inside the kept span.
The list covers the whole ranked pool, not only the sent regions, because the second sweep can
send any region of the pool. The `regions` of the search entry and of each `sweep` entry tell
which regions were sent.
It selects at most `max_target_regions` by rank, then source and
byte start. `omitted_regions` counts discarded regions from that bounded pool; it does not
estimate regions from omitted matches. Either cap, or a cut with a `cut_matches` count above
zero, records `search_truncated`. A cut that keeps every match of its region removes only
context, so it does not truncate the search (#494). Before #494, each cut truncated the search,
and with `search_context_chars` above half of `max_region_chars` the window of one match was
always cut. The selected
regions are sent in document, reference-id and byte-start order for stable quote anchoring.

On a document with nodes, a cut moves each end of its kept span to the nearest row boundary
inside the merged region, or to the nearest cell boundary when no row boundary is inside it
(#508). An end that is not inside a row stays. The kept span can then be longer than
`max_region_chars` by part of a row at each end. If the kept span starts in a table after its
header rows, the header rows go into the pool as one more region, with the rank of the cut
region. Two cuts in one table add the header rows one time. `cut_regions` records the kept span
after the move.

The match-record cap does not cap the number of hits scanned. Each of at most 64 retained
queries per missing field scans every supplied source to count all hits, including omitted
matches. The runner builds and caches a casefold once per source across all fields and
queries. Length-preserving folds use identity boundaries; expansions use compact array
breakpoints. Runner byte offsets also use compact multibyte deltas, not a per-character
reverse dictionary. Search memory grows with the supplied texts, schema query deduplication
and cached folds.

The caller must bound the number of requested fields, number and size of references, and
document length before calling the runner. Source scans can cover up to
`missing fields * 64 * total source characters`; query matching and schema processing add
work. Counting omitted queries still reads all schema terms. The runner does not enforce a
total scanned-character or CPU budget. `max_calls` limits client calls and does not bound
these scans, including searches that make no client call.

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
The runner admits no candidate from that reply. It records `protocol_failure` for that field
only and continues with the other fields and the repair rounds. The run stays complete, as
after a repair protocol failure. The field state does not claim that the value is absent.
Other evidence roles keep their core checks in the pinned text.

One prompt includes all retained regions and asks only for that field. If they do not fit the
prompt limit, the script removes the region with the worst rank first, then source and byte
start as above, until they fit. The other regions keep their location order. The search entry
records `trimmed_regions`, lists only the sent regions and has the status `search_truncated`.
This is the first sweep, and its call has `sweep: 1`.

If no region fits, the second sweep runs (#382). It takes every ranked region in rank order,
then source and byte start, and puts as many in each call as fit `max_prompt_chars` and
`max_target_regions`. A region that does not fit alone is skipped. Each call sends its regions
in location order. A `sweep` entry before each call lists its regions without text, and the
call has `sweep: 2` and its `part`. The sweep stops at the first reply with a candidate or a
protocol failure, when every region is sent or skipped, or after `max_sweep_calls` calls. A
`sweep_stop` entry records the calls, the skipped regions, the unsent regions (which include
the skipped ones) and the status: `proposed`, `protocol_failure`, `exhausted`, `sweep_limit` or
`no_room`. A sweep that ends the run, at `call_limit`, an invalid reply or a candidate limit,
has no `sweep_stop`: its `limit` or `call` entry tells why the run stopped. Each not-found reply
records `targeted_not_found`. If the sweep sends no call, or `max_sweep_calls` is zero, the
field is `search_limit` and the run is incomplete. If the sweep sent a call, the run stays
complete, as after a trimmed first sweep, also when `sweep_limit` leaves regions unsent. I
chose this on purpose: the search entry keeps the status `search_truncated`, and `sweep_stop`
counts the unsent regions, so the field state `targeted_not_found` is never a claim that the
value is absent. A consumer that needs every region searched reads those two entries. A `call_limit` in the second sweep records
`call_limit`, not `unsearched`, because the field was searched. A single-field reply uses
the initial envelope. It can give candidates, or explicit `not_found`. Targeted candidates
have the same repair rules and budget as initial candidates. There is one targeted call per
field in the first sweep, not one per match, and at most `max_sweep_calls` more in the second
sweep.

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
It rejects model ids, source ids or offsets that the runner did not permit.

On a document, a document evidence item can cite a node in place of a quote (#508): `node` with
`text`, or `node` alone for a cell. The runner finds the quote inside the node with the quote
rules of SPEC §4.6 and gives the item the offsets of that one match, with no `text`. `node`
alone gives the span of the cell. An id that is not an integer of the document, a quote that is
not exactly once in the node, a blank quote, `node` alone on a node that is not a cell or on an
empty cell, and `node` on a reference item or on a run on text make the reply invalid. A cited
value must be inside a document region of its prompt: the runner sets `search_region` to the
first such region, and a value outside them is a protocol failure, as a quote outside the
targeted regions is. The prompt does not list node ids yet, so a model reply cites a node only
when its client gives the ids. The runner
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
error or unexpected internal failure raises `ExtractError` with its `record` set to the partial
run record. It is never converted to a not-found result or an admitted candidate. A call timeout belongs to the
client; the synchronous interface cannot force an uncooperative client to return.

The final result distinguishes ordinary no candidate, final review, final rejection, repair
limit, protocol failure and incomplete run. The last three do not claim that the field is
absent. Field states are a history of attempted work, not an active candidate inventory.
`proposed` can precede a resource rollback. A limit entry lists retained and dropped candidate
ids and ids whose evidence version was reverted. Rollback restores the last accepted raw
candidates as well as their admission packet. The returned candidate list and core receipt
are the active inventory. No history state overrides a core outcome. If an incomplete run
leaves a field with no valid disposition, `incomplete_no_disposition` replaces its empty
history. It makes no claim about whether the client attempted that field or whether the
value is absent; call and protocol-failure entries describe the attempted work. A prompt
character-budget stop records `prompt_limit`, separately from a total `call_limit`, in both
the limit event and affected field history. Targeted call exhaustion keeps the field state
`unsearched` with the limit event's `call_limit` status. Field histories omit phase names;
call and limit events carry `phase`. In normal execution, oversized initial prompts refuse
before the first call, targeted region-size exhaustion records `search_limit`, and an
oversized repair prompt records `prompt_limit`. Exhausted repair calls record `call_limit`;
completed repair rounds can leave `repair_limit`. A targeted not-found response records
`model_not_found` followed by `targeted_not_found`, preserving response and phase history.

## 8. The run record and replay

The core receipt format stays unchanged. The `groundgate-run/5` record is a log: one line of
canonical JSON for each entry. Each line has a `sequence`, the `previous` line's digest and its
own `entry_sha256`. The first line, `header`, is the run manifest. It holds the runner version,
core spec version, model id and every `RunPolicy` setting, and it names every input by digest:
the text (with `kind: "text"`, the document id and source), the resolved schema, the resolved
policy and each reference. A run on a document has `kind: "document"`, and the input also names
the `document@1` object by its run key `document_sha256` and its store key `document_key`, and
the reader of the document (#508). The last line, `final`, holds `complete`, the terminal field states
and the final core receipt digest. Its `entry_sha256` is the run digest, `run_sha256`.

For each call the log holds its sequence number, phase, field or candidate ids, repair round,
complete prompt digest, model id, raw reply digest and length, parse or client error, and
permitted and actual diff. Each admission line names its admission packet: the exact candidate
list and the core receipt. Search-only, limit and final-admission steps have lines too.
A field item that fails because it holds the value's token or comes after the token has the
cause `holds_value` or `after_value` (#318). The token is the one that the precision of section 4
reads. Without it, the value span stands for the token. A repair call line lists the causes of its candidate in
`field_causes`. The final admission line maps each candidate id with a cause to its causes, in
the same key, so that a bench can count each cause.

The log names objects by digest, and the returned artifacts are those objects: the inputs,
the prompts, the replies and the admission packets. An object's key is its digest with its kind
tag (`text`, `document`, `schema`, `policy`, `reference`, `prompt`, `reply`, `admission`). Raw-reply digests
cover exact UTF-8 bytes, including whitespace. Prompt digests cover the exact string given to
`client`, encoded as UTF-8. Document, schema, policy, reference and admission objects are canonical JSON.
Client errors have no reply digest.

Runner digests use their own prefix, `groundgate-run/5:<kind>` followed by a zero byte and the
object bytes. They do not reuse the core `digest()`, whose prefix names the spec version, so the
same text keeps its key in each spec version. There are no wall-clock times, host paths,
credentials or random ids in this deterministic content. An app may keep times separately. The
chain detects a changed or removed line when checked against the saved run digest; it is not a
signature or proof of the model's identity.

`RunResult.write(folder)` checks every key and refuses an existing log before it writes. It
writes each object to `folder/objects/<hex>` first and the log to `folder/run.jsonl` last. Each
file goes to a temporary name and moves into place, and an existing object with other bytes is
written again. After a crash, `read` refuses the run and `write` can run again. `write` uses only
the standard library and never replaces a log. Runs that share a folder trust each other's
writes.
`RunResult.read(folder)` reads only the objects that the log names, so runs can share one
`objects/` folder. The log and each object must be a regular file, not a symlink, and together
at most `max_bytes` (1 GiB by default), so a FIFO, a device or a huge file cannot hang it or fill
memory. It gets the inputs from the objects that the header names and replays the run, so a
changed line, a changed, missing or oversized object, or a bad object key raises `ValueError`.
The replay cost grows with the document and the record.
`RunResult.save(store)` writes the run into a store of [store.md](store.md) (#288, #405) and
returns the packet key. It writes each object as its store kind (`text@1`, `document@1`,
`schema@1`, `policy@1`, `reference@1`, `prompt@1`, `reply@1`, `admission@1`), then the record as one `run@5`
object with the bytes of `run.jsonl`, then the final inputs, the receipt and a `packet@1` object
whose `run` names the record. It writes only the objects that the record names, and it saves a
run that is not complete too. Before the first write, it checks each object against its key and
runs `admit` again on the stored inputs. If that gives another receipt, it raises before it
writes. A store error during the writes can leave objects that no packet names. The record
keeps its runner keys, so a store cannot replay the run yet: the store keys come with
`groundgate-run/5` too (#429), in 0.13. `RunResult.read(folder)` stays the replay path.

The document model (#285) adds no new log format. An input of `kind: "document"` names a
document and its reader, and a `node` key in a reply names a node, which the runner resolves to
a span before `admit` (#508). A chunk plan entry keeps the members `source`, `start` and `end`,
and an entry with any other key fails replay. `store forget` removes the `document@1` object of
a run with the prompts, the replies and the admissions of the run.

`replay(record, artifacts, text, schema, policy, references)` makes no model call. For a run on
a document, `text` is the `Document`. It runs the runner again on the supplied inputs and gives it the recorded replies in call order. Each
new prompt must have its recorded digest. The rerun re-parses replies, enforces the same diffs
and budgets and calls `admit` again for each admission. Replay then compares the complete new
log with the saved log and the new artifact map with the supplied artifacts. That
comparison covers the header input digests, every entry and its chain digest, each admission
packet and core receipt, the final receipt digest and the run digest. Replay does not call
`verify`; a receipt must be identical to the receipt that the rerun creates. Before building any prompt, replay bounds the initial chunk plan by the
recorded chunk-plan length or call and limit entries, as well as the declared budget. An untrusted header cannot
authorize a plan larger than those saved entries. The recorded chunk plan also bounds replay
of an initial pass interrupted before every planned call ran. It validates each saved chunk
and compares the regenerated source and byte ranges before constructing prompts. Replay
allocation ceilings for candidates and admission history are further bounded by the actual
canonical record and artifact byte counts, even when the header declares larger budgets.
It checks not-found and search-only entries too. Missing artifacts, changed
settings, unknown runner versions or a different core version fail replay.
`groundgate-run/5` replaced `groundgate-run/4`, the version that 0.12.0 wrote, because the
search leaves out common words and a cut that keeps every match does not truncate the search
(#494). A run/4 record searches other regions in this runner, so its replay cannot match.
`groundgate-run/4` replaced `groundgate-run/3`, the version that 0.11.0 wrote, because the
search leaves English function words out of the word queries (#466). A run/3 record with such a
query searches other regions in this runner, so its replay cannot match.
`groundgate-run/3` replaced `groundgate-run/2`, the version that 0.10.0 wrote, because the
search cuts large regions and the second sweep adds entries (#382). `groundgate-run/2` replaced
`groundgate-run/1`, the version that 0.9.0 wrote, because the prompt, the field causes and the
`rounding` line changed (#318, #319). An older record fails replay with the message
`runner version differs`, which names both versions. It does not get to
a prompt comparison. The prompt of `groundgate-run/3` changed before a release wrote it (#428):
it asks for the whole scale heading. The `groundgate-run/3` records written before #428 are
development loop records only, and their replay fails with `invalid replay record or inputs`.
#441 changed the prompt for one development loop, and #395 reverted it. The records of that
loop fail replay the same way.
A client-error
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
