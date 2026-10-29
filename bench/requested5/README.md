# Requested fields: the lane 2 held-out set

Status: I selected the members on 2026-10-29 and 2026-10-30, before any model output on this set
(#548). The manifest is a draft: the labels, the arms and the code freeze come later. No model
call has run on this set.

The set has 32 documents, and all of them are in the held-out split. It measures the 0.14 code
and the lane 1e terms (`bench/requested4/terms-547.json`) on documents that no rule came from.
The terms are not in the schemas here: a held-out run gives them as a separate input.

| Kind | Members | Group B members |
|---|---:|---:|
| component | 6 | 2 |
| sbc | 7 | 1 |
| annual | 7 | 4 |
| sds | 6 | 1 |
| scanned | 6 | 6 |

The kinds `component`, `sbc`, `annual` and `sds` use the schemas and the fixed requests of
[bench/requested4](../requested4). The new kind `scanned` holds old annual reports that exist only
as page scans. It uses a copy of the `annual` schema and the `annual` request. A document schema
changes only the reporting currency of an annual report or a scanned report. No publisher,
employer or family of bench/requested, bench/requested2, bench/requested3 or bench/requested4 is a
member.

## Format

The manifest uses `requested-fields/1` with no change to the members of bench/requested4. It has
no `split_rule`: a split rule needs a development share between 0 and 1, and this set has only a
held-out split. Each document has `"split": "heldout"`.

A scanned document has 2 more members (#548):

- `image_only`: the copy of the scan that the OCR arm reads. It has the copy's `sha256`, its
  `bytes`, the `method` and its `resolution_dpi`, and the `renderer`. The method
  `image-only-render/1` renders each page with the renderer at the resolution and keeps only the
  page images. `bench/requested/image_only.py` (#551) makes this copy:
  `PYTHONPATH=bench uv run python -m requested.image_only --dpi 350 SOURCE.pdf OUT.pdf`. The
  method `image-only/1` keeps the page images with no change, and its `resolution_dpi` is null.
  No document of this set uses `image-only/1`, and no tool in this repository makes it yet.
- `source_layer_text_sha256`: the reader text of the text layer in the original download. That
  layer comes from the archive's OCR, so a second arm can compare it with groundgate's OCR.

`source`, `source_bytes`, `source_sha256` and `approved_max_bytes` stay the original download.
`text_sha256` of a scanned document is the text that `groundgate read --ocr` makes from the
image-only copy. `bench/requested/run_set.py` and `bench/requested/diagnostics.py` read the
image-only copy as `<id>.pdf` for a document with `image_only`, and check its hash and its size. Other documents are checked as
before.

## Selection

The maintainer approved each source and its size. Before that I read only catalog pages and terms
pages, and I sent HEAD requests for the sizes. Terms group A gives no use limit that applies to a
private copy. Terms group B allows only personal, noncommercial or internal use, so a group B
member is a member only for local, internal measurement. Each scan comes from the Internet Archive,
which grants access for scholarship and research use, so all 6 scans are group B.

After each download I checked the identity, the period or revision, the text layer, the language
and the printed notices. Each download has the approved size. 10 approved candidates are not
members:

- 2 component datasheets are on hold: their own notice says that they "shall not be reproduced
  without permission".
- 4 component datasheets and 1 SBC failed: the server answered 403.
- 2 SBCs are a carrier benefit summary, not the SBC form.
- 1 annual report failed: its URL now goes to a server message and then to 404.

One annual report is a member with a limit: each page of the exchange copy has the stamp "For
personal use only", so it is group B.

The maintainer dropped 7 more candidates before download. Selection used publisher metadata,
notices and layout eligibility. It never used a requested value or a model output.

## Sources and reader text

`manifest.json` records each source URL, byte size, PDF hash, reader text hash, terms group and
license note. The originals, the image-only copies and the reader texts stay in local work storage
and are not published.

The reader text of each document comes from `groundgate read` at the commit in `reader_text`. The
text of a scanned document comes from `groundgate read --ocr` with tesseract on the image-only
copy. One annual report has a PDF flag against text extraction. The reader does not obey that
flag, and the text stays private like every other reader text.

## Labels

The maintainer labels each slot blind from the original PDF with `bench/requested/label_app.py`.
The page shows the original page beside the fields. Each number field names every part to check:
the row, the period or condition, the amount with its printed scale and sign, and the unit.
