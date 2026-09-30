# Changelog

Versions follow [SemVer](https://semver.org). A change to how any candidate is decided is a new
spec version, and receipts name the spec version they were decided under.

## 0.1.0 (2026-09-29)

First release. Implements spec v0.1.

- `admit` and `verify`: deterministic admission with ten rejection codes, five flags, required
  field coverage and re-anchoring, and receipts hashed over RFC 8785 canonical JSON.
- `groundgate extract`: PDF (with `[pdf]`), HTML, XML and text to NFC text, with page and word
  boxes for PDFs. Text a reader can't see is dropped, and superscripts are marked.
- A LangExtract adapter that checks each extraction's value and unit at the place LangExtract
  aligned it.
- `groundgate report`: a self-contained HTML review page that re-derives the receipt before it
  renders.
- 16 conformance vectors and 6 invalid packets, language-neutral, so another implementation can
  prove it agrees.
- A benchmark on 30 public-domain FDA, NTSB and IRS documents with person-checked gold and seven
  models: [bench/RESULTS.md](https://github.com/mohanraj00/groundgate/blob/main/bench/RESULTS.md).
