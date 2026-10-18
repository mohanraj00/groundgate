# Requested fields: the 0.10 set

Status: I froze the manifest on 2026-10-18, before any model output on this set (#308). The set
has 79 documents: 3 development pilots and 76 held-out (25 component datasheets, 28 SBCs and 23
annual reports). I sealed the labels on 2026-10-18. No model has run on this set.

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

| Kind | Slots | Present | Absent | Unclear |
|---|---:|---:|---:|---:|
| component | 130 | 96 | 0 | 34 |
| sbc | 145 | 122 | 16 | 7 |
| annual | 144 | 90 | 52 | 2 |

The manifest is frozen and the labels are sealed before the first model call. Next I run both
arms with one frozen configuration on the 0.10 main commit, and score with:

```bash
uv run python bench/score.py --requested --set bench/requested2 --split heldout
```
