# Contributing

Issues and pull requests are welcome. For anything that changes a decision, open an issue first
with the "Spec change" form: decisions are defined by [SPEC.md](SPEC.md), not by the code.

Issues labelled `spec` change a decision and ship as a new spec version. `benchmark` covers
`bench/`. The milestone of the next spec version holds what it is measured on.

## Setup

```bash
uv sync
uv run pytest
```

Before you push, run what CI runs:

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

`uv run --group langextract pytest tests/test_langextract.py` also runs the adapter against a
real LangExtract install.

## Outside pull requests

If you do not have write access to this repository, your PR comes from a fork. I read each one,
and these steps make it fast:

1. Open an issue first, or name the issue that the PR fixes. The PR body says `Fixes #N`.
2. Run the full check before you push:
   `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`.
3. Open the PR. CI runs on the PR after I read the diff and approve the run.
4. Do not edit `CHANGELOG.md`. Put the changelog line in a `## Changelog` section of the PR body
   instead, or write "none" if users will not notice the change.
5. Do not change `.github/`, `SPEC.md` or `conformance/`, or a `.claude/`, `.codex/`,
   `.mcp.json`, `AGENTS.md` or `CLAUDE.md` (also the `.local.md` and `.override.md` forms) in any
   directory, unless the maintainer approved it on an issue. The check `outside-pr-paths` fails a
   fork PR that changes these paths or `CHANGELOG.md`, until I add the label
   `maintainer-approved`. After each new push, I read the new diff, then remove the label and add
   it again.

What happens next is in [docs/maintainers/outside-prs.md](docs/maintainers/outside-prs.md): who
reviews the PR, the labels, and when an open PR closes.

## Rules that keep the project honest

The principles and the evidence rules are in [CONSTITUTION.md](CONSTITUTION.md#principles):
no dependencies in the core, no model inside the decision, vectors for each spec change, and
measures on documents that a rule was not written from.

## Releasing

1. Set `__version__` in `src/groundgate/__init__.py` and the version and date in `CITATION.cff`,
   and rename `CHANGELOG.md`'s "Unreleased" section to the version and date.
2. Commit, then tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. The release workflow builds once, tests that exact wheel on Linux and macOS, publishes it to
   PyPI through trusted publishing (no token is stored), and creates the GitHub release with the
   changelog section as its notes.

## License

The license of a contribution is in [CONSTITUTION.md](CONSTITUTION.md#contributions).
