# Working on groundgate

[CONTRIBUTING.md](CONTRIBUTING.md) has the setup and the rules. [SPEC.md](SPEC.md) defines every
decision. This file covers how work is run.

## Work starts from an issue

- Pick up work with `gh issue list` and `gh issue view N`. If there is no issue, open one first.
- One branch per issue, named `N-short-slug`. The PR body says `Fixes #N`.
- CI must be green before a PR is ready. The agent that opened the PR merges it (see Two agents).
- Something out of scope turns up: open an issue for it instead of widening the PR.
- Labels: `spec` changes a decision, `benchmark` touches `bench/`, plus the usual `bug`,
  `documentation` and `enhancement`. The next spec version gets its own milestone.

## Two agents

Claude Code and Codex both work on this repository. This file is the one copy of the rules:
`CLAUDE.md` imports it.

- Before you start an issue, add the label `agent:claude` or `agent:codex`. Do not take an issue
  that has the other label or an open PR.
- Claude Code branches are `N-short-slug`. Codex branches are `codex/N-short-slug`. The Claude
  review job finds Codex PRs by that prefix.
- Codex reviews Claude Code PRs, and Claude Code reviews Codex PRs. To ask for a review again,
  comment "@codex review" or "@claude review". Answer each finding on its comment: the fix and
  its commit, or why it does not apply.
- An agent merges its own PR with squash when the required checks pass and the other agent's
  review of the head commit has no open finding. The macOS jobs are not required.
- One agent runs each milestone: it gives each issue to an agent, keeps the milestone's plan issue
  current, and finishes what is left. The maintainer names the runner.
- Only the maintainer tags a release.
- `CLAUDE.local.md` holds local rules that are not in git. If it is there, read it before you
  start, and follow it. Never commit it or quote it.

## Rules that are easy to break

- A change to a decision is a new spec version. Write the vectors by hand in
  `conformance/build.py` before the code, and never generate expectations by running groundgate.
- A new rule is measured on documents it was not written from. Never tune a rule on the v0.1 set
  in `bench/` or set 2 in `bench/set2/`, and never change their published numbers.
- Every benchmark number in the README, a `RESULTS.md`, the changelog or an issue must match its
  set's `results.json`. Rescore with `bench/score.py` and `bench/report.py`; don't type numbers.
- The core stays dependency-free. No model runs inside the decision: a model's answer enters
  only as a recorded input (#66).
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

## Review guidelines

A review checks the PR against this file, its issue and [SPEC.md](SPEC.md). Report these first:

- A decision changes without a new spec version, or without vectors written by hand in
  `conformance/build.py` before the code.
- A benchmark number that does not come from its set's `results.json`, or a changed published
  number of the v0.1 set or set 2.
- A dependency in the core, or a model call inside a decision.
- A doc, SPEC text or docstring that says something the code does not do. Run the example if
  you are not sure.
- A product, employer or client name, an em-dash or an emoji in text that the PR adds.
- Work that the issue does not ask for. It belongs in a new issue.

Give each finding a file and a line, a concrete input that fails, and its effect. Do not report
style that ruff accepts.
