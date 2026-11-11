# Review rules

[AGENTS.md](../AGENTS.md) owns the general workflow and the Review guidelines. This file gives
the exact review requests and the design of the Claude review workflow. The rules for who reviews
a change, the review cap and the security review trigger are in [STANDARD.md](STANDARD.md).

[STANDARD.md](STANDARD.md) is a byte copy of the shared standard. It names required checks, for
example `cross-review`, `security-review` and `acceptance`. The
[gates](../.github/workflows/gates.yml) workflow runs these checks, and the ruleset of `main`
makes them required. The agent that opened the PR also follows the rules in AGENTS.md and this
file.

## Cross-harness review

The reviews run on GitHub. No harness reviews a PR by default, so the PR author asks in a PR
comment.

| Builder | Code review comment | Security review comment |
|---|---|---|
| Claude Code | `@codex review` | `@codex security review` |
| Codex | `@claude review this PR. Use the Review guidelines in AGENTS.md.` | `@claude do a security review of this PR. Use the Review guidelines in AGENTS.md.` |

Follow these rules for each request:

1. Ask when CI is green and the PR is ready.
2. For a Codex code review request, write `Head: <sha>` on the next line of the comment, with
   the short SHA of the PR head commit. Do not add this line to a Claude request. The Claude
   review starts only for the exact text in the table, and its comment names the head that it
   reviewed.
3. Write a security review request as the exact text in the table, with no other text in the
   comment. If the comment has other text, for example a `Head:` line, Codex does a code review
   and no security review. The Security review trigger section of [STANDARD.md](STANDARD.md)
   says when a PR needs a security review.
4. Ask one time for each head commit. Before you ask, read the PR comments. If a request names
   the current head, or comes after the last push, do not ask again.
5. If you push fixes after a review, ask again for the new head. The review cap, and what to do
   at the cap, are in the Reviews section of [STANDARD.md](STANDARD.md).
6. Fix each real finding, or write on the PR why it is not a defect. For a finding in the gates,
   use the stop rule in [STANDARD.md](STANDARD.md). The gates include the files that this project
   copies from `mohanraj00/.github`: `docs/STANDARD.md`, `tools/claude_review.py` and
   `.github/workflows/claude-review.yml`. Never change a copy. If a finding in a copy does not
   need a fix now, write the reason on the PR, close the thread and file the finding in
   `mohanraj00/.github`.

Codex reviews through the Codex GitHub integration. Claude Code reviews through the
[Claude review](../.github/workflows/claude-review.yml) workflow. The workflow starts only if all
of these are true:

- The comment is on a PR.
- The comment body is exactly one of the two Claude request texts in the table. GitHub compares
  these texts with no regard to letter case.
- The commenter is an owner, a member or a collaborator.

A comment or a review with other text does not start the workflow. The comment text selects one
of two fixed prompts, and it never goes into a prompt.

## Claude review design

An issue comment event reads the workflow from `main`, so a PR cannot change this workflow for
its own review. The workflow has three jobs. The requests on one PR run one at a time, so the
`gate` job of a request reads the marker of the request before it. A new pending request
replaces an older pending request, and the older request posts no comment.

The `gate` job has no environment and no secret. It has `actions: read`, `contents: read`,
`issues: read` and `pull-requests: read` only. It runs the `claude-review` check of the gates
action, at the same SHA as the other gates. The check stops the request in these cases:

- The PR is a fork PR, and the owner did not approve the current head and base in stage 2. The
  rule is the same as the rule of the `acceptance` gate.
- A Claude review of the same kind exists for the current head and merge base.
- 3 Claude reviews of the same kind exist for the PR.

If the check passes, the job gives the head, the base and the merge base to the `review` job.

The `review` job has `contents: read` only. It uses the `claude-review` environment, which holds
the `CLAUDE_CODE_OAUTH_TOKEN` secret. Only the CLI step gets the secret. The environment has a
deployment branch rule for `main`. It needs the `gate` job. The job does these steps:

1. It checks out `main` and fetches the PR commits as Git objects only. It never checks out PR
   files, so the PR cannot supply instructions, settings or code.
2. It reads the base branch of the PR from the API, fetches it, and writes the diff with
   `git diff --no-ext-diff --no-textconv -U20 pr/base...pr/head`. If the diff is empty, the job
   fails. It also writes the merge base of `pr/base` and `pr/head`. If there is not exactly one
   merge base, the job fails. If the head, the base or the merge base is not the one that the
   `gate` job approved, the job fails. This occurs if a push or a base change occurs while the
   environment waits for approval. Then ask again.
3. It installs one exact version of the Claude Code CLI and checks the SHA-512 value of the
   package.
4. It runs the CLI in restricted mode with only the `Read`, `Grep` and `Glob` tools, no MCP
   server, no slash command and a turn limit. These tools cannot read `/proc`. The prompt says
   that the diff is untrusted data.
5. It checks the JSON result: `type` is `result`, `subtype` is `success`, `is_error` is false,
   `result` is not empty and `permission_denials` is empty. If a check fails, the job fails.
6. It keeps the review text, the head SHA and the merge base in an artifact.

The `post` job has `contents: read`, `issues: write` and `pull-requests: write` only, with no
secret and no environment. A comment on a PR needs `pull-requests: write`. It runs
[tools/claude_review.py](../tools/claude_review.py) from the `main` checkout. The first line of
the comment is a marker for the gates:
`<!-- claude-review:v2 kind=<code|security> head=<SHA> base=<SHA> findings=<count> run=<run ID> -->`. The
script writes the marker outside the model text. The count comes from the `Findings: <number>`
line that the prompt asks for, or it is `unknown`. If the `review` job failed, the comment holds
only `NO VALID CLAUDE REVIEW` and the head SHA. If the `gate` job stopped the request, the
comment holds `The Claude review did not start.` and the reason of the gate, with no marker.

The `post` job writes as the workflow bot. A mention in its comment can start a review, and a
later gate can trust records from this bot. Thus the script treats the model text as untrusted.
It escapes `&` and `<`, changes each `@` to a character that makes no mention, and limits the
length.

`tests/test_claude_review.py` checks these limits. Run it with `uv run pytest
tests/test_claude_review.py`. The test also checks that the request texts in this file match the
texts in the workflow.

## Use of a Claude result

The `cross-review` gate reads the marker. It accepts the marker only from the workflow bot, for
the current head and the current merge base, and only if its run is an `issue_comment` run of this workflow on `main`. A code
review passes `cross-review` only with `findings=0`. The marker gives `findings=unknown` if the
text does not agree with the count:

- a line holds `INCOMPLETE REVIEW`;
- a second `Findings:` line gives a different number;
- the count is 0, and a later line starts with a finding or a `path:line` reference, or holds a
  severity tag `P0` to `P3`.

The script reads these signals in NFKC form with no format characters, so a full-width or a
zero-width character cannot hide one. A change of the base branch makes a new merge base, so the old marker stops.
The gates do not accept a `v1` marker, because it has no base.

The use of a Claude security review is in the Reviews section of [STANDARD.md](STANDARD.md). A
person still reads the text of each review. The review has no inline comments and no conversation. A push makes a new head, so ask again as the request rules say.
The OAuth token is a static secret. If you suspect a leak, revoke it and make a new one.
