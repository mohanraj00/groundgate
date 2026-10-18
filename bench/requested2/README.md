# Requested fields: the 0.10 set

Status: I froze the manifest on 2026-10-18, before any model output on this set (#308). The set
has 79 documents: 3 development pilots and 76 held-out (25 component datasheets, 28 SBCs and 23
annual reports). I sealed the labels on 2026-10-18. Both arms ran on the held-out split on 2026-10-18.

The 0.10 rules (#300, #301) came from the 0.9 held-out set in [bench/requested](../requested).
That set cannot measure them. This set uses the same three kinds and the same fixed requests,
which the maintainer approved on #269, on new documents:

| Kind | Fixed requested fields |
|---|---|
| Electronic component datasheets | recommended supply voltage minimum and maximum (V); typical supply current (mA); operating temperature minimum and maximum (C) |
| Health plan Summary of Benefits and Coverage | in-network deductible for one person and for a family (USD); in-network out-of-pocket limit for one person and for a family (USD); in-network specialist visit copay (USD) |
| Annual reports from outside the U.S. in English | revenue; cost of sales; gross profit; total assets; total liabilities; total equity |

No 0.9 document is a member, and no publisher or employer of the 0.9 set is used again. The
schemas, the request context and the scoring rules are the ones of the 0.9 set. A document schema
changes only the reporting currency of an annual report.

## Selection

On 2026-10-18 the maintainer approved 92 downloads in chat, in two rounds: 35 component
datasheets, 30 SBCs and 27 annual reports. Before each round I read only catalog pages and terms
pages, and I sent HEAD requests for the sizes. Other sources stayed on hold, because their terms
forbid robots, scraping or all copying, or because I could not read the terms.

After each download I checked the identity, the period, the text layer and the printed notices.
13 downloads are not members (`source_checks.json` gives each reason):

- 9 component datasheets and 2 annual reports print a ban on reproduction without written
  permission.
- 1 SBC is a scanned carrier summary, not the SBC form.
- 1 annual report has a 6-month transition period as its latest period, not a full year.

Every other download is a member. I made no subsample. The development pilot of each kind is
the lowest ID whose source family has one member: component-c04, sbc-c30 and annual-c01.

Selection uses publisher metadata, notices and layout eligibility. It never uses a requested
value or a model output. Plans of one employer and datasheets of one family stay in one split.
`manifest.json` records each source URL, byte size, PDF hash and reader text hash. The originals
and the reader texts stay in local work storage and are not published.

## Labels and measure

Two blind passes labeled all 419 slots from the original PDFs, with the rules of the 0.9 set.
Each pass confirmed each present value on a render of its PDF page. The passes gave the same
label on 407 slots (97.1%). An independent check of the original PDF decided the other 12. Each
absence has a second blind check: both passes, or the independent check.

The review of this PR changed 5 slots before any model output. Two annual reports print no total
liabilities line on the balance sheet, but print the consolidated total in the segment note. That
total is now present, as for total assets. One datasheet had two unclear temperature slots. Its
operating range is now present, because the other row is an absolute maximum rating. One annual
report had an unclear revenue slot. Its own statement has no revenue line and the other candidates
are agency-only accounts, so revenue is now absent.

| Kind | Slots | Present | Absent | Unclear |
|---|---:|---:|---:|---:|
| component | 130 | 98 | 0 | 32 |
| sbc | 145 | 122 | 16 | 7 |
| annual | 144 | 92 | 51 | 1 |

## Held-out results

I ran both arms on the 76 held-out documents on 2026-10-18, on main 4c3da85, with one frozen
configuration (`runs/`, `results.json`, `RESULTS.md`). The model, transport and run limits are the
same as in the 0.9 run. The labels were sealed before this output. The scorer counts 300 labeled
values that the documents state. 39 unclear slots are not counted.

| Arm | Right values admitted | Right absences | Escapes | Reviews | Silent misses | Miss rate |
|---|---:|---:|---:|---:|---:|---:|
| baseline | 44 | 0 | 11 | 231 | 25 | 85.33% (256 of 300) |
| runner | 34 | 15 | 0 | 241 | 25 | 88.67% (266 of 300) |

- The runner admits no wrong value. The baseline admits 11 wrong values of 55, all in annual
  reports (11 of 16). Combined upper bound: baseline 49.46%, runner 31.23%.
- The runner misses more right values than the baseline: 266 against 256. Silent misses are the
  same (25). The difference is values that the runner sends to review and the baseline admits.
- The SBCs give the runner 15 right absences and 0 silent misses for both arms. SBC miss rate is
  77.12% for the baseline and 80.51% for the runner.
- The runner did not complete 15 of the 23 annual reports and 1 datasheet. Each one stopped at the
  search limit, with no transport error. Their unadmitted present fields count as misses. Annual
  miss rate is 94.32% for the baseline and 98.86% for the runner.
- Three baseline calls failed with a transport error at the last call of a document. The harness
  archived each one and ran it again (`Transport retries` in `RESULTS.md`).
- The miss rate is above 85% for both arms. 0.10 does not meet the goal on this set, and the
  runner does not beat the baseline on misses.

To score again:

```bash
uv run python bench/score.py --requested --set bench/requested2 --split heldout
uv run python bench/score.py --requested --set bench/requested2 --split heldout --check
```
