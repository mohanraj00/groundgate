# Requested fields: proposed set for 0.9

Status: kinds and field lists approved by the maintainer in chat on 2026-10-15 and recorded on
#269. I froze the manifest and sealed the labels on 2026-10-16, before any model output on this set.
The set has 64 documents: 3 development pilots and 61 held-out (20 component datasheets, 20 SBCs,
21 annual reports). `manifest.json` records each source URL, byte size, PDF hash and reader text
hash. The originals and reader texts stay in local work storage. Every download had approval.

## Proposed kinds and fixed requests

The maintainer approved these three kinds. The first two are unlike the current field sets. The last kind is
the one financial kind that the issue permits, and gives totals and parts for later relation
checks. No relation check is built in 0.9.

| Kind | Fixed requested fields | Scope |
|---|---|---|
| Electronic component datasheets | recommended supply voltage minimum and maximum (V); typical supply current (mA); operating temperature minimum and maximum (C) | one device or ordering variant named by the document; recommended operation, not absolute maximum ratings; typical current at the document's stated reference condition |
| Health plan Summary of Benefits and Coverage | in-network deductible for one person and for a family (USD); in-network out-of-pocket limit for one person and for a family (USD); in-network specialist visit copay (USD) | one plan and coverage year; a numeric copay only, not a coinsurance percentage; a condition that prevents one value is unclear |
| Annual reports from outside the U.S. in English | revenue; cost of sales; gross profit; total assets; total liabilities; total equity | latest full fiscal year, consolidated group, original reporting currency; amounts after printed scale; report the positive amount of a cost; preserve the other printed signs |

The financial fields use the document's reporting currency as the schema unit. The request stays
fixed. A schema records that currency before labeling, and no conversion is performed. The
component fields use schema unit surfaces for V, mA and C. Their endpoint fields carry the
appropriate comparison meaning: `ge` for minimum and `le` for maximum. The out-of-pocket
limit fields also use `le`; other requests use `eq`. A range with no unique endpoint reading is unclear.

I propose one development part and one held-out part per kind, with at least 20 held-out documents
per kind as #269 requests. Development and held-out documents have disjoint publishers or product
families where possible. The manifest fixes membership before extraction or model output. One
document does not stand for several independent trials because it has several fields.

## Selection and download gates

I inspect catalog pages only before the kind approval. No document enters the corpus at this
stage. I propose public publisher pages and URL plus SHA-256 provenance, rather than committing
copyrighted source PDFs without permission. I check the source terms before each download. A
public URL by itself is not a redistribution license.

After kind approval, I list exact URLs and response sizes, or a stated byte cap when a source does
not give a size. I ask for approval of each download. I keep source PDFs, browser files and
intermediate text in the workspace's local work folder outside synced folders. Final labels,
request, manifest and reproducible reports belong in this set. No new-set model output is read until all blind labels in both splits are complete and sealed.

I reject duplicate source/text hashes and split near-duplicate revisions together. Selection uses
publisher metadata and layout eligibility, not model success. I record rejected sources and the
reason. I label from the original document and text together: value, unit, condition/key, evidence,
absence or unclear with a reason. An absence gets a second blind check. I do not compute a label
that the document does not state.

## Measures

`bench/score.py --requested --set bench/requested` uses a separate requested-field mode. It consumes sealed blind labels and
final decisions from cached runs. It writes this set's `results.json`; `bench/report.py` renders
that file. It leaves the published v0.1 and set 2 files unchanged.

For each final distinct admitted value, the scorer compares field, key, normalized value and unit.
It counts every distinct wrong admit, including extras on a multiple field and values on an absent
field. A labeled value with no admitted match is either a right-value review or a silent miss.
Wrong reviews are catches. Explicit not-found for an absent field is an absence hit; silence is
reported separately. Unclear slots are excluded and counted. Duplicate proposals never add hits.

The report gives totals, each kind, each field, and each kind/field pair. Each slice includes the
admitted error rate, the miss rate, right-value review share, silent miss share, escapes, and sample
sizes. It gives two one-sided 95% upper bounds from #269 and #277. For the value bound, the default
design effect is the largest number of distinct admitted values from one document in that slice,
at least 1. This assumes no independence within a document. Effective trials round down and
effective errors round up. The document bound is on the documents with at least one admitted
value, and counts those with at least one wrong admit. A document with no admitted value cannot
hold an admitted error, so it adds no document trial. A slice with no admitted value has no
document bound.
A slice with no effective value trials has no combined bound. The report states this default;
it does not claim to estimate within-document correlation from zero errors.

