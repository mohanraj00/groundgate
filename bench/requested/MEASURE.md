# Measure plan for 0.9

I fix the requests, split membership, source hashes, labels and run configuration before the
held-out runs. Each new source still needs the maintainer's download approval. Source selection
uses publisher metadata and layout eligibility. I do not select documents from model success.
Development and held-out documents have disjoint publishers or product families where possible.
Related revisions stay in one split. The target remains at least 20 held-out documents per kind.

I label every requested slot from the original source before any new-set model output is read.
A present label records the value after its printed scale, unit, condition, evidence and PDF page.
An absence gets a second blind check. An unclear field gets a reason and stays excluded. I freeze
the complete manifest and seal labels in both splits before any model run. The run cache binds
to both exact file digests. A changed label after model output needs the maintainer's approval.

## Requested-field comparison

I freeze the released one-pass prompt and app feedback-loop configuration on the development
split, including the model identity, policy, call limits and repair limits. I run that baseline
and the new runner on the held-out split with the same request, policy and model identity. The
runner and reader commits are fixed before those runs. I keep the prompts, raw replies, source
text hashes, candidates and receipts. I never use held-out output to tune a rule or prompt.

The manifest records predeclared selected subjects and scopes as explicit request context. Both
arms receive that same context in field descriptions in the effective schema. Raw field names,
types, aliases, units and multiplicity stay fixed. Labels and annotation notes never supply
prompt context. The cache records the effective schema digest and refuses frozen metadata
changes. This is part of the declared shared-request adapter, alongside shared chunks.

I rescore each final run with `bench/score.py --requested --set bench/requested` and render its
`results.json` with `bench/report.py`. I report distinct admitted error rate, value and document
upper bounds, right-value reviews, silent misses, miss rate and escapes for every field and kind.
I also report unclear exclusions and document counts. The original fixed requests remain the
scoring units. No number is a measure until it comes from this set's generated `results.json`.

## Key and layout diagnostics

The key and layout rule must be measured on two kinds, including one unlike the kind from which
the earlier key rules came. Unkeyed requests alone cannot show whether a wrong column key was
blocked. I declare companion keyed views of the same approved values before any model output:

| Kind | Companion view | Mapping to original fixed requests |
|---|---|---|
| Component datasheet | recommended supply voltage with minimum/maximum keys | supply_voltage_min, supply_voltage_max |
| Component datasheet | operating temperature with minimum/maximum keys | operating_temperature_min, operating_temperature_max |
| Benefit summary | in-network deductible with person/family keys | deductible_individual, deductible_family |
| Benefit summary | in-network out-of-pocket limit with person/family keys | out_of_pocket_individual, out_of_pocket_family |

The exact printed key words, aliases and units are fixed from each source during blind labeling.
The companion views ask for no new year, network, condition or value. Their manifest declares the
mapping and shares the original sealed labels. They are diagnostic views, not extra independent
trials or replacements for the fixed requested-field comparison.

For the decision comparison I use exactly the same new reader text and cached candidates with
the released 0.8 decision and draft 0.9 decision. I do not reuse offsets against different reader
text. I report changed decisions and reason codes against the blind labels in a diagnostic
section of `results.json`. The reader comparison is separate: I compare serialized table columns
and running-head inclusion with blind source layout annotations. This distinguishes a changed
reader from a changed decision or proposer. No source PDF or long source passage is redistributed.

I record whether the new documents actually exercise empty cells, ambiguous columns and running
heads. If a route has no applicable case, I report that limit. I do not claim that aggregate
requested-field success measures a route that the documents do not exercise. A separate corpus
would need a plan and its own kind, field and download approvals before use. I keep the original
rule, vectors and physical margin fixed when reporting held-out results.

No arithmetic relation rule, pack system or later-milestone tool is built here.
