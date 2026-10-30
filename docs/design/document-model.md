# The document model: one structure from the reader for every step

Status: approved by the maintainer on 2026-10-23, with the recommendation of each open question
(section 15). Nothing in this file is built yet. The note changes no decision. Sections 8 and 9
describe a decision change, and that change waits for spec 0.12 (milestone 0.14), with vectors
written by hand. The last section lists the code issues.

## 1. The answers in short

| Question (#285) | My answer | Section |
|---|---|---|
| What the model is | The NFC text that `admit` checks, plus a flat list of nodes. Each node is a UTF-8 byte span into that text. | 4 |
| The node kinds | `heading`, `paragraph`, `list`, `item`, `table`, `row` and `cell`. A section is not a node: lookup derives it from the headings. | 4 |
| Location | Not in the nodes. The page and the boxes of a node come from `layout@1` and the node span. | 4.3 |
| How reliable each source is | Each node records its `basis`: `markup`, `rules` or `layout`. `admit` never reads a node, so no kind from any source changes a decision. | 5 |
| The cache key | The reading cache key of store.md §5.1: the source key, the reader name and version, and the options. The format is `document@1`. | 6 |
| Lookup | Deterministic lookup with the standard library, by id, span, kind and exact text. `admit` does not import it. Ranked search stays with the app. | 7 |
| The structure reader | A proposer in the runner, with its own proposer id. Its code shares no value selection with the core rules. | 8 |
| Agreement | A spec version adds a `proposer` member and a policy rule. Two proposers that disagree on the value or the span give `needs_verification`. | 9 |
| The runner | `extract` takes the document. A chunk is whole sections or whole rows of a table. The character window stays as the fallback. A reply can cite a node. | 10 |

## 2. Three options

**A. Nodes as spans into the hashed text.** The reader writes the text as today, and it also
writes a list of nodes. Each node points into the text. The text does not change, so every
receipt, vector and bench outcome stays the same. Every node is a span that a candidate can cite.

**B. A tree with its own text.** The reader writes a tree, for example HTML or Markdown, and each
part renders the text from the tree. This gives the richest structure. But the rendered text is
then a second text beside the text that `admit` checks, and each offset needs a map between the
two. One error in that map moves evidence to the wrong place.

**C. No model.** This is today. The runner cuts the text by character count, and an app that
needs a section or a table parses the source again. Each part then has its own view of the
document, and no two parts agree on what a table is.

I choose A. It adds structure and keeps one text.

## 3. What the reader gives today

`groundgate.read.read(path)` returns `Extracted(text, layout, warnings)`. Only a PDF has a layout.

- **HTML and XML** (`read/markup.py`). The `_Writer` puts a blank line around each block element,
  a line break after a line element and a tab between two table cells. `h1` to `h6`, `p`, `ul`,
  `ol` and `table` are all the same block element, so the heading level and the list are lost.
- **PDF** (`read/pdf.py`). Words come with boxes in PDF points from the top-left. A page ends with
  `"\n\f"`, a block with a blank line and a cell with a tab. `_tables` builds the rows of a table
  from the height of the text lines, and `grid` gives the cells of a ruled table (#332). The
  reader does not read font sizes, so it finds no headings.
- **Text and Markdown.** The reader decodes the bytes and gives the text with no structure.
- **Layout** (`read/layout.py`, `groundgate_layout` 0.1). Pages and words, each with UTF-8 byte
  offsets into the text. `Layout.locate(start, end)` gives one box for each line of a span.

The runner (`extract/runner.py`) cuts the text in two ways. The first pass uses windows of
`chunk_chars` code points (12000), with `overlap_chars` (1000) of overlap, and it ends a window
at the last line break in its second half. The targeted pass takes `search_context_chars` (1000)
on each side of a query match, merges the windows, and cuts a merged region to
`max_region_chars` (6000) around its best match (#382). Neither cut knows where a table starts
or ends, so a table can lose its column headings.

The store and the runner already reserve space for this note. A `reading@1` object has the member
`document`, null today (store.md §5.1). The store kind `document@1` is reserved, and `forget`
removes it (store.md §8). The run record reserves an input of `kind: "document"` and a `node` key
in an evidence item and a chunk plan entry (runner.md §8).

## 4. The model

### 4.1 The format

```json
{"format": "document@1",
 "source": "sha256:...",
 "reader": {"name": "groundgate.read", "version": "0.13.0"},
 "options": {"pages": null},
 "text": "sha256:...",
 "nodes": [
  {"id": 0, "kind": "heading", "basis": "markup", "parent": null, "start": 0, "end": 17, "level": 1},
  {"id": 1, "kind": "table", "basis": "markup", "parent": null, "start": 19, "end": 64},
  {"id": 2, "kind": "row", "basis": "markup", "parent": 1, "start": 19, "end": 36},
  {"id": 3, "kind": "cell", "basis": "markup", "parent": 2, "start": 19, "end": 24,
   "row": 0, "column": 0, "rows": 1, "columns": 1, "header": true}
 ],
 "doubt": []}
```

- `source` and `text` are the store keys of the `source@1` and `text@1` objects. They are store
  keys, not the core `document_sha256`, because the core digest names the spec version
  (store.md §4). The same bytes then keep one key in each spec version.
- `reader` and `options` are the members of the reading. The object holds them too, so a
  `document@1` file is complete without a store.
- `doubt` is a list of spans that OCR read with low confidence (section 5.2). It is empty for a
  file with a text layer.

### 4.2 The node rules

1. **A span.** `start` and `end` are UTF-8 byte offsets on character boundaries, half-open, as
   SPEC §2.2 says. A node span holds no whitespace at its start or end, so the span text of a
   cell is the text of the cell.
2. **An empty cell.** A cell with no text has `start == end`, at the place of its cell break. It
   keeps the column positions of its row. Nothing can cite it.
3. **Order.** `id` is the position in the list. The list is in text order: a lower `start` comes
   first, and a parent comes before its children.
4. **Nesting.** A node span is inside the span of its parent. Two children of one parent do not
   overlap. A `row` has a `table` as parent, a `cell` has a `row`, and an `item` has a `list`.
   A `heading`, `paragraph`, `list` or `table` has a null parent, or a `cell` or an `item` as
   parent, for a table in a cell.
5. **Members by kind.** Only a `heading` has `level`, 1 to 6. Only a `cell` has `row`, `column`,
   `rows`, `columns` and `header`. `row` and `column` count from 0 in the grid of the table, after
   spanned cells. `rows` and `columns` are the cell span, 1 or more. `header` is true for a
   header cell, false for a data cell, and null when the source does not say. Other members make
   the object invalid.
6. **The text stays.** The nodes never change the text. A reader version that adds nodes gives
   the same text bytes as the version before it.
7. **Gaps.** Not every byte is in a node. A page break, a running head or a blank line can stay
   outside all nodes.

### 4.3 Location

A node has no page and no box of its own. `Layout.page_at(start)` gives its page, and
`Layout.locate(start, end)` gives its boxes. This keeps one source of geometry. A cell of a
ruled table then gets the boxes of its words, not the walls of the cell. That is enough for the
review page, which marks the text.

A spreadsheet has no page. Its location is the sheet, the row and the column. The sheet is a
`table` with a `heading` before it, and the cell members give the row and the column (section 5).

### 4.4 Sections

A section is not a node. The section of a heading starts at the heading and ends at the next
heading of the same level or a lower level number, or at the end of the text. Lookup gives it
(section 7). A source that marks sections, as SPL does, gives the same result through its
heading levels.

## 5. How reliable each source is

### 5.1 The basis of each node

| Basis | Meaning | Sources |
|---|---|---|
| `markup` | The source marks the node: an element, a style or a cell. | HTML, XML, DOCX, XLSX |
| `rules` | The page draws the rules of the table, and `grid` found the cells (#332). | PDF |
| `layout` | The reader inferred the node from positions, font sizes or blank lines. | PDF, OCR, text |

| Source | Headings | Paragraphs | Lists | Tables |
|---|---|---|---|---|
| HTML | `h1` to `h6` | `p` and other blocks | `ul`, `ol`, `li` | `table`, `tr`, `td`, `th`, with `rowspan` and `colspan` |
| XML (SPL) | a `title`, at the depth of its `section` | `paragraph` | `list`, `item` | `table`, `tr`, `td`, `th` |
| Other XML | none | the block elements of `markup.py` | none | only the HTML table names |
| DOCX (#529) | the heading styles | paragraphs | numbered paragraphs | tables |
| XLSX (#529) | the sheet name | none | none | one table for each sheet |
| PDF text layer | none in `document@1` | text blocks (`layout`) | none | rows and cells from `_tables` (`layout`) or `grid` (`rules`) |
| OCR (#7) | none | the blocks of the engine (`layout`) | none | none in the first version |
| Text and Markdown | none | blocks between blank lines (`layout`) | none | none |

A `markup` node says what the author marked, not what the content is. A page can use a table to
place its parts, or a styled `div` as a heading. A hidden element gives no node, because the
reader drops its text already.

PDF headings from font size are a guess. I do not put them in the first version. They can come
later as `layout` headings, and the runner can use them, but they stay information only.

### 5.2 Information only

`admit` never reads a node. A node kind and its basis change no decision, from any source. The
runner uses nodes to cut prompts, and a wrong node gives a worse prompt, never an admitted value
that the core did not check. The structure reader (section 8) uses nodes to propose values, and
its candidates go through `admit` as every candidate does.

OCR doubt is different. A `doubt` span says that the text itself can be wrong. extensions.md
§5.5 says that a value on such text must go to review, and that rule is a decision change for its
own spec version. Until then, `doubt` is information only too, and the report shows it. A doubt
entry is `{"start": s, "end": e, "confidence": c}`, with `c` from 0 to 1 as the engine gives it.

## 6. Identity and the cache key

The key of a reading is the source key, the reader name and version, and the options
(store.md §5.1). The document model is a member of the reading, so it has the same key. If the
reader changes, the key changes, and a stale entry never applies.

- **Byte for byte.** The same bytes and the same reader give the same `document@1` bytes. The
  object is canonical JSON, and the PDF reader already has a stable reading order (#30). A test
  reads each fixture two times and compares the bytes.
- **The reader version.** Today it is the package version, `groundgate.__version__`. Each
  release then gives a new key, also when the reader code did not change. That costs a new read
  after an upgrade, never a wrong entry.
- **The format version.** `document@1` is a format for apps. A change to a member, a kind or a
  rule is `document@2`, and the changelog marks it as a break. An old key never gets a new
  meaning (store.md §8, rule 2).

`read --store` uses the reading cache for a PDF (#519). `read --store --document` writes `document@1` and does not use the cache (#407).

## 7. Lookup in groundgate, search outside

`groundgate.read.document` gives a `Document` class with the standard library only:

| Lookup | Result |
|---|---|
| `node(id)` | one node |
| `at(start, end)` | the innermost node that holds the span, for example the cell of a cited value |
| `of_kind(kind)` | the nodes of one kind, in text order |
| `find(text)` | each exact occurrence of an NFC string, with its innermost node |
| `children(id)`, `section(id)` | the children of a node; the span of a heading's section |
| `cell(table, row, column)` | the cell at a grid position, also when a spanned cell covers it |

Each lookup is deterministic. `find` compares exact bytes, with no case folding and no
whitespace rule, because the search rules of the runner belong to the runner. `admit` does not
import this module.

Ranked or semantic search stays out of groundgate. It needs dependencies, and its order is not
deterministic. The app, or an optional extra, builds that index from the nodes and their text.
I do not ship an extra for it in 0.13.

## 8. The structure reader: a second proposer

A structure reader finds a value with no model: a table cell by its row label and column header,
a `label: value` line, or a form field when a reader gives form fields. The row labels and the
column headers come from the schema `aliases` and `keys`.

It must not be part of the decision. If the gate checks a value with the same lookup that found
it, the check repeats the work of the reader and never finds its errors. A wrong header or a
merged cell then gives a wrong value with full confidence. So:

1. The structure reader lives in the runner, `groundgate.extract`, not in `admit`. Its output is
   a recorded candidate with the proposer id `structure`, as a model answer has a proposer.
2. Its code shares no value selection with the core rules. It reads cells by their grid
   position, and the core checks the key and the field with SPEC §4.5 and §4.6, which read the
   text. A test checks that the module imports nothing from `groundgate.text` or `admit`.
3. If it is the only proposer for a field, the outcome is `needs_verification`. A policy can
   permit admission only after a held-out set shows its error rate.

The candidate cites the value cell as its value item, the row label cell as its field item and
the column header as its key item. Each item has offsets, so the gate checks plain spans. The
candidate also records the basis of the cells that it used, so the measure can split by basis.

The reader proposes nothing when a cell is not clear: two cells match, the path from the label to
the value crosses a cell with `rows` or `columns` above 1, or the header is null. A wrong row is
worse than no row, as `grid` says.

## 9. The agreement rule

The model and the structure reader make different errors. When both propose a field:

- If they agree on the value and the span, `admit` decides as it does today.
- If they disagree, the outcome is `needs_verification`, and the review page shows both
  candidates.

Part of this exists. If two candidates for one field and key pass with different canonical
values, each gets `CONFLICTING_CANDIDATES` (SPEC §3.3). The core does not know proposers:
SPEC §2.5 ignores a member such as a proposer name. The spec version adds:

1. An optional candidate member `proposer`, a non-blank string, which the decision records.
2. A policy member `proposers`, a map from a proposer id to `admit` or `corroborate`. A proposer
   that the map does not name is `admit`, so a packet with no map keeps its outcome.
3. A flag for a passed candidate of a `corroborate` proposer with no passed candidate of another
   proposer that agrees with it.
4. A flag for two passed candidates of different proposers, where the policy names at least one
   as `corroborate`, with the same canonical value and value spans that do not overlap.

Agreement is a passed candidate of another proposer, for the same field and key, with the same
canonical value and a value span that overlaps. This changes decisions, so it is a new spec
version. I write the vectors by hand in `conformance/build.py` before the code.

## 10. Use in the runner

#286 renamed the steps: the reader is `read`, and the runner is `extract`.

- **The input.** `extract` takes a `Document` as an alternative to `text`. The text is the text
  of the document, and the runner checks it against the `text` key. The run record names the
  document key and the reader in its `kind: "document"` input. This is a record change, so it
  comes with `groundgate-run/5` and the store keys of #429, as one break.
- **The first pass.** The runner packs whole top-level nodes into chunks of at most
  `chunk_chars` code points, in text order. A section that is too large splits at its children.
  A table that is too large splits between rows, and each part also sends the header rows of the
  table as a second region. Only a single row that is too large falls back to the character
  window. Each chunk also sends the headings above it as a small region, so the model sees the
  heading of a table in two parts. A document with no nodes uses the character window as today.
- **The targeted pass.** A region that the runner cuts to `max_region_chars` moves its ends to
  the nearest row or cell boundary, and it keeps the header rows of its table.
- **Node citations.** An evidence item can have `node` with `text`. The runner finds the quote
  inside the node and sets the offsets. If the quote occurs zero or two or more times in the
  node, the reply is invalid. An item with `node` and no `text` is valid only for a cell, and it
  gets the span of the cell. `node` must be an id that the prompt marked (see the next item).
  Any other id is an invalid reply. `admit` sees only offsets.
- **Node ids in the prompt (#526).** The maintainer approved this format on 2026-10-23. It is
  part of `groundgate-run/5`. The text that `admit` checks does not change.
  1. Only a `cell` node with text, inside a document region of the prompt, gets an id. Other
     kinds get no id. A model cites them with a quote.
  2. The runner puts `⟦N⟧` (U+27E6, the id in decimal, U+27E7) directly before the text of each
     such cell, in the region text that it sends. The prompt digest covers the marked text. The
     document text and its offsets do not change. The `length` of the region is the length of
     the marked text.
  3. If the text of a region already holds U+27E6 or U+27E7, that region gets no markers, and
     the region says `"node_ids": false`. A document cannot forge an id.
  4. The instructions of a run on a document get one more part: a marker gives the id of a cell,
     and a marker is not part of the text, so do not copy it. The runner removes only the markers
     that it put in. It first searches for the quote as the model gave it (in the node for a
     node citation, else in the document text). Only if that search fails, it removes each
     `⟦digits⟧` and searches again. Thus `A⟦12⟧B` from a region with no markers keeps its text.
     A quote of only markers is a protocol failure.
  5. In the output schema of a run on a document, a document evidence item can also be
     `{source, role, node}` or `{source, role, node, text}`, with `node` an integer. A text run
     keeps its schema and its instructions.
  6. `node` must be an id that this prompt marked. Any other id makes the reply invalid, as an
     unknown id did before.
  7. The markers count against `max_prompt_chars`, and the chunk packing counts the marked
     length. A row that falls back to the character window counts only its text, so a window can
     be longer than `chunk_chars` by its markers.
  8. The run record gets no new header member. The prompt digests and the instruction text
     record the change. There is no SPEC change and no conformance vector: the core never reads a
     node.

Node text in a prompt is document data, and the prompt marks it as untrusted, as it does for all
document text (runner.md §3).

## 11. Use in the review page and the store

- **Review.** A node id can be a place in a task (review.md §11). The `structure` item kind
  (review.md §7, #414) asks about each node that the app uses, for example the cell that a field
  cites. The page draws the boxes of a node from the layout.
- **The store.** `document@1` is the canonical JSON of section 4.1, and the `document` member of
  `reading@1` names its key. `forget` removes it, because a node span with the text gives the
  document text (store.md §8).

## 12. Untrusted input

A `document@1` from a store or a file is untrusted. The loader checks it as `Layout.from_dict`
checks a layout, and it refuses the object at the first fault:

- the format, the members of each kind, and keys that match `sha256:[0-9a-f]{64}`;
- integer offsets within the text bytes and on character boundaries;
- the order, the nesting and the parent kinds of section 4.2;
- a limit on the number of nodes, as the store has a byte limit.

The lookup uses sorted starts and `bisect`, so a large document costs time in proportion to its
nodes, not to their square.

## 13. The measure

The 1.0 measure (#277) gives the admitted error rate for each proposer and for agreement, on
documents that the rules were not written from. It never mixes the three. The miss rate (#269)
shows the fields that only the structure reader found. No rule of this note is tuned on the v0.1
set or set 2.

## 14. Not in scope

- Markdown or any other rendering. The app builds its own artifacts from the nodes.
- A search engine in groundgate.
- Dates and other normalised text (SPEC §7).
- Geometry as evidence. SPEC §7 keeps PDF geometry out of the decision, and this note does not
  change that.

## 15. Open questions

The maintainer chose the recommendation for each question on 2026-10-23.

1. **Node ids.** An integer position in the list, or a path such as `t3/r4/c2`? I recommend the
   integer. It is short in a prompt, and the key already makes it stable for one reader version.
2. **Location.** Derive the boxes from the layout, or store them in each node? I recommend the
   layout, so that there is one source of geometry.
3. **Sections.** A derived span, or a `section` node kind? I recommend the derived span. A node
   kind adds a parent to every paragraph and gives no new fact.
4. **OCR doubt.** Record only the words under a reader threshold, or the confidence of every OCR
   word? I recommend every word with a confidence below 1. A later spec version then chooses the
   threshold with no new read.
5. **The reader version.** The package version, or a separate reader version? I recommend the
   package version. A separate number is one more thing to forget in a release.
6. **Same value, other span.** Is it a disagreement? I recommend yes, but only when the policy
   names one of the two proposers as `corroborate`. Two model proposers then keep the current
   outcomes.
7. **The default for the structure reader.** The core or the runner? I recommend the runner:
   it runs the structure reader only when the policy names `structure` in `proposers`. Then the
   core knows no proposer names, and no packet of today changes its outcome.
8. **Text files.** Paragraph nodes only, or also Markdown headings? I recommend paragraphs only.
   A `.md` file stays plain text, as the reader reads it today.

## 16. Code issues

I open these after the maintainer approves this note.

1. **The document model in `groundgate.read`.** Nodes for HTML, XML, PDF blocks and tables, and
   text. The `document@1` format, the loader checks, the lookup of section 7, and
   `read --document FILE`. A test shows that the text bytes do not change on each test fixture.
   Needs a security review.
2. **The store.** `read --store` writes `document@1` and uses the reading cache (#407).
3. **The runner.** The document input, node chunks and node citations, with `groundgate-run/5`
   and #429. The record format changes, so the maintainer decides first.
4. **The spec version.** `proposer`, the policy member `proposers` and the two flags of section 9.
   Vectors by hand first. This changes decisions.
5. **The structure reader.** After issue 4.
6. **The review kind `structure`.** #414.
7. **The readers of #7.** DOCX and XLSX nodes, and OCR nodes with `doubt`.
8. **The measure.** Section 13.

Issues 1, 2 and 3, and the OCR nodes of issue 7, are in 0.13. Issue 6 (#414), its crop view
(#537) and the DOCX and XLSX nodes of issue 7 (#529) moved to 0.14. Issues 4 and 5 change
decisions: they are in spec 0.12, milestone 0.14. Issue 8 needs issue 5, so it is in 0.14 too.