## Baseline and seal

I freeze the current one-pass prompt and the app feedback loop configuration, including model
version and repair limits, on the development part. I run the held-out baseline and runner with
the same request, policy and model identity after labels are sealed. I keep all calls and receipts.
A cache records the label-file and manifest digests, so the scorer refuses output from a different
label seal, request or split. A document schema may supply its currency and aliases, while keeping
the fixed kind field names, types and multiplicity. Each document schema is a full field snapshot.
An optional `request_context` records only the predeclared `subject` and `scope`. The harness
appends its canonical JSON to each existing field description in an effective schema used by
both arms, admission and replay. The scope is one fixed string for each kind. The annual and SBC
subject is one fixed string for each kind. A component subject is only the part number. Request
context never holds a value, date, currency, scale or labeling instruction from a source.
Raw field schemas stay unchanged. Later edits to a kind template do not update existing document
snapshots; I review all request parts together before the manifest freeze. On 2026-10-16 I
replaced each request context with one fixed scope for each kind, before any model output. This
changed the manifest digest, so a cache made with the earlier context does not validate.
A changed label after model output requires the maintainer's approval and is reported. Held-out
output is used for the planned measure and never for tuning. A release-only sealed set for 1.0
is outside this milestone.

## Cache format and synthetic checks

`manifest.json` has `schemas` indexed by kind and a `documents` list. Each document has `id`,
`kind`, `split` (`development` or `heldout`), source URL and source/text digests. An optional
`schema` on the document resolves its currency, aliases and keys before labels are sealed.
`labels.json` has `status: "sealed"` and a `documents` list. Each label document has its `id`
and a `fields` list. Each requested field/key occurs exactly once with `status` `present`,
`absent` or `unclear`. A present slot has `values` of `{value, unit}`. An unclear slot has its
reason in the labeling record. Scoring refuses incomplete labels in either split.

Each `runs/<name>.json` has `labels_sha256` and `manifest_sha256`, each prefixed `sha256:` and
computed over the exact file bytes, plus its `split` and a `documents` list. Each run document
has `id`, final `decisions` and an explicit `not_found` list of `{field, key}`. Runner decisions come from its
final core receipt. Baseline decisions are application storage outcomes: they keep independently
admitted rounds, but withhold different admitted values for a single-value field. Those entries
retain `core_outcome` and an `application_reason`; original core receipts remain unchanged.
The scoring projection omits quotes and raw replies; the external cache keeps all calls and
receipts. A run document with no decisions is no candidate, not an absence hit. The scorer
refuses a run of another split, a partial run, and a run whose documents are not exactly the
documents of the split. The manifest is frozen and the labels are sealed. No result file is
committed before an actual sealed-label measure exists.

I check the scoring mode with synthetic values:

```bash
uv run pytest bench/requested/test_metrics.py
uv run python bench/score.py --requested --set bench/requested --split heldout
uv run python bench/score.py --requested --set bench/requested --split heldout --check
```

The last two commands require the sealed corpus and cached runs; they refuse the present draft.

## Blind label page

I use the original, unchanged PDFs in the approved local source directory:

```bash
uv run python bench/requested/label_app.py --set bench/requested --local-root /absolute/local/work --source-dir /absolute/local/work/downloads
```

I supply the local storage root with `--local-root` or `GROUNDGATE_LOCAL_WORK`. Source and
scratch paths must stay inside that root. The server binds only to `127.0.0.1:8784`. I open
the exact private session URL printed at startup and keep it private. Every HTTP route needs
that session capability; the old root URL cannot return source or label state. A restart creates
a new capability. The server does not log requests and sends a no-referrer policy. It displays
the original source beside the fixed field
scope, unit and manual label controls. If `pdftoppm` is installed, it renders one page at a time
to a PNG cache in local work storage. Each page request checks the original PDF hash. Page
previews have page and size limits. Without the optional renderer, the page embeds the PDF and
provides a link to open the original. The renderer is discovered on the server PATH and adds no
Python or core dependency. An optional source-text link states when its text has no pinned hash;
when the manifest provides `text_sha256`, the server checks that raw-file hash before display.
It never opens cached model replies. The page displays explicit request context as plain text
above the fields. Present values need an original PDF page; unclear fields need a reason; absences need a second blind check. The server
checks each PDF against its manifest hash before display and before sealing. A changed or missing
source cannot be used to seal labels. Evidence pages cannot exceed the recorded PDF page count.

