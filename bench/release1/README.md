# The 1.0 release set: three new kinds

Status: design. The kinds, the fields and the field rules wait for the owner approval in #748.
No member is chosen and no document body is downloaded.

This set gives the numbers of exit conditions 1 and 2 of #277: the admitted error rate with
a bound for each field and each kind, the miss rate, and the share of right values sent to
review. It is for release measures only. No development run uses it, and no rule, pack or
profile is tuned on it. A fix that a result of this set shows goes to the next release, and
its claim needs a new set.

## Targets

The owner set these targets on 2026-11-27 (#748). They apply to the held-out part of this set,
and I write them here before the run:

| Measure | Target |
|---|---|
| Miss rate | at most 40% |
| Share of right values sent to review | at most 35% |

The miss rate counts labels with a value that got no admitted right value. The review share
is the right values that went to review, divided by all labels with a value.

## The kinds of the current sets

I read every folder under `bench/`. The current sets have these kinds:

| Kind | Sets |
|---|---|
| FDA drug labels (DailyMed) | set 2, `bench/fields`, `bench/keys`, `bench/conflicts`, `bench/relations`, `bench/tables`, `bench/strings`, probe sets |
| IRS publications | set 2, `bench/status`, probe sets |
| Federal Register final rules | set 2, `bench/caps`, `bench/dots`, `bench/patterns` |
| NTSB reports | set 2, `bench/aviation` |
| SEC 10-K filings | `bench/sec`, `bench/sec2`, `bench/sec3`, `bench/outside` |
| SEBI documents | `bench/india` |
| State and federal annual financial reports | `bench/acfr`, `bench/acfr2`, `bench/afr`, `bench/pdfrows` |
| Company annual reports, component datasheets, benefit summaries (SBC), safety data sheets, scans | `bench/requested` to `bench/requested5` |
| CFR parts | `bench/regulatory`, `bench/regulatory2` |

No set has patents, court opinions, committee reports of Congress, mineral commodity
summaries or funding notices. The candidates below come from these.

## Candidate kinds

Each kind has four fields, one of each value kind where the layout permits. Each member gets
one slot for each field, so a kind with 30 members has 120 slots. A seed draws no slot: each
field asks for the one value that the field rule names.

### 1. US patent grants

- Source: the USPTO weekly full text of patent grants, XML with no images
  (bulkdata.uspto.gov). A member is one grant of one weekly file.
- Terms: the USPTO terms page says that the text and drawings of a patent are typically not
  subject to copyright. Some specifications print a copyright notice for a part of the text
  (37 CFR 1.71). The source check flags each notice, as in `bench/regulatory`, and a member
  with a notice is on hold.
- Cost: a weekly file holds all the grants of that week. The download script keeps only the
  members and deletes the rest of the file before any read. The owner approves this step.

| Field | Kind | Field rule |
|---|---|---|
| `filing_date` | date | The filing date of the application, as the front page states it. |
| `claim_count` | number | The number of claims that the patent states. |
| `first_claim` | passage | The full text of claim 1, without its number. |
| `cited_patents` | record | The cited US patent documents of the front page, one record for each, with the members `number`, `date` and `name`. |

### 2. US federal appellate opinions

- Source: the USCOURTS collection of govinfo (US courts of appeals). A member is one opinion
  PDF of one package.
- Terms: the govinfo policy says that public documents can generally be reprinted without legal
  restriction. Judicial opinions are government edicts with no copyright. The govinfo API needs
  an api.data.gov key, with a limit of 1,000 requests each hour.

| Field | Kind | Field rule |
|---|---|---|
| `decision_date` | date | The date on which the court filed or decided the opinion, as the opinion states it. |
| `disposition` | passage | The last paragraph of the opinion of the court that states its disposition (for example affirmed, reversed or remanded). |
| `award_amount` | number | The one sum of money that the judgment awards or affirms, with its currency. If the opinion states no such sum, or more than one, the field is absent. |
| `panel` | record | The judges of the panel that the caption or the first page names, one record for each, with the members `name` and `role` (author, concurring or dissenting; null if not stated). |

### 3. Committee reports of Congress

- Source: the CRPT collection of govinfo (House and Senate reports on bills). A member is one
  report PDF of one package.
- Terms: the same govinfo policy as kind 2. Reports are works of the US government
  (17 U.S.C. 105). A part that the report quotes from another publisher can have its own
  copyright, so the source check flags each notice.

| Field | Kind | Field rule |
|---|---|---|
| `report_date` | date | The date on which the report was submitted or ordered printed, as its first page states it. |
| `purpose` | passage | The text of the section on the purpose and summary of the bill. |
| `cbo_total` | number | The total of the CBO cost estimate over its full period, in the unit that the table states. Absent if the report has no CBO estimate. |
| `cbo_table` | record | The rows of the CBO table of estimated budgetary effects, one record for each row, with one member for each column header. Absent if the report has no such table. |

### Spare A: USGS Mineral Commodity Summaries

- Source: the 2026 Mineral Commodity Summaries of USGS (pubs.usgs.gov). A member is one
  commodity chapter of two pages.
- Terms: USGS products are works of the US government. The USGS copyright page refused a
  scripted fetch on 2026-11-27, so I must read it by hand before the owner decides.
- Fields: `us_production` (number), `salient_statistics` (record), `events_trends` (passage)
  and `world_reserves` (number). This kind has no date field.

### Spare B: notices of funding opportunity

- Source: the funding notices of Grants.gov, through the read-only API of simpler.grants.gov
  (an API key, 60 requests each minute).
- Terms: works of the US government. I found no reuse statement on the developer pages, so the
  terms are less clear than for the other kinds.
- Fields: `award_ceiling` (number), `close_date` (date), `eligibility` (passage) and
  `key_dates` (record).

## Members, split and labels

| Item | Plan |
|---|---|
| Members | 30 for each kind, 90 in all, from publisher metadata only |
| Calibration | 5 for each kind, for the operating point only |
| Held-out | 25 for each kind, 75 in all, with 100 slots for each kind |
| Seed | the SHA-256 of the source digests in member order, one on each line, after the download and before any label; the 5 ids of each kind with the lowest SHA-256 of the seed, a line feed and the id are calibration |
| Labels | the method of `bench/regulatory`: two blind passes by two harnesses, a second blind check of each absence, an owner decision on each other slot, then the seal |
| Run | one held-out run on the release candidate commit, which the run record names |

The metadata for the member choice:

- kind 1: the weekly file list of the USPTO bulk data, and the bibliographic data of the grants
  of one week (patent number, title, CPC class, claim count of the metadata);
- kinds 2 and 3: the govinfo collection and package summary API (court, date, title, page
  count, bill number).

The member rule spreads each kind across sources of different layouts: CPC sections for
patents, circuits for opinions, and committees and the two chambers for reports. I record the
rule before the choice, and I never read a body to choose.

## Open decisions

1. The three kinds: 1, 2 and 3, or a spare in place of one of them.
2. The fields and the field rules of each kind.
3. The approval to select members from metadata as this section says. The member list then
   goes to the owner before any download.
