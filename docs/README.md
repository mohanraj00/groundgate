# groundgate docs

Release: main, before 1.0.0 (spec 0.13).

groundgate checks the values that an extractor takes from a document, and returns one decision
for each value with the reason. Start with the [quickstart](../README.md#quickstart). Then pick
the page for your task, or the page of a command or a function.

## How-to guides

| Task | Page |
|---|---|
| Write a schema for your documents | [schema.md](schema.md) |
| Use only the core: admit, verify and the receipt | [howto/core-only.md](howto/core-only.md) |
| Check your own model's extractions, end to end | [howto/own-model.md](howto/own-model.md) |
| Send the reasons back to the extractor and decide again | [howto/feedback.md](howto/feedback.md) |
| Check values in financial tables | [howto/tables.md](howto/tables.md) |
| Read DOCX, XLSX and other files with their nodes | [howto/documents.md](howto/documents.md) |
| Read scanned PDFs with OCR, and review their values | [howto/scanned-pdfs.md](howto/scanned-pdfs.md) |
| Use references, web sources and the model's knowledge | [howto/outside-sources.md](howto/outside-sources.md) |
| Review flagged facts, and keep and verify receipts | [howto/review.md](howto/review.md) |
| Read review tasks and send answers over HTTP | [howto/review-api.md](howto/review-api.md) |
| Keep your pack files with your receipts | [howto/keep-packs.md](howto/keep-packs.md) |
| Run groundgate as a job in a container or on a cluster | [howto/job-runner.md](howto/job-runner.md) |
| Check LangExtract output | [guide.md#langextract](guide.md#langextract) |
| Measure a judge's thresholds on your documents | [howto/calibrate.md](howto/calibrate.md) |

## Commands

| Command | Purpose |
|---|---|
| [groundgate read](cli/read.md) | Turn a PDF, HTML, XML, DOCX, XLSX or text file into NFC text. |
| [groundgate schema](cli/schema.md) | Write the JSON Schema of the extractor output. |
| [groundgate schema check](cli/schema-check.md) | Find schema settings that make a check fail each time. |
| [groundgate admit](cli/admit.md) | Decide the candidates and write a receipt. |
| [groundgate verify](cli/verify.md) | Decide again from the inputs and compare with the receipt. |
| [groundgate report](cli/report.md) | Verify a receipt, then write an HTML review page. |
| [groundgate export](cli/export.md) | Verify a stored receipt and export its facts. |
| [groundgate pack list](cli/pack-list.md) | List the built-in packs and their status. |
| [groundgate review tasks](cli/review-tasks.md) | Write the review tasks of a packet to the store. |
| [groundgate review serve](cli/review-serve.md) | Answer the review tasks in the browser. |
| [groundgate review api](cli/review-api.md) | Serve the review API over HTTP. |
| [groundgate review resolve](cli/review-resolve.md) | Resolve the answers to the tasks of a packet. |
| [groundgate review measures](cli/review-measures.md) | Print the measures of the answers in a store. |
| [groundgate store check](cli/store-check.md) | Check each object, chain and packet of a store. |
| [groundgate store rebuild](cli/store-rebuild.md) | Build the views of a store again. |
| [groundgate store forget](cli/store-forget.md) | Remove the document data of a packet. |
| [groundgate store pin](cli/store-pin.md) | Write a source file to the store and print its pin. |
| [groundgate calibrate](calibrate.md) | Experimental: measure a profile or a judge on your documents. |

## Functions

| Function | Purpose |
|---|---|
| [gg.admit()](api/admit.md) | Decide the candidates and return a receipt. |
| [gg.verify()](api/verify.md) | Decide again from the inputs and compare with the receipt. |
| [gg.extractor_schema()](api/extractor-schema.md) | The JSON Schema of the extractor output. |
| [gg.candidate_schema()](api/candidate-schema.md) | The JSON Schema of a candidate. |
| [gg.feedback_message()](api/feedback-message.md) | The text that tells the extractor how to fix a decision. |
| [gg.load_pack()](api/load-pack.md) | Read and check a vocabulary or kind pack. |
| [gg.digest()](api/digest.md) | The SHA-256 digest of an object, as the receipt has it. |
| [gg.jcs()](api/jcs.md) | The canonical JSON bytes of an object (RFC 8785). |
| [load_profile()](api/load-profile.md) | Read a document-family profile. |
| [check_profile()](api/check-profile.md) | Check a document-family profile. |
| [read()](api/read.md) | Read a file into text and a layout. |
| [read_document()](api/read-document.md) | Read a file into a document with its nodes. |
| [extract()](api/extract.md) | Run an extractor, admit, and repair with feedback. |
| [replay()](api/replay.md) | Run a saved extraction again with no model call. |
| [to_candidates()](api/to-candidates.md) | Turn LangExtract output into candidates. |
| [admit_document()](api/admit-document.md) | Admit the LangExtract output of one document. |
| [render()](api/render.md) | Write the HTML review page of a receipt. |
| [FolderStore](api/folder-store.md) | A store in a folder for packets, receipts and answers. |
| [admit_packet()](api/admit-packet.md) | Admit and write the packet to a store. |
| [load_packet()](api/load-packet.md) | Read a packet and its inputs from a store. |

## Reference

- [guide.md](guide.md): every input, policy key, code, function and command, with defaults.
- [calibrate.md](calibrate.md): the experimental `groundgate calibrate` command, step by step.
- [SPEC.md](../SPEC.md): the normative rules of every decision. Another implementation conforms
  when it passes the vectors in [conformance/](../conformance).
- [CONTEXT.md](../CONTEXT.md): the terms that the docs use.
- [CHANGELOG.md](../CHANGELOG.md): what each version changes, with its measure.

## Decisions and designs

- [adr/0001-admit-by-policy.md](adr/0001-admit-by-policy.md): why the app's policy, not
  groundgate, decides whether to trust evidence from outside the document.
- [design/hybrid-decisions.md](design/hybrid-decisions.md): recorded judgments from a model or a
  person. Partly built.
- [design/locale-packs.md](design/locale-packs.md): number formats outside English. A design.

## The benchmark

[bench/README.md](../bench/README.md) has every measure behind the numbers in the README, and each
set's `results.json`.
