# Judge probe

`probe.json` holds 32 short sentences that I wrote to try System 1 models on groundgate's review
questions (#66, #67). Each item has its expected answer, written by hand. None of the sentences
come from the v0.1 set or set 2.

| Kind | Items | Question |
|---|---|---|
| `comparator` | 18 (4 in German) | Which relation does the text state for the value? |
| `key` | 4 | Which condition does the value belong to? |
| `field` | 6 | Does the text state this field as this value? |
| `paraphrase` | 4 | Do the quote and the span state the same fact? |

`questions` gives the exact wording that I used for each kind: the state, the instructions and
the options. Use the same wording to compare a new model with the results on #67.

This is a quick check, not a measurement. The sentences are short and clean, unlike real
documents. I have also seen how several models answer them, so they must never choose a
threshold or appear in a test part. The measurement in #67 uses a new gold set for that.
