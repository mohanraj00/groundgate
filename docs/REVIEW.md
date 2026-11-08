# Review rules

[AGENTS.md](../AGENTS.md) owns the general workflow and the Review guidelines. This file gives
the exact review requests and the design of the Claude review workflow.

[STANDARD.md](STANDARD.md) is a byte copy of the shared standard. It names required checks, for
example `cross-review`, `security-review` and `acceptance`. The
[gates](../.github/workflows/gates.yml) workflow runs these checks, and the ruleset of `main`
makes them required. The agent that opened the PR also follows the rules in AGENTS.md and this
file.

## Cross-harness review

A harness does not review its own change. The reviews run on GitHub. No harness reviews a PR by
default, so the PR author asks in a PR comment.

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
   and no security review. AGENTS.md says when a PR needs a security review.
4. Ask one time for each head commit. Before you ask, read the PR comments. If a request names
   the current head, or comes after the last push, do not ask again.
5. If you push fixes after a review, ask again for the new head. Ask at most 3 times for each
   PR. After that, ask the maintainer to review.
6. Fix each real finding, or write on the PR why it is not a defect.

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
its own review. The workflow has two jobs.

The `review` job has `contents: read` only. It uses the `claude-review` environment, which holds
the `CLAUDE_CODE_OAUTH_TOKEN` secret. Only the CLI step gets the secret. The environment has a
deployment branch rule for `main`. The job does these steps:

1. It checks out `main` and fetches the PR commits as Git objects only. It never checks out PR
   files, so the PR cannot supply instructions, settings or code.
2. It reads the base branch of the PR from the API, fetches it, and writes the diff with
   `git diff --no-ext-diff --no-textconv -U20 pr/base...pr/head`. If the diff is empty, the job
   fails.
3. It installs one exact version of the Claude Code CLI and checks the SHA-512 value of the
   package.
4. It runs the CLI in restricted mode with only the `Read`, `Grep` and `Glob` tools, no MCP
   server, no slash command and a turn limit. These tools cannot read `/proc`. The prompt says
   that the diff is untrusted data.
5. It checks the JSON result: `type` is `result`, `subtype` is `success`, `is_error` is false,
   `result` is not empty and `permission_denials` is empty. If a check fails, the job fails.
6. It keeps the review text and the head SHA in an artifact.

The `post` job has `contents: read`, `issues: write` and `pull-requests: write` only, with no
secret and no environment. A comment on a PR needs `pull-requests: write`. It runs
[tools/claude_review.py](../tools/claude_review.py) from the `main` checkout. The first line of
the comment is a marker for the gates:
`<!-- claude-review:v1 kind=<code|security> head=<SHA> findings=<count> run=<run ID> -->`. The
script writes the marker outside the model text. The count comes from the `Findings: <number>`
line that the prompt asks for, or it is `unknown`. If the `review` job failed, the comment holds
only `NO VALID CLAUDE REVIEW` and the head SHA.

The `post` job writes as the workflow bot. A mention in its comment can start a review, and a
later gate can trust records from this bot. Thus the script treats the model text as untrusted.
It escapes `&` and `<`, changes each `@` to a character that makes no mention, and limits the
length.

`tests/test_claude_review.py` checks these limits. Run it with `uv run pytest
tests/test_claude_review.py`. The test also checks that the request texts in this file match the
texts in the workflow.

## Use of a Claude result

The `cross-review` gate reads the marker. It accepts the marker only from the workflow bot, for
the current head, and only if its run is an `issue_comment` run of this workflow on `main`. A code
review passes `cross-review` only with `findings=0`. If the first line says `Findings: 0` and a
later line starts with a severity tag or a `path:line` reference, the marker gives
`findings=unknown`.

A Claude security review is advisory. The `security-review` gate does not accept it. The owner
reads the review, then adds the `security-reviewed` label. A person still reads the text of each
review. The review has no inline comments and no conversation. A push makes a new head, so ask again as the request rules say.
The OAuth token is a static secret. If you suspect a leak, revoke it and make a new one.
