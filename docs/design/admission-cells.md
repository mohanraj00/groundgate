# Table cells in admission

Proposed for spec 0.12 (#622). The maintainer decides this note before I change the spec or
write the implementation. The approved [columns and markers note](columns-markers.md) chose
text slots. This proposal gives the core cell positions while keeping the checks of the cited text.

## Packet input

I propose an optional `table_cells` member. The application projects it from the table, row and
cell nodes of a checked `document@1` of the same NFC text. Each table gives its UTF-8 byte span
and a list of cells. Each cell gives `start`, `end`, `row`, `column` and `header` as in
`document@1`. The application supplies the table input. A proposer supplies only citations.

The first version projects only tables with no nested tables or spanned cells. It keeps the
empty cells, which have zero-length spans and cannot be cited. It omits a table with a row or
column that the reader could not place. The core validates the bytes, types and limits of the
projection. Tables are disjoint and in text order. Cells lie in their table in row and column
order, with one cell per grid position. A span cannot cross a page break. A malformed projection
makes the packet invalid.

The receipt names the digest of the projection when present. The store keeps that projection
with the packet. Verify and replay take the same input and re-derive the digest. The reader's
source file is outside the core. An application that can replace the cell input can change the
decision, as it can with the schema or policy. No model reply can replace that input.

## Rule

For a value found wholly in a projected cell, a field with aliases needs a passing field item
(#450). An item may cite an alias in the row's first cell, before the value. Without a column
rule, the value must be in the next cell. An item may also cite an alias in an explicit header
above the value in the same column of the same table. An intervening header for that column
ends the earlier header's reach. An item in a different row or table cannot stand in for either.

A field with `columns` still needs the column word for the value. With cell input, a column
item can cite an explicit header in the same column and table. The core still checks the
header's text and the token in its cell. A header marked unknown can pass the existing text
rule only where the text slots agree with the projected column. The value goes to review if
neither proof passes. A cell under `Max` cannot stand for a blank `Typ` cell.

The answer `$400 person/$800 family` still needs the marker at the amount (#426). A valid row
label does not let the second amount cross the first number by itself. The existing marker,
clause and four-word rules still apply. A candidate that calls the second amount `person` goes
to review. The range rule remains separate (#586).

When the packet omits the projection, the current text rules apply. Text outside a projected
table and evidence from another source still use their own text rules.

## Checks before the run

I write vectors for a blank typical column, a cited header in a different table, an omitted
field item, a two-amount answer with correct and swapped markers, and a packet without cells.
Invalid vectors cover a split UTF-8 character, a duplicate coordinate and a span outside its
table. I check that stored verification rejects a different projection and that lookups index
the grid once.

The PDF reader currently records unknown headers. I keep unknown distinct from explicit.
For the development run, I first measure how many values the current reader can place and
report any missing column evidence. If the benchmark needs PDF header inference, that needs
its own rule and vectors. I score the runner on the development split before any held-out
run. The held-out labels are fixed before a model sees those documents.
