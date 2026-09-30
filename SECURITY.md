# Security

groundgate decides whether extracted facts can be trusted, so a way to make it decide wrongly is
a security bug. Examples:

- a document, schema or candidate that makes `admit` admit a value the spec rejects, or decide
  differently on the same inputs;
- a receipt that `verify` accepts although its inputs or decisions changed;
- document or candidate text that runs script or escapes its element in the `report` page.

A model extraction that passes every check and is still wrong is not a vulnerability. It is the
documented limit in the README's "What it does not do".

Report a vulnerability privately through GitHub: the repository's **Security** tab, **Report a
vulnerability**. Please don't open a public issue. I aim to reply within a week.

Supported: the latest 0.x release.
