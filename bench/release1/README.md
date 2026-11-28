# The 1.0 release set: three new kinds

Status: member list. The owner approved the kinds and the member choice from metadata on
2026-11-27 (#748). On the same day the owner picked spare A, the USGS Mineral Commodity
Summaries, as kind 1 in place of patents. `members.json` has 30 chapters, 30 opinions and 30
reports. On 2026-11-27 the owner approved the list with the words "Yes, keep one" (one report
on HR 3944). I downloaded the 90 PDFs on 2026-11-27, and all 90 pass the source checks.
`manifest.json` pins each source and its split. The slots and the labels come next.

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

### Not chosen: US patent grants

The owner replaced this kind with spare A on 2026-11-27, because the USPTO bulk data now needs
an API key. The plan stays here as a record.

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

### 1. USGS Mineral Commodity Summaries (spare A, chosen 2026-11-27)

- Source: the Mineral Commodity Summaries 2026 of USGS
  (https://pubs.usgs.gov/periodicals/mcs2026/). A member is one commodity chapter, one PDF
  file of the index.
- Terms: I read the USGS page "Copyrights and Credits" by hand on 2026-11-27
  (https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits). It says
  that USGS-authored or produced data and information are in the US public domain. Some
  non-USGS images and graphics are used with permission and are generally marked as
  copyrighted. USGS asks for credit, for example "Credit: U.S. Geological Survey". The source
  check flags each notice, and a member with a notice is on hold.

| Field | Kind | Field rule |
|---|---|---|
| `us_production` | number | The first production value of the latest year in the table "Salient Statistics, United States", with the unit of the table. Absent if the table withholds the value (W) or gives none. |
| `world_reserves` | number | The world total of the reserves column in the table "World Mine Production and Reserves", with its unit. Absent if the table states no world total. |
| `events_trends` | passage | The full text of the section "Events, Trends, and Issues". |
| `salient_statistics` | record | The rows of the table "Salient Statistics, United States", one record for each row, with the member `item` and one member for each year column. |

This kind has no date field. I expect a chapter to state years, not dates: the year columns
of its tables and the years in its text. The only dates in the metadata are the dates of the
files and of the release, and almost all chapters share them. A date field would ask for
the same value in almost each chapter, so it measures nothing. The fourth field is a second number of a different
table. I opened no chapter to choose the fields. If the download shows a date that each
chapter states, the owner can change this field before any label.

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

- kind 1: the file index of the Mineral Commodity Summaries 2026 and a HEAD request for each
  chapter (size, entity tag, date of change);
- kinds 2 and 3: the govinfo collection and package summary API (court, date, title, page
  count, bill number).

The member rule spreads each kind across sources of different layouts: CPC sections for
patents, circuits for opinions, and committees and the two chambers for reports. I record the
rule before the choice, and I never read a body to choose.

## The member choice

`select.py` chose the members on 2026-11-27 from the govinfo sitemaps and the MODS record of
each package. The cache holds 13 sitemaps and 1,012 MODS records, and no document body. The order of the candidates
in each group is the SHA-256 of a fixed tag, a line feed and the package id.
`members.json` keeps each member and each rejected candidate with its reason.

Kind 2, opinions of 2025:

- Courts: the 11 regional circuits and the Federal Circuit (`ca13`). govinfo has no 2025
  sitemap for the DC Circuit.
- A member is from an appellate court, has 1 document in its package, has 6 to 60 pages and
  was issued in 2025.
- One opinion can be filed in two or more dockets. A package with the same docket entry
  number in the same court as an earlier member, or the same title, date of issue and page
  count, is out. In Re: Fairfield Sentry Limited has 3 packages in the Second Circuit, and the
  set keeps the first.
- The rule takes 2 members from each court first. Then it takes one more at a time from the
  courts with the most 2025 packages, until there are 30. It examines 40 candidates of a court
  at most.
- The result: 11 courts, 2 or 3 members each, 6 to 51 pages. The Eighth Circuit has no
  member. Its first 40 candidates have fewer than 6 pages, because most of its packages are
  short orders.

Kind 3, reports of 2025:

- A member is an HRPT or SRPT report on one bill, with a primary bill and a committee, and
  has 8 to 150 pages. Reports of the House Rules Committee and the Senate Rules Committee are
  out, and so are titles that are not about one bill (activity reports, allocations,
  oversight plans, conference reports).
- The same twin rule applies: the same title, date of issue and page count is out. No report
  of the list has a twin.
- One bill gives at most one member. A report on the same primary bill as an earlier member is
  out, also if it comes from the other chamber. The first report in the selection order stays.
- The rule takes one report from each committee first, then a second pass, until there are 15
  for each chamber.
- The result: 15 House and 15 Senate reports from 18 committees, 8 to 132 pages. The first
  list had two reports on HR 3944 (military construction appropriations): the House report
  119hrpt161 and the Senate report 119srpt43. On 2026-11-27 the owner chose to keep one. The
  House report is first in the selection order, so it stays. The Senate report is out, and
  the next Senate candidate, 119srpt38 (S 2257, legislative branch appropriations, 62 pages),
  takes its place.

Kind 1, USGS chapters of 2026:

- The candidates are the files `mcs2026-NAME.pdf` of the index. The appendixes are out. A file
  `NAME_ver.N.pdf` is an earlier version of a revised chapter, so it is out. A file with the
  same entity tag as an earlier member is the same file, so it is out.
- The rule takes the first 30 candidates in hash order. A chapter has the same layout as each
  other chapter, so the rule does not spread them across groups.
- The result: 30 chapters, 114 to 173 KB, except molybdenum (748 KB). USGS revised the
  molybdenum chapter on 2026-04-15 (version 1.2 of the release, one sentence on the price).
  The member is the current file.

USPTO patents: the USPTO bulk data now needs an API key of the USPTO Open Data Portal. The old
bulk data site did not answer on 2026-11-27. I made no request with a key.

## Sources

Each member is one PDF of its publisher: the chapter file of the USGS index, or the PDF
rendition that the MODS record of the govinfo package names. The PDFs and the reader text stay
in local work storage.

```bash
WORK=/path/outside/the/repo
uv run python bench/release1/sources.py --out "$WORK/release1-sources" \
  --meta "$WORK/release1-metadata" --fetch
```

The script refuses a list that the owner has not approved. It does these checks on each
member:

- identity: a USGS chapter has the size and the entity tag of the selection, names its
  commodity on the first page, and names the series line "U.S. Geological Survey, Mineral
  Commodity Summaries, February 2026". An opinion gives its docket on the first page. A report
  gives its number, for example 119-161, on the first page;
- the page count of a govinfo PDF is the page count of its MODS record;
- the text is not empty, and it is English text;
- each match of copyright, the copyright sign, "all rights reserved", "reproduc" or
  "permission of" is a place for a person to read.

It writes `manifest.json` and `source_checks.json`. A rerun with a changed PDF or a changed
reader text fails before it writes a file.

I downloaded the 90 PDFs on 2026-11-27. All 90 pass the checks, so no member is on hold, and
`selection_complete` is true. 82 members have no notice match. I read each of the 53 matches of
the other 8 members, and `notice_review` of `members.json` records each review. Each match is
text of the source: the Copyright Act or copyright claims in three opinions, the Copyright
Office budget and reproductive health services in two reports, a reproduced contract clause,
the permission of a court, and cesium iodide for reproduction into new X-ray panels. No source
has a notice of the publisher or of another owner.

The seed is the SHA-256 of the 90 source digests in member order. The calibration members:

| Kind | Calibration |
|---|---|
| minerals | rubidium, cesium, iron-steel, gold, magnesium-metal |
| opinions | ca1 24-02002, ca4 24-04340, ca5 24-40662, ca11 24-13668, ca13 23-01663 |
| reports | 119hrpt383, 119srpt51, 119srpt50, 119srpt58, 119srpt65 |

## Decisions

1. The fields of kind 1 and the member lists of the three kinds: the owner approved them on
   2026-11-27 ("Yes, keep one"), on the #748 comment that holds the lists and the field set.
