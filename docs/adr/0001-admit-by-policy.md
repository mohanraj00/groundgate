---
status: accepted
---

# Admit by policy, and say so in the receipt

Until spec 0.4, groundgate admitted only what a pinned document supported. Some right values come
from outside the document: a web page, or the extractor's own knowledge (#125). groundgate cannot
check these. From spec 0.5 (#141), groundgate admits what checked evidence supports, plus what the
app's policy allows. The receipt shows which of the two applies: a value that the policy admits
gets `ADMITTED_BY_POLICY` and the source kind. groundgate is one step in a pipeline that the app
owns, so the trust decision belongs to the app. The default policy sends quoted and stated evidence
to review, so an app that changes nothing never admits these values. Spec 0.4 rejected them.

## Considered options

- **Never admit evidence from outside the document.** This keeps the old contract. But a right value
  goes to review in every pipeline, also when the app trusts the source, and the app cannot change
  that.
- **Trust an external source on the document's own domain automatically.** One domain holds many
  pages, some of them old, and the extractor still supplies the quote. The app can trust the
  document's host with the `document-domain` allow-list entry. groundgate does not do it by default.
- **Treat an app-supplied reference as external.** The app is part of the trusted pipeline, and it
  supplies the reference text. So groundgate checks a reference like the document.
