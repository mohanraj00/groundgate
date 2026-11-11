# Working on groundgate

[CONSTITUTION.md](CONSTITUTION.md) has the purpose, the principles, the evidence rules, the
contribution rules and the governance. [docs/STANDARD.md](docs/STANDARD.md) has the rules for
builds, reviews, approvals and CI. [CONTRIBUTING.md](CONTRIBUTING.md) has the setup.
[SPEC.md](SPEC.md) defines every decision. This file covers how work is run in this project.

## Work starts from an issue

- Pick up work with `gh issue list` and `gh issue view N`. If there is no issue, open one first.
- One branch per issue, named `N-short-slug`. The PR body says `Fixes #N`.
- CI must be green before a PR is ready.
- Something out of scope turns up: open an issue for it instead of widening the PR.
- Labels: `spec` changes a decision, `benchmark` touches `bench/`, plus the usual `bug`,
  `documentation` and `enhancement`. The next spec version gets its own milestone.

## Two agents

Claude Code and Codex both work on this repository. `CLAUDE.md` imports `CONSTITUTION.md` and
this file.

- Before you start an issue, add the label `agent:claude` or `agent:codex`. Do not take an issue
  that has the other label or an open PR.
- Claude Code branches are `N-short-slug`. Codex branches are `codex/N-short-slug`.
- The reviewer of each PR, the review requests and the security review trigger are in
  [docs/STANDARD.md](docs/STANDARD.md). [docs/REVIEW.md](docs/REVIEW.md) has the exact request
  texts. `.github/gates.json` names the boundary files of this project.
- Answer each finding on its comment: the fix and its commit, or why it does not apply. Never
  write `@codex` or `@claude` in a PR body, an issue or a commit message: each mention is a
  request.
- Who merges a PR is in the Approvals section of [docs/STANDARD.md](docs/STANDARD.md). The macOS
  jobs are not required.
- Outside PRs (from forks) follow [docs/maintainers/outside-prs.md](docs/maintainers/outside-prs.md).
- An agent never adds or removes the label `maintainer-approved`.
- One agent runs each milestone: it gives each issue to an agent, keeps the milestone's plan issue
  current, and finishes what is left. The maintainer names the runner.
- `CLAUDE.local.md` holds local rules that are not in git. If it is there, read it before you
  start, and follow it. Never commit it or quote it.

## Writing

Docs, issues, PR descriptions and commit messages sound like the maintainer: first person,
plain, confident, specific numbers instead of adjectives, short sentences. No em-dashes, no
emoji, no filler ("seamless", "robust", "leverage", "delve", "comprehensive"). The names that a
contribution must not add are in [CONSTITUTION.md](CONSTITUTION.md#contributions).

## Before every commit

```bash
make check
```

`make check` runs ruff, the ruff format check, mypy and pytest.

## Review guidelines

A review checks the PR against this file, [CONSTITUTION.md](CONSTITUTION.md), its issue and
[SPEC.md](SPEC.md). Report these first:

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

A PR needs a deeper security review when it changes how groundgate reads untrusted input
(documents, candidates, schemas, policies, references, judgments, URLs), the extract or report
paths, a workflow under `.github/`, a release step, or a dependency.

If your review format lets you add text after the findings, end a code review with one line:
`Security review: needed` and the reason, or `Security review: not needed`. Do not ask for the
security review yourself: the agent that opened the PR asks. A security review does not end with
this line.