Draft labels can be saved while source selection is open. After the complete source list and
request are frozen, I can seal all labels after the complete source checks. The server refuses edits after a seal or
when cached run JSON exists. Each save is atomic and uses a local work directory for its temporary
file. The startup capability, separate CSRF token, exact host/origin checks and document-ID routes keep the local write interface
separate from source text and filenames. Restart the server after changing the manifest.

The regular pytest run collects the requested-field scoring and label-server tests, so CI checks
both. The CLI refuses unsealed pilot labels; it does not turn drafts into a reported measure.

The held-out comparison and companion key/layout diagnostics are planned in [MEASURE.md](MEASURE.md).

The development drafts use source-only agent annotations, checked against original PDF page
renders. Independent source checks cover absences and disputed fields. Component case-temperature
limits retain that condition; fields with no selected rail or mode stay unclear. These drafts
are not sealed and cannot be scored. No benchmark model call has run.

## Frozen run harness

`run_set.py` takes a caller-supplied synchronous client. It has no provider client or model CLI.
I construct `FrozenSet` with the set directory, external source and cache directories, an explicit
configuration file, and the SHA-256 digests of the manifest, labels and configuration bytes.
The harness requires a frozen, complete manifest and sealed, complete labels before a call.
It verifies every source PDF and reader text against their frozen hashes. Reader text must be
NFC. Sources are named `<id>.pdf` and `<id>.txt` in the external source directory.

The configuration fixes `model_id`, transport identity/version/effort, policy, every runner
setting, source commit, reader identity/commit/code digest and baseline guide commit. The harness
also hashes the imported package and its own code. Explicit request context accepts only nonblank
subject and scope strings, each at most 4096 Unicode characters. Before copying context across
fields, it checks that the combined JSON string content of all resulting descriptions fits the
frozen prompt budget. Full prompt checks still apply. It never infers context from
`label_scope_note`, `named_source` or labels. It refuses a scope that changes in a kind, and a
subject or scope that holds a label note, an unclear reason or a `label_scope_note`. Each arm
sends the same effective schema, and the recorded schema digest covers the appended descriptions.
Changed request metadata in memory or on disk stops a call before a reservation. Commit, reader and transport names are caller
declarations; the actual code and input bytes are checked independently before each call.

`session.run("baseline", client, split="heldout")` runs the released feedback-loop algorithm
with the same current core as the runner. Its instruction string is copied exactly from the
released own-model guide, including external and knowledge evidence with the default review
policy. Both arms use the same fixed initial chunks. Baseline admission uses the whole document
and a chunk-bounded `search_region`. It permits one batched feedback retry for each chunk.
It does not infer an explicit absence from an omitted candidate. This is an adapted baseline,
not a replay of the entire released reader and decision pipeline.

`session.run("runner", client, split="heldout")` needs the integrated `groundgate.extract` API.
Without that API it stops before any call. Explicit runner absence needs a complete, untruncated
search with no active candidate. A field-level absence never creates a key-level absence.
`session.run(arm, split="heldout")` replays the immutable call cache without a client.
`documents=[...]` runs only those documents of the split, so separate processes can fill the
cache in parallel. A partial run writes no projection. A later run of the whole split reuses the
completed documents without transport and writes the projection.

Each call reserves an exclusive cache entry before transport, then stores the prompt and reply
before admission. A process stop with an unresolved reservation needs inspection; it is never
retried automatically. A recorded transport error is never retried automatically either. With a
client, `retry_transport_errors=True` moves the error at the last call of a document, its
reservation and its result into `attempts/NNNN` in the document cache. It also moves the split
projection into `_attempts`. Then that call runs again. Nothing is deleted. A transport error
before the last call stays refused. Completed calls can resume without repeated transport. A changed frozen
input or code snapshot stops reuse. The local transport reply retention limit is 8 MiB; larger
replies record a size-limit failure and digest rather than their body. The client must bound its
own download and memory use before returning a reply. Both arms also apply the frozen parsing,
call, prompt, candidate and admission-history budgets. Each projection document records
`complete`, `transport_error` and `transport_retries`. `results.json` and the report give, for
each arm and kind, the incomplete documents, the documents with a transport error and the
retries. A smaller harness limit is reported rather than silently treated as an absence.

