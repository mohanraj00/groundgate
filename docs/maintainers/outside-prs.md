# Outside pull requests

This is how I handle a pull request from a fork. The rules for the author are in
[CONTRIBUTING.md](../../CONTRIBUTING.md#outside-pull-requests). The rules for the two agents are in
[AGENTS.md](../../AGENTS.md).

The maintainer or the milestone runner does each step. The milestone runner is the agent that
the maintainer named for the current milestone.

## 1. Triage

1. Add the label `external`.
2. Find the issue that the PR fixes. If there is no issue, ask the author to open one or to name
   one, and add `changes-requested`.
3. Read the agent labels on that issue. An agent does not take an issue that has an outside PR.
   If an agent label is on the issue and no agent PR is open, remove the label. If an agent PR
   is open, tell the author, and decide which PR stays.
4. Check that the PR body has a `## Changelog` section and a link to a green CI run in the fork.

## 2. Before "Approve and run"

GitHub holds the CI run of a first-time contributor until a person with write access clicks
"Approve and run". The run uses the code of the PR, so read the whole diff first. Look for:

- a change under `.github/`, most of all a workflow;
- `conftest.py`, a pytest plugin, or a change to the pytest settings in `pyproject.toml`;
- the build settings in `pyproject.toml`, a build hook, or a new dependency;
- a script that a test or a CI step calls, such as `conformance/build.py`,
  `examples/irs-590a/build.py` or a `bench/` script;
- a network call in a test or in a script.

If one of these is in the diff and the issue does not ask for it, do not approve the run. Ask
for the reason, and add `changes-requested`. If the diff is clean, approve the run.

The job `outside-pr-paths` fails a fork PR that changes `.github/`, `CHANGELOG.md`, `SPEC.md` or
`conformance/`. If the maintainer approved the change on its issue, add the label
`maintainer-approved`. The label reruns the job. If GitHub holds that run, approve it too.

Do not trust a green `outside-pr-paths` alone. The job comes from the `ci.yml` of the PR, so a
PR that edits `ci.yml` can change the job. That is one more reason to read the diff first.

## 3. Review

1. The milestone runner asks for the review in a separate comment that holds only:
   `@claude review this PR. Use the Review guidelines in CLAUDE.md.`
   If Codex reviews, the comment holds only `@codex review`.
2. Decide the security review under the rule in AGENTS.md. If it is needed, ask for it once in
   a separate comment that holds only the request.
3. After each push that fixes a finding, read the new diff again before you approve the run.
   Then ask for the review again.

## 4. Disposition

Each outside PR ends with one of these labels:

- `changes-requested`: the PR waits for its author. The comment lists each change as a specific
  item, with the file and the line.
- `accepted`: the maintainer or the milestone runner merges the PR with squash when the required
  checks pass and the review of the head commit has no open finding. The release PR copies the
  line from the `## Changelog` section of the PR body into `CHANGELOG.md`, and credits the
  author, as in "(#123, thanks @author)".
- `declined`: close the PR with the reason. If the idea stays useful, open a new issue for it and
  link it.
- `stale`: if the author does not answer for 14 days after `changes-requested`, close the PR. The
  closing comment says that the author can reopen it.

Remove `changes-requested` when the author pushes the changes. Keep `external` on the PR.
