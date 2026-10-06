# Aviation set: the field question on a second document kind

The field question (#67, `bench/judges/fields`) asks whether a typed-decision model can find a
number that spec 0.3 admits as the wrong field. Every answer so far is on FDA labels. This set asks
it on NTSB aviation reports: each number in hours or feet is labeled by a person with the set-2
fields that the report states as that number.

`aviation.py` walks the reports with the set-2 NTSB rule (`bench/pick.py`). The walk looks only at
the first words and the page count of a report, and prints no text. The label tool shows the
report text with its line breaks and links each number to its page of the PDF. It never shows
what spec 0.3 or a model reads.

```bash
uv run python bench/aviation/aviation.py pick --count   # how many reports the walk finds
uv run python bench/aviation/aviation.py pick           # write sources.json, selection-log.json
uv run python bench/fetch.py --set bench/aviation       # download, verify, write docs/
uv run python bench/aviation/aviation.py items          # write items.json from docs/
uv run python bench/aviation/aviation.py web            # label at http://127.0.0.1:8772
```

## Reports

NTSB report ids from 192732 up, the first after set 2, with the set-2 rule: the PDF starts with
"Aviation Investigation Final Report" and has 8 pages or fewer. A 404 means there is no report.
The walk takes reports in id order until their numbers in hours or feet reach 150. The text is the
whole report, as in set 2.

One rule is new. Set 2 stops the walk on any download failure but a 404, after about two minutes
of retries, so a slow server never makes the walk skip a report. Report 192732 gives HTTP 500 with
an error body every time. A 500 that stays after all the retries now counts as no report.

## Numbers and fields

A number is a number token followed by a set-2 unit suffix of hours or feet (`hours`, `hour`,
`Hrs`, `hrs`, `ft`, `feet`, `-ft`, `-foot`). `items.json` holds every such number of each report,
with its PDF page. The fields are the six set-2 NTSB fields in hours or feet, with the set-2
schemas and descriptions (`FIELDS` in `aviation.py`): `pilot_total_hours`,
`pilot_make_model_hours`, `pilot_last_90_days_hours`, `airframe_total_hours`,
`airport_elevation` and `runway_length`. Four fields share hours and two share feet, so spec 0.3
admits many numbers as more than one field.

## A label

The fields that the report states as the marked number: one, several, or none. `?` is not sure,
and it is left out of the gold.
