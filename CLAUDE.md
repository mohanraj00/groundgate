# Working on groundgate

[CONTRIBUTING.md](CONTRIBUTING.md) has the setup and the rules. [SPEC.md](SPEC.md) defines every
decision. This file covers how work is run.

## Work starts from an issue

- Pick up work with `gh issue list` and `gh issue view N`. If there is no issue, open one first.
- One branch per issue, named `N-short-slug`. The PR body says `Fixes #N`.
- CI must be green before a PR is ready. The maintainer merges.
- Something out of scope turns up: open an issue for it instead of widening the PR.
- Labels: `spec` changes a decision, `benchmark` touches `bench/`, plus the usual `bug`,
  `documentation` and `enhancement`. Milestone `0.2` is the next spec version.

## Rules that are easy to break

- A change to a decision is a new spec version. Write the vectors by hand in
  `conformance/build.py` before the code, and never generate expectations by running groundgate.
- Spec 0.2 rules are measured on new documents. Never tune a rule on the v0.1 benchmark set in
  `bench/`, and never change its published numbers.
- Every benchmark number in the README, `bench/RESULTS.md`, the changelog or an issue must match
  `bench/results.json`. Rescore with `bench/score.py` and `bench/report.py`; don't type numbers.
- The core stays dependency-free and never calls a model.
- Tags publish to PyPI and can't be undone. Only the maintainer tags a release.

## Writing

Docs, issues, PR descriptions and commit messages sound like the maintainer: first person,
plain, confident, specific numbers instead of adjectives, short sentences. No em-dashes, no
emoji, no filler ("seamless", "robust", "leverage", "delve", "comprehensive"). Keep product,
employer and client names out of the repository, including commit messages.

## Before every commit

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```
