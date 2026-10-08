# groundgate

groundgate decides if an extracted value is supported, and it writes a receipt for each decision.
It is one step in an app's pipeline. The app owns the extractor, the judge and any feedback loop.

## Pipeline

**Extractor**:
The model or tool that the app puts in front of groundgate to give candidates.
_Avoid_: proposer, LLM

**Candidate**:
One extracted value for one field, with the evidence that the extractor gives for it.
_Avoid_: fact, extraction, claim

**Judge**:
An optional model or person whose answers the app records and gives to groundgate as recorded
judgments. groundgate never calls a judge.
_Avoid_: verifier, checker

## Evidence

**Evidence**:
The list of evidence items that a candidate gives to support its value.
_Avoid_: grounds, citation, proof

**Evidence item**:
One piece of support for a candidate's value. It has a source kind.
_Avoid_: ground, span (a span is only one form of an evidence item)

**Source kind**:
Where an evidence item comes from: the document, a reference, an external source, or the
extractor's own knowledge.
_Avoid_: origin, provenance

**Reference**:
A source text other than the document that the app, not the extractor, puts in the packet. The
text can be only the part that matters.
_Avoid_: second document, attachment

**External source**:
A source that the extractor cites with a URL, a retrieved date and a quoted passage, with no text
from the app.
_Avoid_: web evidence, citation

**Role**:
The part of a value that a document or reference item supports: the value as written, its sign,
its scale, its unit, its key or its field.
_Avoid_: type, kind (source kind is a different term)

**Field alias**:
A word or phrase in the document's words that names a field, such as "loss from operations" for
operating income.
_Avoid_: label (a label is a person's mark on a bench item), synonym

**Quote**:
The text that an evidence item cites, given without a position. groundgate finds its position.
_Avoid_: snippet, excerpt

**Document source**:
The URL that the app gives for the document. An app can trust external sources on the same host
with the `document-domain` allow-list entry.
_Avoid_: origin, document URL

**Trust level**:
How far groundgate can check an evidence item: checked (document or reference), quoted (external
source) or stated (the extractor's knowledge).
_Avoid_: confidence, strength

**Weak evidence**:
Evidence that supports the value but has a missing part (`PART_MISSING`) or a role item that
fails its check (a field item on a field with no aliases is not checked), or outside evidence that the policy sends to review (`EVIDENCE_QUOTED`,
`EVIDENCE_STATED`). It gives the outcome `needs_verification`.

**No evidence**:
A candidate with no value item and no outside item (`NO_EVIDENCE`), or evidence that does not
hold the value (`QUOTE_NOT_FOUND`, `VALUE_NOT_IN_EVIDENCE`, `UNIT_NOT_IN_EVIDENCE`). It gives the
outcome `rejected`.
_Avoid_: unsupported, hallucinated

## Decisions

**Outcome**:
The result of one decision: `admitted`, `needs_verification` or `rejected`.
_Avoid_: verdict, status

**Feedback**:
What groundgate returns for each candidate (the outcome, the codes, the parts and the missing
parts) and for each required field with no admitted or flagged candidate (a coverage finding). The
app decides whether to send it back to the extractor.
_Avoid_: critique, review notes

**Feedback message**:
The text for the extractor, built from the feedback of one candidate, that says what to change:
a part to cite, a quote to copy exactly, or the value to send, such as the scaled number. It is
worth sending only when a new answer can change the decision.
_Avoid_: retry prompt, critique

**Feedback loop**:
The app builds feedback messages, sends them to the extractor, and gives the new candidates to
groundgate. groundgate never calls the extractor, so the app runs the loop.
_Avoid_: retry loop, self-correction