I check the harness with synthetic sources and fixed replies. No test reads the source PDFs.
One test reads the tracked manifest and labels only to check the request context rules. The
runner integration checks skip until the Runner lane is available; I run them against that lane
before integration. No real client runs before the full corpus seal.

## Inspected candidate batches

`source_checks.json` records the individually approved inspection downloads and their own notices.
All originals fit their approved caps and remain in local work storage. The first three component
candidates are on hold: their PDF notices add an application-specific use restriction, and
applicable benchmark permission is not established. They are not in the label-page manifest.

The two SBCs and two annual reports are draft candidates in the manifest, with source-checked
provisional labels.
Their original identities, presentation currencies and scope notes are fixed before value
labeling. They have readable English text layers. No affirmative open reuse grant was found;
source availability and download approval do not establish one. Their presence in this draft
page is not a final eligibility decision or permission to redistribute source material.
Selection remains open and the set cannot seal. The component holds, all source notices and
any final exclusion reasons must be resolved before membership is frozen.

The first candidate labels use source-only agent annotations and original page renders. Independent
blind checks confirm the three new absence labels and the SBC fields. One SBC states both
ordinary out-of-pocket limits and maximum cost shares for different medical expense categories;
its two out-of-pocket slots stay unclear because the fixed request does not choose that scope.
No expense components, unstated profit or closing totals were calculated. These source checks
are not benchmark outputs, a sealed label set or a measured result.

The second inspection batch adds three component datasheets, three SBCs and one annual report
as draft candidates. Their source hashes, named variants, grouping and notices are recorded.
The two related SBC plans share one source-family group and stay in the same split. Generic
copyright and safety notices are recorded separately from document-use restrictions; no
affirmative open reuse grant is inferred. The annual source has a limited personal noncommercial
download permission, not an open license. Final source-use eligibility remains open.

The requests use the same fixed fields. The annual report records GBP before value labeling.
Source-only primary and independent checks retain the printed signs and table conditions.
A cycle-average current does not resolve the fixed typical-current request, so it stays unclear.
Unselected current modes, stress-only temperature interpretations and unselected in-network
provider tiers also stay unclear. No field request or rule is changed to resolve these cases.
These provisional labels stay unsealed; they do not permit a model run or establish a measured
result. The earlier draft labels are preserved.

A later module and annual-report batch records affirmative documentation or publication grants
with their conditions and third-party exceptions. Exact source/generator paths support the module
documentation grant; they do not attest that deployed bytes equal a repository revision. The
original PDF bytes remain pinned by SHA-256. One company-only annual source stays on hold because
its own consolidated group scope is not established. No superior department figures are used.

The added absence labels have independent full-document source checks. Nominal supply voltage,
drop and ripple requirements do not state numeric supply endpoints. A gross-profit figure on an
explicitly different proportional reporting basis does not answer the fixed consolidated Group
request. Those scope distinctions were reconciled before any benchmark client output. No endpoint,
combined liabilities or profit was computed. The earlier fourteen draft labels remain unchanged.

Further module drafts name their ordering variants before any source-value inspection. Related
documentation stays in one conservative source-family group, with technical families recorded
separately. Shared material does not create independent publishers or extra split clusters.
Independent original-table checks agree on the source conditions. Unselected rails, current modes
and normal versus extended performance qualifications stay unclear. Some documents have only
unclear slots under the fixed requests; those exclusions stay visible instead of changing the
requests. Source membership remains open and these drafts cannot be scored.

The next SBC and sensor drafts retain the same predeclared requests. Independent blind source
checks agree on their statuses, values and units. An SBC labelled Uniform Summary in its catalog
is a standardized SBC in the original. Provider tiers within a network remain unresolved when
the fixed request does not select one. Generic family-deductible prose and self-only examples
do not state a numeric family deductible; that absence has two complete-source checks. Separate
medical and drug-card limits are not added. Sensor operating-table endpoints and typical-current
columns are distinct from stress ratings, current maxima and plotted estimates. Temperature
endpoints have direct operating-range support outside a stress-only table. The source records
retain the limited attributed-copy and noncommercial-copy conditions, unresolved rights and
package-tooling restrictions. No broad reuse grant or final source eligibility is inferred.
The earlier twenty draft labels remain unchanged.

