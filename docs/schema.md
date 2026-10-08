# How to write a schema

The schema tells groundgate what each field means: its type, its unit, its bounds, and how the
text may state it. groundgate checks every candidate value against its field. A good schema
admits a right value and sends a doubtful one to a person. This page shows how to write one.
[SPEC.md](../SPEC.md) §2.3 and §4 are the normative rules, and the
[guide](guide.md#schema) has the short reference table.

A schema is an object with `fields` and, optionally, `units`. This is a minimal one, with one
candidate that quotes its evidence:

```python
import groundgate as gg

text = "The late filing penalty is $485 for each return."
schema = {"fields": {"late_penalty": {"type": "integer", "unit": "USD"}}}
candidates = [
    {
        "id": "c1",
        "field": "late_penalty",
        "value": "485",
        "unit": "USD",
        "evidence": [{"text": "$485"}],
    }
]
receipt = gg.admit(text, schema, candidates)
print(receipt.decisions[0].outcome)
print(gg.jcs(gg.Schema.from_dict(schema).to_dict()))
```

```text
admitted
{"fields":{"late_penalty":{"aliases":null,"comparator":"eq","keys":null,"maximum":null,"minimum":null,"multiple":false,"required":false,"type":"integer","unit":"USD"}},"units":{}}
```

`gg.Schema.from_dict` adds the defaults, and `gg.jcs` writes the result as canonical JSON. The
receipt's `schema_sha256` is the digest of that object. So a schema that writes a default and a
schema that omits it have the same digest.

The examples below share two helpers. `cite` makes a candidate whose value item is a quote, and
`show` prints one line for each decision:

```python
def cite(cid, field, value, quote, unit=None, **extra):
    """A candidate whose value item is a quote. groundgate finds the quote in the text."""
    candidate = {"id": cid, "field": field, "value": value, "evidence": [{"text": quote}]}
    if unit is not None:
        candidate["unit"] = unit
    return {**candidate, **extra}


def show(receipt):
    """Print one line for each decision, in the order of the candidate ids."""
    for d in sorted(receipt.decisions, key=lambda d: d.candidate_id):
        value = "-" if d.value is None else d.value
        notes = [f"key={d.key}"] if d.key else []
        notes += d.codes
        if d.missing:
            notes.append("missing=" + ",".join(d.missing))
        print(f"{d.candidate_id:<4}{d.outcome:<20}{value:<14}{' '.join(notes)}".rstrip())
```

## Fields

Each field has a `type`. The default is `number`.

| `type` | Accepts | Rejects |
|---|---|---|
| `number` | One decimal number: `"485"`, `"0.5"`, `"-12"`, `"7,000"`, or a JSON integer. | A JSON float such as `0.5`, a unit in the value (`"$485"`, `"485 USD"`), an exponent (`"1e3"`), a fraction (`"1/2"`). |
| `integer` | The same, with an integral value: `"485"`, `"485.0"`, `485`. | `"485.5"`, and everything that `number` rejects. |
| `string` | A non-blank string. | A JSON integer, and a string that is blank after whitespace normalisation. |

groundgate reads a candidate value with the rules that it uses for numbers in the text
([SPEC §4.1](../SPEC.md)). The value must be one number token and nothing else. Commas in groups
of three, or in the Indian grouping, are allowed. The decision then carries the canonical value:
no grouping, no trailing zeros after the decimal point. So `"7,000"`, `7000` and `"7000.00"` are
all `7000`.

Send a decimal as a string. A JSON number with a fraction is a float, and a float cannot hold
every decimal exactly. So step 1 rejects it with `CANDIDATE_INVALID`.

Send a large integer as a string too. A JSON integer must be in [-(2^53-1), 2^53-1]
([SPEC §6](../SPEC.md)). An integer outside this range anywhere in a candidate makes the packet
invalid. `PacketError` names the path of the value, before any digest is computed. The same check
covers the document id, references, judgments and the policy. A string such as `"12500000000000000"`
has no limit.

`minimum` and `maximum` are bounds, each a decimal string or a JSON integer. Both are inclusive.
A value outside them is rejected `RANGE_INVALID`, before groundgate reads the evidence. Use bounds
for values that cannot be right, such as a negative age or a rate above 100 percent.

```python
text = "The late filing penalty is $485 for each return. The interest rate is 8 percent."
schema = {
    "fields": {
        "late_penalty": {"type": "integer", "unit": "USD", "minimum": 0},
        "interest_rate": {"type": "number", "unit": "%", "minimum": "0", "maximum": "100"},
    }
}
candidates = [
    cite("p1", "late_penalty", "485", "$485", "USD"),
    cite("p2", "late_penalty", 485, "$485", "USD"),
    cite("p3", "late_penalty", "485.00", "$485", "USD"),
    cite("p4", "late_penalty", "$485", "$485", "USD"),
    cite("p5", "late_penalty", "485.5", "$485", "USD"),
    cite("r1", "interest_rate", "8", "8 percent", "%"),
    cite("r2", "interest_rate", 8.0, "8 percent", "%"),
    cite("r3", "interest_rate", "800", "8 percent", "%"),
]
show(gg.admit(text, schema, candidates))
```

```text
p1  admitted            485
p2  admitted            485
p3  admitted            485
p4  rejected            -             TYPE_INVALID
p5  rejected            485.5         TYPE_INVALID
r1  admitted            8
r2  rejected            -             CANDIDATE_INVALID
r3  rejected            800           RANGE_INVALID
```

`p1`, `p2` and `p3` have the same canonical value, so they do not conflict. `p4` holds a unit,
and `p5` is not integral. `r3` is above the maximum, so groundgate does not search the text
for it.

## Units

`unit` is the unit code that the value must carry. The candidate must send the same code in its
`unit`, or it is rejected `UNIT_INVALID`. Then groundgate looks for a form of the unit next to
the number in the text.

The built-in table ([SPEC §4.3](../SPEC.md)):

| Code | Prefix | Suffix |
|---|---|---|
| `USD` | `$`, `US$` | `USD`, `dollars` |
| `EUR` | `€` | `EUR`, `euros` |
| `GBP` | `£` | `GBP` |
| `INR` | `₹`, `Rs.`, `Rs` | `INR`, `rupees` |
| `%` | | `%`, `percent` |
| `mg`, `mcg`, `g`, `kg`, `mL`, `L` | | the code itself |
| `hours`, `days`, `weeks`, `months`, `years`, `minutes` | | the code, its singular, and `-<singular>` |

A unit is at a number when one of these is true:

- A prefix ends at the start of the number. Whitespace between them is allowed, so `$ 485` is
  USD.
- The first suffix after the number is one of the unit's suffixes. It must start within
  `unit_window` code points (24 by default) and lie wholly inside the number's sentence.

Only the first suffix of any unit counts. In "10 mcg (maximum 500 mg)", the 10 is mcg and never
mg. A number without a unit of its own takes the next one, so `mg` is at the 25 in "25 or 50 mg".
A suffix that starts with a letter must not follow another letter in the text after the number.
A suffix that ends with a letter must not have a letter or digit directly after it. So `g` is not
at the 5 in "5 grams", but `mg` is at the 500 in "500mg".

**Custom units.** Add a code under `units` with its `prefix` and `suffix` lists. A code that is
also in the built-in table replaces the built-in forms. Each list holds non-empty strings, and an
absent list is empty.

```json
{"fields": {"cuff_pressure": {"unit": "mmHg"}},
 "units": {"mmHg": {"suffix": ["mmHg", "mm Hg"]}}}
```

Do not write a suffix that holds a dot and a space, such as `in. Hg`. The dot and the space end
the sentence, and the whole suffix must lie inside the number's sentence. So that suffix never
matches. Write the forms without the dot, or accept that the value goes to review.

**Per-units.** A dose such as "10 mg/kg" is not a dose in mg. When `/` or `per` follows the suffix,
with a body-size or volume unit after it (`kg`, `lb`, `m2`, `mL`, `L` and their long forms), the
suffix is a per-unit and does not count. So `mg` is not at "10 mg/kg", "75 mg/m2" or
"250 mg/5 mL". A time keeps the unit: "200 mg/day" is mg. Give a weight-based dose its own code,
with the per-unit as its suffix.

**A unit with no forms.** A code with no prefixes and no suffixes is at every number. That holds
for a code that is not in the table, such as `IU`, and for a code that the schema gives two empty
lists. The unit check is then vacuous. If you want the check, give the code its forms.

Two outcomes tell you that a unit is not where the field expects it:

- `UNIT_NOT_IN_EVIDENCE` rejects the value. Another unit is next to the number, such as mcg for an
  mg field, or a per-unit.
- `PART_MISSING` with `missing=unit` sends the value to review. No unit form is next to the
  number: the text writes a form that is not in the table, or the suffix is too far away or in the
  next sentence. A `unit` item can supply the unit (see [Field aliases](#field-aliases)).

```python
text = (
    "Give 10 mcg (maximum 500 mg) each day. "
    "For children, give 15 mg/kg once daily. "
    "The cuff read 120 mm Hg. The gauge read 30 in. Hg at noon. "
    "The tablet holds 400 IU of vitamin D. The daily limit is 4,000 for adults."
)
schema = {
    "fields": {
        "dose_mcg": {"unit": "mcg"},
        "dose_mg": {"unit": "mg"},
        "dose_per_kg": {"unit": "mg/kg"},
        "cuff_pressure": {"unit": "mmHg"},
        "gauge_pressure": {"unit": "inHg"},
        "vitamin_d": {"unit": "IU"},
        "daily_limit": {"unit": "mg"},
    },
    "units": {
        "mg/kg": {"suffix": ["mg/kg"]},
        "mmHg": {"suffix": ["mmHg", "mm Hg"]},
        "inHg": {"suffix": ["inHg", "in. Hg"]},
    },
}
candidates = [
    cite("u1", "dose_mcg", "10", "10 mcg", "mcg"),
    cite("u2", "dose_mg", "10", "10 mcg", "mg"),
    cite("u3", "dose_per_kg", "15", "15 mg/kg", "mg/kg"),
    cite("u4", "dose_mg", "15", "15 mg/kg", "mg"),
    cite("u5", "cuff_pressure", "120", "120 mm Hg", "mmHg"),
    cite("u6", "gauge_pressure", "30", "30 in. Hg", "inHg"),
    cite("u7", "vitamin_d", "400", "400 IU", "IU"),
    cite("u8", "daily_limit", "4000", "4,000", "mg"),
]
show(gg.admit(text, schema, candidates))
```

```text
u1  admitted            10
u2  rejected            10            UNIT_NOT_IN_EVIDENCE
u3  admitted            15
u4  rejected            15            UNIT_NOT_IN_EVIDENCE
u5  admitted            120
u6  needs_verification  30            PART_MISSING missing=unit
u7  admitted            400
u8  needs_verification  4000          PART_MISSING missing=unit
```

`u7` is admitted only because `IU` has no forms. The text could say "400 tablets" and the check
would still pass.

## Comparators

`comparator` says what the field means relative to the number in the text. The default is `eq`.

| Comparator | The field holds | Qualifiers that imply it, for example |
|---|---|---|
| `eq` | the number itself | none |
| `gt` | a bound that the quantity exceeds | more than, above, over, exceeds |
| `ge` | a minimum | at least, minimum of, or more, or older |
| `lt` | a bound that the quantity stays below | less than, below, under |
| `le` | a maximum | up to, maximum of, at most, no more than, or less |
| `approx` | an estimate | about, approximately, around, nearly |
| `range` | one end of a range | between, or a second number after `to`, `through` or `-` |

groundgate searches for a qualifier in the value's sentence, up to 40 code points before and after
the value, and not past the next number. If a qualifier applies and its comparator differs from
the field's, the fact is flagged `QUALIFIED_VALUE`. A negation inverts a qualifier, so "may not
exceed $19,000" is `le`. SPEC §4.2 has the full lists.

Set the comparator when the field is a limit. A field for a maximum deduction is `le`, so "up to
$2,500" admits. The same text on an `eq` field goes to review. That is right: on an `eq` field,
"up to $2,500" does not state the value. A value with no qualifier admits on every comparator.

```python
text = (
    "You can deduct up to $2,500 of interest. "
    "Patients must be at least 18 years old. "
    "The study enrolled adults between 18 and 65 years. "
    "The filing fee is $50."
)
schema = {
    "fields": {
        "max_deduction": {"type": "integer", "unit": "USD", "comparator": "le"},
        "deduction_eq": {"type": "integer", "unit": "USD"},
        "min_age": {"type": "integer", "unit": "years", "comparator": "ge"},
        "enrolled_age_low": {"type": "integer", "unit": "years", "comparator": "range"},
        "enrolled_age_high": {"type": "integer", "unit": "years", "comparator": "range"},
        "max_filing_fee": {"type": "integer", "unit": "USD", "comparator": "le"},
    }
}
candidates = [
    cite("q1", "max_deduction", "2500", "$2,500", "USD"),
    cite("q2", "deduction_eq", "2500", "$2,500", "USD"),
    cite("q3", "min_age", "18", "18 years", "years"),
    cite("q4", "enrolled_age_low", "18", "18 and 65", "years"),
    cite("q5", "enrolled_age_high", "65", "65 years", "years"),
    cite("q6", "max_filing_fee", "50", "$50", "USD"),
]
show(gg.admit(text, schema, candidates))
```

```text
q1  admitted            2500
q2  needs_verification  2500          QUALIFIED_VALUE
q3  admitted            18
q4  admitted            18
q5  admitted            65
q6  admitted            50
```

## Lists and conflicts

A field holds one value by default. If two candidates for it pass the checks with different
canonical values, both are flagged `CONFLICTING_CANDIDATES`. groundgate never picks one. Send
the candidates of several extractors to one `admit` call, and a disagreement becomes a flag.

A rejected candidate does not conflict, and two candidates with the same value do not conflict.
If the field holds a list, such as the strengths of a tablet, set `multiple` to `true`. Then
different values do not conflict.

```python
text = "Tablets come in 5 mg, 10 mg and 20 mg. The usual dose is 10 mg once daily."
schema = {
    "fields": {
        "strengths": {"unit": "mg", "multiple": True},
        "usual_dose": {"unit": "mg"},
    }
}
candidates = [
    cite("s1", "strengths", "5", "5 mg", "mg"),
    cite("s2", "strengths", "10", "10 mg", "mg"),
    cite("s3", "strengths", "20", "20 mg", "mg"),
    cite("d1", "usual_dose", "10", "dose is 10 mg", "mg"),
    cite("d2", "usual_dose", "20", "20 mg", "mg"),
    cite("d3", "usual_dose", "40", "10 mg", "mg"),
]
show(gg.admit(text, schema, candidates))
```

```text
d1  needs_verification  10            CONFLICTING_CANDIDATES
d2  needs_verification  20            CONFLICTING_CANDIDATES
d3  rejected            40            VALUE_NOT_IN_EVIDENCE
s1  admitted            5
s2  admitted            10
s3  admitted            20
```

`d1` and `d2` disagree, so a person picks. `d3` is rejected, so it does not add a conflict.

## Required fields and coverage

Set `required` to `true` for a field that every document must have. If no candidate of a required
field is admitted or flagged, the receipt's `coverage` lists the field with
`REQUIRED_FIELD_MISSING`. This is a finding about the document, not a decision. It is per field:
on a keyed field, one key with a value is enough.

```python
text = "The annual fee is $95."
schema = {
    "fields": {
        "annual_fee": {"type": "integer", "unit": "USD", "required": True},
        "late_fee": {"type": "integer", "unit": "USD", "required": True},
        "foreign_fee": {"type": "number", "unit": "%", "required": True},
        "notes": {"type": "string"},
    }
}
candidates = [
    cite("f1", "annual_fee", "95", "$95", "USD"),
    cite("f2", "late_fee", "40", "$95", "USD"),
]
receipt = gg.admit(text, schema, candidates)
show(receipt)
print(receipt.coverage)
```

```text
f1  admitted            95
f2  rejected            40            VALUE_NOT_IN_EVIDENCE
(('foreign_fee', 'REQUIRED_FIELD_MISSING'), ('late_fee', 'REQUIRED_FIELD_MISSING'))
```

`late_fee` has a candidate, but it is rejected, so the field is still missing. `notes` is not
required, so it is not listed.

## Keyed fields

Some fields have one value for each condition: a starting dose for each indication, a limit for
each tax year. Give such a field `keys`, in the document's words. Each candidate then names its
key in `key`. A candidate with no `key`, or with a key that is not exactly one of the list, is
rejected `KEY_INVALID`. Case counts in this comparison.

```json
{"fields": {"starting_dose": {"unit": "mg", "keys": ["hypertension", "heart failure"]}}}
```

A **key mention** is an occurrence of a key in the text. It matches without regard to case, a
space in the key matches any whitespace run in the text, and no letter or digit may touch it.
groundgate then reads which keys the text puts at the value:

1. The keys mentioned in the value's sentence.
2. If the sentence mentions none, the key of the nearest mention before the value. A heading such
   as "2.2 Heart Failure" reaches every value under it, until the text mentions another key.
3. A label line stops that reach. A label line has 12 words or less, no `.` or `;` before a space
   or a line end, and a blank line after it. A blank line or the start of the text comes before
   it. "Dosing notes" and "Adults" are label lines. A value under one has no key.
4. In a table sentence, only the value's own line counts. A table sentence holds 3 or more line
   breaks and mentions 2 or more keys of the field.

If the candidate's key is not one of these keys, the fact is flagged `KEY_NOT_AT_VALUE`. If the
candidate also has no key item, the decision lists `key` in `missing`. Two candidates conflict
only when they share a key. The receipt echoes the key.

```python
text = (
    "2.1 Hypertension\n\n"
    "The starting dose is 10 mg once daily.\n\n"
    "2.2 Heart Failure\n\n"
    "Dosing notes\n\n"
    "The starting dose is 5 mg once daily.\n\n"
    "For angina, give 15 mg once daily."
)
schema = {
    "fields": {"starting_dose": {"unit": "mg", "keys": ["hypertension", "heart failure", "angina"]}}
}
candidates = [
    cite("k1", "starting_dose", "10", "10 mg", "mg", key="hypertension"),
    cite("k2", "starting_dose", "5", "5 mg", "mg", key="heart failure"),
    cite("k3", "starting_dose", "15", "15 mg", "mg", key="angina"),
    cite("k4", "starting_dose", "15", "15 mg", "mg", key="hypertension"),
    cite("k5", "starting_dose", "15", "15 mg", "mg", key="Angina"),
    cite("k6", "starting_dose", "15", "15 mg", "mg"),
]
show(gg.admit(text, schema, candidates))
```

```text
k1  needs_verification  10            key=hypertension CONFLICTING_CANDIDATES
k2  needs_verification  5             key=heart failure KEY_NOT_AT_VALUE missing=key
k3  admitted            15            key=angina
k4  needs_verification  15            key=hypertension KEY_NOT_AT_VALUE CONFLICTING_CANDIDATES missing=key
k5  rejected            15            key=Angina KEY_INVALID
k6  rejected            15            KEY_INVALID
```

`k2` has the right key, but the label line "Dosing notes" stops the heading, so a person checks
it. `k4` names a key that the text does not put at 15 mg. It also conflicts with `k1`, because
both passed with the key `hypertension`.

**Tables.** A table flattened to one cell on each line puts no key at its values. The extractor
can cite the key with a `key` item, such as the column header "2024". A key item puts its key at
the value only by the **column rule**: the key is the n-th key of its header, and the value is the
n-th cell after the row label. The row label is the candidate's `field` item, so the field needs
`aliases`. [Tables](howto/tables.md) shows the rule at work, and the
[10-K schema](#a-10-k-income-statement) below uses it.

## Field aliases

`aliases` are the field's names in the document's words, such as "loss from operations" for an
operating income field. They follow the same rules as `keys`. groundgate uses them for one
thing: to check a `field` item. A field item is the extractor's quote of the words that name the
value, such as a table row label.

A field item passes when it holds a mention of one of the aliases and ends before the value. It
must also be at the value: on its row with no letter between it and the number, or in the value's
sentence with no number between them. Otherwise it fails with `FIELD_CITATION_INVALID`. A field
with no `aliases` does not check its field item. That item adds no flag, but it does not pass.

Two other checks need a passing field item:

- The column rule for keys (above).
- A `unit` item. A unit item supports a unit that is not next to the number, such as the `$` at
  the top of a column. It passes only when it comes before the value and the field item passes.
  It does not check that the unit applies to the value's row. A `$` on an earlier row passes too.

```python
text = "Segment results (all amounts in $)\n\nNet sales\t4,210\nCost of sales\t2,950"


def segment_candidate(cid, field_quote):
    return {
        "id": cid,
        "field": "net_sales",
        "value": "4210",
        "unit": "USD",
        "evidence": [
            {"text": "4,210"},
            {"role": "unit", "text": "$"},
            {"role": "field", "text": field_quote},
        ],
    }


no_aliases = {"fields": {"net_sales": {"type": "integer", "unit": "USD"}}}
with_aliases = {
    "fields": {"net_sales": {"type": "integer", "unit": "USD", "aliases": ["net sales"]}}
}
show(gg.admit(text, no_aliases, [segment_candidate("a1", "Net sales")]))
show(gg.admit(text, with_aliases, [segment_candidate("a2", "Net sales")]))
show(gg.admit(text, with_aliases, [segment_candidate("a3", "Cost of sales")]))
show(gg.admit(text, with_aliases, [cite("a4", "net_sales", "4210", "4,210", "USD")]))
```

```text
a1  needs_verification  4210          UNIT_CITATION_INVALID
a2  admitted            4210
a3  needs_verification  4210          UNIT_CITATION_INVALID FIELD_CITATION_INVALID
a4  needs_verification  4210          PART_MISSING missing=unit
```

`a1` fails its unit item, because the field has no aliases. `a2` cites the row and the unit, and
is admitted. `a3` cites another row. `a4` cites no unit at all, so the unit is missing.

## String fields

A `string` field holds text, such as a dosage form or a filing status. Its value matches when it
is a substring of the evidence text. Before the comparison, groundgate collapses every whitespace
run to one space on both sides. Case counts, so "oral tablets" does not match "Oral Tablets".

A string field reads no qualifiers and no scale words. "up to 30 days" on a string field is the
text itself, not a limit. Step 4 rejects a JSON integer, and a string that is blank, with
`TYPE_INVALID`.

```python
text = "Dosage form: Oral   Tablets. Store opened bottles for up to 30 days."
schema = {"fields": {"dosage_form": {"type": "string"}, "storage": {"type": "string"}}}
candidates = [
    cite("t1", "dosage_form", "Oral Tablets", "Oral   Tablets"),
    cite("t2", "dosage_form", "oral tablets", "Oral   Tablets"),
    cite("t3", "storage", "up to 30 days", "up to 30 days"),
    cite("t4", "storage", 30, "30 days"),
    cite("t5", "storage", "  ", "30 days"),
]
show(gg.admit(text, schema, candidates))
```

```text
t1  admitted            Oral Tablets
t2  rejected            oral tablets  VALUE_NOT_IN_EVIDENCE
t3  admitted            up to 30 days
t4  rejected            -             TYPE_INVALID
t5  rejected            -             TYPE_INVALID
```

## When the schema is invalid

groundgate refuses an invalid schema. `admit` raises `gg.PacketError` and writes no receipt. The
schema is invalid when:

- it is not an object with a `fields` object, or it has keys other than `fields` and `units`;
- a field is not an object, or it has keys other than the nine in this page;
- `type` is not `number`, `integer` or `string`, or `comparator` is not one of the seven;
- `unit` is not a string or null;
- `minimum` or `maximum` is not a decimal string or an integer (a float or a boolean is invalid);
- `required` or `multiple` is not a boolean;
- `keys` or `aliases` is not null or a non-empty list of strings, or two entries are equal after
  whitespace normalisation and lower-casing, or an entry is blank;
- `units` is not an object, a unit has keys other than `prefix` and `suffix`, or a surface is not
  a non-empty string.

To check a schema before the first document, call `gg.Schema.from_dict`:

```python
bad_schemas = [
    {"fields": {"limit": {"type": "float"}}},
    {"fields": {"limit": {"comparator": "<="}}},
    {"fields": {"limit": {"maximum": 2500.5}}},
    {"fields": {"limit": {"min": "0"}}},
    {"fields": {"limit": {"required": "yes"}}},
    {"fields": {"dose": {"keys": ["Heart failure", "heart  failure"]}}},
    {"fields": {"pressure": {"unit": "inHg"}}, "units": {"inHg": {"suffix": "inHg"}}},
]
for bad in bad_schemas:
    try:
        gg.Schema.from_dict(bad)
    except gg.PacketError as error:
        print(error)
```

```text
field 'limit' has unknown type 'float'
field 'limit' has unknown comparator '<='
field bound limit.maximum must be a decimal string or integer
field 'limit' has unknown keys ['min']
field 'limit' required must be a boolean
field 'dose' keys must be distinct, non-blank text
unit 'inHg' surfaces must be non-empty strings
```

## Three schemas

### An IRS publication

A tax publication states a dollar limit for each year and a phase-out range. The limit is a
maximum, so its comparator is `le`, and the year is its key. The phase-out has two ends, and each
end is a `range` field. The text below is made up.

```python
text = (
    "Home Office Equipment Credit\n\n"
    "For 2025, you can claim up to $1,200 of qualified costs. "
    "For 2026, you can claim up to $1,250.\n\n"
    "The credit phases out for modified AGI between $90,000 and $110,000."
)
schema = {
    "fields": {
        "credit_limit": {
            "type": "integer",
            "unit": "USD",
            "comparator": "le",
            "keys": ["2025", "2026"],
            "required": True,
        },
        "phaseout_start": {"type": "integer", "unit": "USD", "comparator": "range"},
        "phaseout_end": {"type": "integer", "unit": "USD", "comparator": "range"},
    }
}
candidates = [
    cite("i1", "credit_limit", "1200", "$1,200", "USD", key="2025"),
    cite("i2", "credit_limit", "1250", "$1,250", "USD", key="2026"),
    cite("i3", "credit_limit", "1200", "$1,200", "USD", key="2026"),
    cite("i4", "phaseout_start", "90000", "$90,000", "USD"),
    cite("i5", "phaseout_end", "110000", "$110,000", "USD"),
]
show(gg.admit(text, schema, candidates))
```

```text
i1  admitted            1200          key=2025
i2  needs_verification  1250          key=2026 CONFLICTING_CANDIDATES
i3  needs_verification  1200          key=2026 KEY_NOT_AT_VALUE CONFLICTING_CANDIDATES missing=key
i4  admitted            90000
i5  admitted            110000
```

`i3` puts the 2025 limit under 2026. The key flag sends it to review, and it conflicts with `i2`.

### A drug label

A drug label gives a starting dose for each indication, a dose for each kilogram of body weight,
and a minimum age. The dose per kilogram has its own unit code. The minimum age is `ge`, because
the label says "or older". The text below is made up.

```python
text = (
    "2.1 Hypertension\n\n"
    "The recommended starting dose is 10 mg once daily.\n\n"
    "2.2 Heart Failure\n\n"
    "The recommended starting dose is 5 mg once daily.\n\n"
    "2.3 Pediatric Use\n\n"
    "Use in patients 6 years or older. Give 0.1 mg/kg once daily."
)
schema = {
    "fields": {
        "starting_dose": {"unit": "mg", "keys": ["hypertension", "heart failure"]},
        "pediatric_dose": {"unit": "mg/kg", "minimum": "0"},
        "pediatric_min_age": {
            "type": "integer",
            "unit": "years",
            "comparator": "ge",
            "minimum": 0,
        },
    },
    "units": {"mg/kg": {"suffix": ["mg/kg"]}},
}
candidates = [
    cite("l1", "starting_dose", "10", "10 mg", "mg", key="hypertension"),
    cite("l2", "starting_dose", "5", "5 mg", "mg", key="heart failure"),
    cite("l3", "starting_dose", "5", "5 mg", "mg", key="hypertension"),
    cite("l4", "pediatric_dose", "0.1", "0.1 mg/kg", "mg/kg"),
    cite("l5", "starting_dose", "0.1", "0.1 mg/kg", "mg", key="heart failure"),
    cite("l6", "pediatric_min_age", "6", "6 years", "years"),
]
show(gg.admit(text, schema, candidates))
```

```text
l1  needs_verification  10            key=hypertension CONFLICTING_CANDIDATES
l2  admitted            5             key=heart failure
l3  needs_verification  5             key=hypertension KEY_NOT_AT_VALUE CONFLICTING_CANDIDATES missing=key
l4  admitted            0.1
l5  rejected            0.1           key=heart failure UNIT_NOT_IN_EVIDENCE
l6  admitted            6
```

`l3` reads the heart failure dose as the hypertension dose. It gets the key flag, and it
conflicts with `l1`, so a person sees both. `l5` reads the dose for each kilogram as a dose in mg.
The per-unit after 0.1 rejects it.

### A 10-K income statement

An income statement is a table. Operating income has one value for each fiscal year, so the year
is its key. The table writes the numbers in thousands, writes a loss in brackets, and puts the
`$` only in the first row. The aliases name the row in the document's words. The text below is
made up, with a tab between cells, as `groundgate extract` writes an HTML table.

```python
text = (
    "CONSOLIDATED STATEMENTS OF OPERATIONS\n"
    "(in thousands)\n\n"
    "\t2025\t2024\n"
    "Revenue\t$ 512,400\t$ 476,150\n"
    "Cost of revenue\t301,220\t288,930\n"
    "Operating loss\t(14,380)\t(9,615)\n"
)
schema = {
    "fields": {
        "operating_income": {
            "type": "integer",
            "unit": "USD",
            "keys": ["2025", "2024"],
            "aliases": ["operating income", "operating loss", "income from operations"],
            "required": True,
        }
    }
}


def table_candidate(cid, value, quote, key, with_roles=True):
    evidence = [{"text": quote}]
    if with_roles:
        evidence += [
            {"role": "scale", "text": "(in thousands"},
            {"role": "unit", "text": "$"},
            {"role": "field", "text": "Operating loss"},
            {"role": "key", "text": key},
        ]
    return {
        "id": cid,
        "field": "operating_income",
        "value": value,
        "unit": "USD",
        "key": key,
        "evidence": evidence,
    }


candidates = [
    table_candidate("x1", "-14380000", "(14,380)", "2025"),
    table_candidate("x2", "-9615000", "(9,615)", "2024"),
]
show(gg.admit(text, schema, candidates))
print()
weak = [
    table_candidate("x3", "-9615000", "(9,615)", "2024", with_roles=False),
    table_candidate("x4", "-9615000", "(9,615)", "2025"),
]
show(gg.admit(text, schema, weak))
```

```text
x1  admitted            -14380000     key=2025 VALUE_DERIVED KEY_CITED
x2  admitted            -9615000      key=2024 VALUE_DERIVED KEY_CITED

x3  needs_verification  -9615000      key=2024 PART_MISSING KEY_NOT_AT_VALUE missing=scale,unit,key
x4  needs_verification  -9615000      key=2025 KEY_NOT_AT_VALUE VALUE_DERIVED
```

`x1` and `x2` cite every part, so groundgate derives the value: the brackets make it negative,
the scale item multiplies it by 1,000, and the key item puts the column's year at it. The second
call holds two weak candidates. I send them in their own call, so that they do not conflict with
`x1` and `x2`. `x3` cites only the number, so the scale, the unit and the key are missing. `x4`
cites the 2025 header for a number in the 2024 column, so the column rule does not put 2025 at
it.
