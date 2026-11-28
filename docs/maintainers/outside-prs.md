# Outside pull requests

This is how I handle a pull request from a fork. The rules for the author are in
[CONTRIBUTING.md](../../CONTRIBUTING.md#outside-pull-requests). The rules for the two agents are in
[AGENTS.md](../../AGENTS.md).

The maintainer or the milestone runner does each step, except a step that the Governance section
of [CONSTITUTION.md](../../CONSTITUTION.md) or [docs/STANDARD.md](../STANDARD.md) gives only to the
owner. For example, an agent never adds the label `accepted` to an issue. The milestone runner
is the agent that the maintainer named for the current milestone.

## 1. Triage

1. Add the label `external`.
2. Find the issue that the PR fixes. If there is no issue, ask the author to open one or to name
   one, and add `changes-requested`.
3. Read the agent labels on that issue. An agent does not take an issue that has an outside PR.
   If an agent label is on the issue and no agent PR is open, remove the label. If an agent PR
   is open, tell the author, and decide which PR stays.
4. Check that the PR body has a `## Changelog` section.

## 2. Before "Approve and run"

GitHub holds the CI run of a first-time contributor until a person with write access clicks
"Approve and run". The run uses the code of the PR, so read the whole diff first. Look for:

- a change under `.github/`, most of all a workflow;
- `conftest.py`, a pytest plugin, or a change to the pytest settings in `pyproject.toml`;
- the build settings in `pyproject.toml`, a build hook, or a new dependency in `pyproject.toml`
  or `uv.lock`;
- a script that a test or a CI step calls, such as `conformance/build.py`,
  `examples/irs-590a/build.py` or a `bench/` script;
- a network call in a test or in a script.

If one of these is in the diff and the issue does not ask for it, do not approve the run. Ask
for the reason, and add `changes-requested`. If the diff is clean, approve the run.

## 3. Protected paths

A fork PR must not change `.github/`, `CHANGELOG.md`, `SPEC.md` or `conformance/`, or a
`.agents/`, `.claude/`, `.codex/`, `.mcp.json`, `AGENTS.md`, `CLAUDE.md` or `GEMINI.md` (also the
`.local.md` and `.override.md` forms) in any directory, unless the owner approved it. These are
level 1 paths of the shared gates and of [.github/gates.json](../../.github/gates.json).

The `acceptance` check of the shared gates protects them. Its rules are in the Fork PRs section
of [docs/STANDARD.md](../STANDARD.md):

- The linked issue has the label `accepted`. Only the owner adds it.
- The owner approves the current head and base in stage 2. A push removes this approval.

## 4. Review

The rules for the review of a fork PR are in the Fork PRs and Review requests sections of
[docs/STANDARD.md](../STANDARD.md). [docs/REVIEW.md](../REVIEW.md) has the exact request texts.
The milestone runner asks for the review, because no agent opens an outside PR. After each push
that fixes a finding, read the new diff again before you approve the run.

## 5. Disposition

Each outside PR ends in one of these ways:

- `changes-requested`: the PR waits for its author. The comment lists each change as a specific
  item, with the file and the line.
- The merge: the maintainer or the milestone runner merges the PR with squash when the required
  checks pass and the review of the head commit has no open finding. The release PR copies the
  line from the `## Changelog` section of the PR body into `CHANGELOG.md`, and credits the
  author, as in "(#123, thanks @author)".
- `declined`: close the PR with the reason. If the idea stays useful, open a new issue for it and
  link it.
- `stale`: if the author does not answer for 14 days after `changes-requested`, close the PR. The
  closing comment says that the author can reopen it.

Remove `changes-requested` when the author pushes the changes. Keep `external` on the PR.
