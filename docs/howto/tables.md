# Check values in financial tables

A financial table puts many similar numbers close together. A right value needs its row, its
column, its scale and often its sign. Each of these parts is at a different place in the table.
This page shows how to make groundgate check every part. The table and the numbers are made up.

The [guide](../guide.md#evidence-items) has the rules for each evidence item. SPEC §4.5 and §4.6
in [SPEC.md](../../SPEC.md) are the normative version.

## 1. Get the text with tabs between cells

`groundgate extract` writes a tab between two cells of an HTML table, and a line break after each
row. The tab is important: it tells groundgate where the row label stops and the first cell
starts.

1. Save the page as an `.html` file.
2. Extract it with `groundgate.extract.extract`, or with `groundgate extract FILE` on the command
   line.
3. Give the same text to the extractor and to `admit`.

```python
import tempfile
from pathlib import Path

import groundgate as gg
from groundgate.extract import extract

html = """<html><body>
<p>CONSOLIDATED STATEMENTS OF OPERATIONS</p>
<p>(in thousands)</p>
<table>
<tr><th></th><th>2025</th><th>2024</th></tr>
<tr><td>Net sales</td><td>$ 84,210</td><td>$ 79,605</td></tr>
<tr><td>Cost of sales</td><td>61,930</td><td>58,114</td></tr>
<tr><td>Operating expenses</td><td>25,695</td><td>24,471</td></tr>
<tr><td>Loss from operations</td><td>(3,415)</td><td>(2,980)</td></tr>
</table>
</body></html>"""

work = Path(tempfile.mkdtemp())
(work / "statement.html").write_text(html, encoding="utf-8")
text = extract(work / "statement.html").text
print(text.replace("\t", "\\t"))
```

The output shows each tab as `\t`:

```text
CONSOLIDATED STATEMENTS OF OPERATIONS

(in thousands)

2025\t2024
Net sales\t$ 84,210\t$ 79,605
Cost of sales\t61,930\t58,114
Operating expenses\t25,695\t24,471
Loss from operations\t(3,415)\t(2,980)
```

If your text comes from a PDF, the cells are often on one line with spaces between them, or on
lines of their own. Read [A row with spaces instead of tabs](#a-row-with-spaces-instead-of-tabs)
before you use it.

## 2. Write the field

Give the field three things:

- `unit`: the unit code, here `USD`. The `$` in the table is a form of it.
- `keys`: the column headings, here the fiscal years, written as the table writes them.
- `aliases`: the row labels, in the table's words. groundgate checks a field item against them.

```python
schema = {
    "fields": {
        "operating_income": {
            "type": "integer",
            "unit": "USD",
            "keys": ["2025", "2024"],
            "aliases": ["loss from operations", "income from operations"],
        },
        "net_sales": {
            "type": "integer",
            "unit": "USD",
            "keys": ["2025", "2024"],
            "aliases": ["net sales"],
        },
    }
}
```

An alias matches without regard to case. Give each label that your documents use for the row.

## 3. Ask the extractor for each part

Tell the extractor to give the value as the fact is: a plain number with its sign and its scale.
For "(3,415)" in a table "in thousands", the value is `-3415000`. groundgate computes the value
from the parts that the extractor cites. The extractor does not state the steps.

Ask for these items, each as a quote copied from the text:

| Role | The quote | Here |
|---|---|---|
| `value` | The number as written, with its brackets. | `(3,415)` |
| `sign` | The brackets or the loss word, when the value quote does not hold them. | not needed |
| `scale` | The words that scale the number. | `(in thousands)` |
| `unit` | The unit, when it is not next to the number. | `$`, from the "Net sales" row |
| `field` | The row label. | `Loss from operations` |
| `key` | The column heading. | `2025` |

On a field with a unit, brackets that enclose the number make it negative. So the value quote
`(3,415)` gives the sign, and the candidate needs no sign item. The prompt text in
[The extractor's output](../guide.md#the-extractors-output) asks for all six roles. Use
`gg.extractor_schema(schema)` as the extractor's output format.

One candidate for 2025 looks like this:

```json
{"id": "oi-2025", "field": "operating_income", "key": "2025", "value": "-3415000", "unit": "USD",
 "evidence": [{"source": "document", "role": "value", "text": "(3,415)"},
              {"source": "document", "role": "scale", "text": "(in thousands)"},
              {"source": "document", "role": "unit", "text": "$"},
              {"source": "document", "role": "field", "text": "Loss from operations"},
              {"source": "document", "role": "key", "text": "2025"}]}
```

## 4. Admit the candidates

The helper below makes a candidate from the quotes. The examples on this page use it.

```python
def candidate(cid, name, key, value, quotes):
    evidence = [{"source": "document", "role": r, "text": q} for r, q in quotes.items()]
    return {
        "id": cid,
        "field": name,
        "key": key,
        "value": value,
        "unit": "USD",
        "evidence": evidence,
    }


def show(receipt):
    for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
        missing = f"  missing: {', '.join(d.missing)}" if d.missing else ""
        print(f"{d.candidate_id:<8} {d.outcome:<19} {' '.join(d.codes)}{missing}")


cited = {"scale": "(in thousands)", "unit": "$", "field": "Loss from operations"}
candidates = [
    candidate(
        "oi-2025",
        "operating_income",
        "2025",
        "-3415000",
        {"value": "(3,415)", **cited, "key": "2025"},
    ),
    candidate(
        "oi-2024",
        "operating_income",
        "2024",
        "-2980000",
        {"value": "(2,980)", **cited, "key": "2024"},
    ),
]
receipt = gg.admit(text, schema, candidates)
show(receipt)
```

```text
oi-2024  admitted            VALUE_DERIVED KEY_CITED
oi-2025  admitted            VALUE_DERIVED KEY_CITED
```

Both values are admitted. The two codes only inform:

- `VALUE_DERIVED`: the value is the cited number with the sign and the scale that the items give.
- `KEY_CITED`: the key item put the key at the value by the column rule. "2024" is the second
  heading of the header, and `(2,980)` is the second cell after the row label.

The decision lists each role item with its span and whether it passed:

```python
decision = next(d for d in receipt.decisions if d.candidate_id == "oi-2025")
for part in decision.parts:
    print(part.role, part.span, part.passed, repr(text[part.span[0] : part.span[1]]))
```

```text
scale (39, 53) True '(in thousands)'
unit (84, 85) True '$'
field (154, 174) True 'Loss from operations'
key (55, 59) True '2025'
```

The spans are UTF-8 byte offsets into the text. This text is ASCII, so they are also Python
indexes. A role quote resolves to the occurrence that holds the value, else to the last one
before it. So the `$` here is the one before `79,605` on the "Net sales" row. The unit check does
not read columns. It checks that a form of the unit comes before the value, and that no unit form
is next to the number.

## What goes wrong, and why

Each case below starts from the candidates of step 4 and changes one thing.

### A value with no scale item

The extractor scales the value, but it does not cite "(in thousands)":

```python
quotes = {"value": "(2,980)", "unit": "$", "field": "Loss from operations", "key": "2024"}
no_scale = candidate("oi-2024", "operating_income", "2024", "-2980000", quotes)
show(gg.admit(text, schema, [no_scale]))
```

```text
oi-2024  needs_verification  PART_MISSING KEY_CITED  missing: scale
```

The value is the cited number times 1,000. No item supports that factor, so the scale is a
missing part. groundgate never uses a scale that it found itself. A person checks the value, or
you ask the extractor for the scale item and decide again.

The opposite mistake is worse. If the extractor gives `-2980` and cites no scale, the number
matches as written:

```python
unscaled = candidate("oi-2024", "operating_income", "2024", "-2980", quotes)
show(gg.admit(text, schema, [unscaled]))
```

```text
oi-2024  admitted            VALUE_DERIVED KEY_CITED
```

Here `VALUE_DERIVED` is for the sign only: the brackets make `2,980` negative. The value is
1,000 times too small, and groundgate admits it. groundgate flags a scale word only when it
follows the number (`SCALE_WORD`). A scale in the table heading is a part that the extractor must
cite. So tell the extractor to apply the scale and to cite it. If the field has a known size, set
its `minimum` and `maximum` too.

### A row with spaces instead of tabs

A PDF or a plain-text table often has spaces between the cells. Here the tabs become three spaces:

```python
spaced = text.replace("\t", "   ")
print(spaced.splitlines()[-1])
show(gg.admit(spaced, schema, candidates))
```

```text
Loss from operations   (3,415)   (2,980)
oi-2024  needs_verification  KEY_NOT_AT_VALUE VALUE_DERIVED
oi-2025  admitted            VALUE_DERIVED KEY_CITED
```

With only spaces between the row label and its first number, groundgate cannot tell a cell from
a number that belongs to the label. So the column rule stops after the first column. The 2025
value is in the first column and is admitted. The 2024 value goes to review.

To keep the second column, extract the HTML source with `groundgate extract`, so the cells have
tabs between them. If you only have the PDF, a person checks the values after the first column.

### A footnote marker after the row label

A footnote marker after the row label is a number between the label and the cells:

```python
marked = html.replace("<td>Loss from operations</td>", "<td>Loss from operations<sup>1</sup></td>")
(work / "marked.html").write_text(marked, encoding="utf-8")
marked_text = extract(work / "marked.html").text
print(marked_text.splitlines()[-1].replace("\t", "\\t"))
show(gg.admit(marked_text, schema, candidates))
```

```text
Loss from operations^1\t(3,415)\t(2,980)
oi-2024  needs_verification  KEY_NOT_AT_VALUE VALUE_DERIVED
oi-2025  needs_verification  KEY_NOT_AT_VALUE VALUE_DERIVED
```

`extract` writes the superscript as `^1`. groundgate does not count cells across a number that
stands between the row label and the first tab. The marker could be a cell, and then the count
of columns is wrong. So the column rule stops for the whole row, and both values go to review. A
person checks them.

### A unit item when "$" is next to the number

On the "Net sales" row, the `$` is in each cell. Here the extractor also cites a unit item:

```python
sales = {"value": "79,605", "scale": "(in thousands)", "field": "Net sales", "key": "2024"}
with_unit = candidate("ns-2024", "net_sales", "2024", "79605000", {**sales, "unit": "$"})
without_unit = candidate("ns-2024b", "net_sales", "2024", "79605000", sales)
show(gg.admit(text, schema, [with_unit, without_unit]))
```

```text
ns-2024  needs_verification  UNIT_CITATION_INVALID VALUE_DERIVED KEY_CITED
ns-2024b admitted            VALUE_DERIVED KEY_CITED
```

A unit item is for a unit that is not next to the number, such as the `$` at the top of a
column. When a unit form is already next to the number, the unit item fails its check. The text
gives the unit, so the item is not necessary, and groundgate flags it. Tell the extractor to
leave out the unit item when the value quote holds the unit, as `$ 79,605` does here.

## Checklist

- Extract HTML tables with `groundgate extract`, so the cells have tabs between them.
- Give the field its `unit`, its `keys` (the column headings) and its `aliases` (the row labels).
- Ask for the value, scale, field and key items on every table value.
- Ask for a unit item only when the unit is not next to the number.
- Ask for a sign item only when the value quote does not hold the brackets or the loss word.

If a value still goes to review, the codes and `missing` say which part failed. The page
[Review flagged facts and keep receipts](review.md) shows what a person checks for each code.
