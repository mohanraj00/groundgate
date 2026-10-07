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
An optional model whose answers the app records and gives to groundgate as input.
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
its scale, its key or its field.
_Avoid_: type, kind (source kind is a different term)

**Field alias**:
A word or phrase in the document's words that names a field, such as "loss from operations" for
operating income.
_Avoid_: label (a label is a person's mark on a bench item), synonym

**Quote**:
The text that an evidence item cites, given without a position. groundgate finds its position.
_Avoid_: snippet, excerpt

**Document source**:
The URL that the app gives for the document. An app can trust external sources on the same domain.
_Avoid_: origin, document URL

**Trust level**:
How far groundgate can check an evidence item: checked (document or reference), quoted (external
source) or stated (the extractor's knowledge).
_Avoid_: confidence, strength

**Weak evidence**:
Evidence that supports the value but has a missing part, or a part that groundgate cannot check.
It gives the outcome `needs_verification`.

**No evidence**:
Evidence that does not support the value. It gives the outcome `rejected`.
_Avoid_: unsupported, hallucinated

## Decisions

**Outcome**:
The result of one decision: `admitted`, `needs_verification` or `rejected`.
_Avoid_: verdict, status

**Feedback**:
The outcome, the codes and the missing parts that groundgate returns for each candidate and for
each required field with no candidate.
_Avoid_: critique, review notes
