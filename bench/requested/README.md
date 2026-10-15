# Requested fields: proposed set for 0.9

Status: kinds and field lists approved by the maintainer in chat on 2026-10-15 and recorded on
#269. Approved development pilots are cached in local work storage. `manifest.json` records their
source URLs, byte sizes, hashes and notices; `labels.json` contains source-based development
drafts and source-checked provisional labels for inspected held-out candidates. Source selection is
still open. No model output exists. Every additional download needs approval.

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
effective errors round up. The document bound counts documents with at least one wrong admit.
A slice with no effective value trials has no combined bound. The report states this default;
it does not claim to estimate within-document correlation from zero errors.

## Baseline and seal

I freeze the current one-pass prompt and the app feedback loop configuration, including model
version and repair limits, on the development part. I run the held-out baseline and runner with
the same request, policy and model identity after labels are sealed. I keep all calls and receipts.
A cache records the label-file and manifest digests, so the scorer refuses output from a different
label seal, request or split. A document schema may supply its currency and aliases, while keeping
the fixed kind field names, types and multiplicity. Each document schema is a full snapshot.
Later edits to a kind template do not update existing document snapshots; I review them together
before the manifest freeze.
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
computed over the exact file bytes, plus a `documents` list. Each run document has `id`, final
`decisions` and an explicit `not_found` list of `{field, key}`. Runner decisions come from its
final core receipt. Baseline decisions are application storage outcomes: they keep independently
admitted rounds, but withhold different admitted values for a single-value field. Those entries
retain `core_outcome` and an `application_reason`; original core receipts remain unchanged.
The scoring projection omits quotes and raw replies; the external cache keeps all calls and
receipts. A missing run document is no candidate, not an absence hit. The pilot manifest and
labels are draft inputs. No result file is committed before an actual sealed-label measure exists.

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
scratch paths must stay inside that root. The server binds only to `127.0.0.1:8784`. It displays the original source beside the fixed field
scope, unit and manual label controls. If `pdftoppm` is installed, it renders one page at a time
to a PNG cache in local work storage. Each page request checks the original PDF hash. Page
previews have page and size limits. Without the optional renderer, the page embeds the PDF and
provides a link to open the original. The renderer is discovered on the server PATH and adds no Python or core dependency. An optional
source-text link states when its text has no pinned hash; when the manifest provides
`text_sha256`, the server checks that raw-file hash before display. It never opens cached model replies. Present values need an
original PDF page; unclear fields need a reason; absences need a second blind check. The server
checks each PDF against its manifest hash before display and before sealing. A changed or missing
source cannot be used to seal labels. Evidence pages cannot exceed the recorded PDF page count.

Draft labels can be saved while source selection is open. After the complete source list and
request are frozen, I can seal all labels after the complete source checks. The server refuses edits after a seal or
when cached run JSON exists. Each save is atomic and uses a local work directory for its temporary
file. CSRF tokens, exact host/origin checks and document-ID routes keep the local write interface
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
also hashes the imported package and its own code. Commit, reader and transport names are caller
declarations; the actual code and input bytes are checked independently before each call.

`session.run("baseline", client, split="heldout")` runs the released feedback-loop algorithm
with the same current core as the runner. Its instruction string is copied exactly from the
released own-model guide, including external and knowledge evidence with the default review
policy. Both arms use the same fixed initial chunks. Baseline admission uses the whole document
and a chunk-bounded `search_region`. It permits one batched feedback retry for each chunk.
It does not infer an explicit absence from an omitted candidate. This is an adapted baseline,
not a replay of the entire released reader and decision pipeline.

`session.run("runner", client, split="heldout")` needs the integrated `groundgate.run` API.
Without that API it stops before any call. Explicit runner absence needs a complete, untruncated
search with no active candidate. A field-level absence never creates a key-level absence.
`session.run(arm, split="heldout")` replays the immutable call cache without a client.

Each call reserves an exclusive cache entry before transport, then stores the prompt and reply
before admission. A process stop with an unresolved reservation needs inspection; it is never
retried automatically. Completed calls can resume without repeated transport. A changed frozen
input or code snapshot stops reuse. The local transport reply retention limit is 8 MiB; larger
replies record a size-limit failure and digest rather than their body. The client must bound its
own download and memory use before returning a reply. Both arms also apply the frozen parsing,
call, prompt, candidate and admission-history budgets. Incomplete documents remain marked in the
projection. A smaller harness limit is reported rather than silently treated as an absence.

I check the harness with synthetic sources and fixed replies. No test reads the corpus labels or
source PDFs. The runner integration checks skip until the Runner lane is available; I run them
against that lane before integration. No real client runs before the full corpus seal.

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