Four further annual-report drafts retain latest-full-year consolidated Group scope and printed
GBP signs and scales. Original statements distinguish Group from parent or agency columns.
Some reports state only current and non-current subtotals; I do not add them to create an
unstated total. A commercial subgroup cost is not a whole-Group cost. Unresolved revenue and
cost mappings remain unclear, with both independent positions recorded rather than forced
agreement. An explicit whole-Group revenue statement elsewhere in one report resolves its
initial ambiguity. All final absences have independent complete-source checks. Both original
annotation freezes remain unchanged; reconciliation occurs before any benchmark output.
Publication-local grants and their exceptions are recorded separately, including a conditional
text grant that is not OGL. Final source selection is open and the earlier drafts are unchanged.

Three further SBC drafts preserve their exact calendar, fiscal and half-year coverage periods.
A stated calendar-year deductible within a half-year document is not prorated or extrapolated.
Explicit overall or active health-provider out-of-pocket limits are distinct from narrower
coinsurance limits; I do not add separate prescription limits. A generic network request with
different participating-tier copays stays unclear. Independent blind checks agree on all new
statuses, values and units. The records retain insurer/form overlap, a generic source-template
placeholder and raster language-notice appendices. Source copying rights remain unresolved or
limited as recorded; these drafts do not establish final membership. Earlier drafts are unchanged.

Six further checked drafts retain selected variant, own consolidated Group and printed GBP
signs and scales. A whole-Group primary revenue line resolves one initial ambiguity; other
unqualified revenue mappings and operating-current conditions remain unclear. I do not combine
current and non-current liabilities or substitute financing, pension or tax Trust Statement
figures. All absences have independent full-source checks. Three initial status disagreements
and both immutable source drafts remain in the local reconciliation record. A report with a
PDF-local reproduction restriction stays on hold outside the manifest and labels. General
publication grants, third-party exceptions and a separate audit-report copying condition are
recorded separately. Selection remains open, no labels are sealed, and earlier drafts are unchanged.

Four further checked drafts keep the same selected variants, fiscal/calendar periods and
request fields. A uniquely named operating supply-current row is distinct from standby rows;
a source with several bus-state current typicals stays unclear. An explicit zero overall
deductible is retained without inventing separate person/family cells. Separate general and
prescription expense limits do not establish a unique overall cap. A dollar specialist copay
remains a copay when additional percentage coinsurance is stated; it is not the total cost.
The local record preserves both independent positions on the two limit ambiguities. Three
originals with reproduction restrictions and one with a population mismatch stay outside the
manifest and labels. Earlier drafts remain unchanged; selection and source-use handling are open.

Five further annual drafts keep the fixed requests, full own-Group scope and original reporting
currencies. The corrected report with an inserted slip remains a full report. Directly named
Group revenue credits retain their printed signs; positive note breakdowns corroborate their
magnitudes. A directly stated rounded whole-Group liability amount retains its printed scale
and sign without adding component categories. A services-and-goods subtotal does not establish
a unique cost-of-sales mapping, so that field stays unclear. Both independent freezes and all
four initial status differences remain in the local record. One original with a reproduction
restriction and one whose target statement tables lack a usable text layer stay outside the
manifest and labels. Earlier drafts remain unchanged; membership and source-use handling stay open.

The added component drafts keep unspecified rails, threshold options and operating conditions
unclear. An explicit functional operating-range statement can establish a supply endpoint without
using an absolute maximum alone. A guaranteed virtual-junction range remains distinct from an
unresolved mapping to the requested operating-temperature quantity. Both initial annotations and
the source-based reconciliation stay in the record.

The added benefit drafts distinguish coverage tiers, membership conditions, provider networks,
and separate medical and prescription limits. Percentage charges do not become dollar copays.
The two annual drafts retain full consolidated scope, printed currencies, scales and signs;
a mixed net-revenue and funding aggregate does not establish a unique revenue mapping.
Every added absence has two complete independent source checks. A catalog-linked benefit PDF
whose original does not confirm the selected period stays outside the manifest and labels.
Earlier drafts remain unchanged; membership, source-use handling and seals remain open.
