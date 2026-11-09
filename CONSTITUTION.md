# Groundgate constitution

Version 1, 2026-11-09.

## Purpose

groundgate is a deterministic admission layer for LLM document extraction. It checks each
proposed value against the text that the value cites, with fixed rules and no model in the
decision. You give it a document, a schema, and the facts an extractor proposed.

The goal is to admit as many fields as possible with the right value, while wrong values almost
never get in.

## Boundaries

No project text yet.

## Principles

- **The core has no dependencies.** Anything that needs a package goes behind an extra
  (`[pdf]`, `[ocr]`, `[langextract]`) and imports it lazily. Only two modules start a
  process, each with a list of arguments, no shell and a timeout: `read/ocr.py` starts the
  `tesseract` program, and `read/crop.py` starts `python -I` to render a crop of a scan for the
  review page.
- **No model inside the decision.** The decision is a pure function of its inputs. A model's
  answer enters only as a recorded input (#66), and the core never imports a model. Examples may
  call models; they cache the output so they rebuild without keys.

## Evidence

I judge every rule by two numbers: the facts admitted with a right value, and the wrong
extractions admitted (escapes). Reviews are the cost between them: each one is a value that a
person confirms by hand.

- **A change to a decision is a new spec version, and it comes with vectors.** If a rule in
  SPEC.md changes, add or edit a vector in `conformance/build.py` before the code, write the
  expected outcome by hand, and run `uv run python conformance/build.py`. Never generate
  expectations by running groundgate.
- **Every reason code keeps two vectors.** `tests/test_conformance.py` enforces it.
- **A new rule is measured on documents it was not written from.** Never tune a rule on the v0.1
  set in `bench/` or set 2 in `bench/set2/`, and never change their published numbers.
- **A rule about keys or layout is measured on two kinds.** One of them is not the kind that the
  rule was written from. The key rules of spec 0.3 came from FDA labels, and `bench/status`
  measures them on IRS publications (#113).
- **Every benchmark number matches its set's `results.json`.** This applies to the README, a
  `RESULTS.md`, the changelog and an issue. Rescore with `bench/score.py` and `bench/report.py`;
  don't type numbers.
- **Examples rebuild byte for byte.** If you touch `src/`, run
  `uv run python examples/irs-590a/build.py` and commit any change it makes. CI fails otherwise.

## Contributions

- Keep product, employer and client names out of the repository, including commit messages.
- By contributing you agree that your work is licensed under Apache-2.0.

## Governance

<!-- governance:start v1 -->
This project follows the project standard in `docs/STANDARD.md`. That file is an exact copy from `mohanraj00/.github`. The standard owns the rules for builds, reviews, approvals and CI. A project exception to the standard is valid only when the standard records it.

The documents own these topics:

- `CONSTITUTION.md`: the purpose, the boundaries, the principles, the evidence rules, the contribution rules and the version log.
- `docs/STANDARD.md`: the builds, the reviews, the approvals and CI.
- `AGENTS.md`: the layout, the check command and the review guidelines.
- `CLAUDE.md` and `GEMINI.md`: imports only.

These rules apply to each change:

1. A harness does not review its own change. The Codex security review is the one exception, as the standard says.
2. The agents use the owner login. An agent never approves a PR and never merges a level 1 PR. An agent never adds the labels `accepted`, `security-reviewed`, `cross-reviewed` or `ready-for-review`.
3. The owner merges each level 1 PR.
4. Each tag, release, package publication, visibility change and outreach step needs a separate owner approval.
<!-- governance:end v1 -->

## Amendment

Change this constitution when the owner changes direction or evidence changes a decision. A change is a level 1 PR. Record the reason in the change, and add an entry to the version log.

Change the governance block only with a new version of the template in `mohanraj00/.github`.

## Version log

### Version 1, 2026-11-09

The first version. It moves the existing project rules from `README.md`, `AGENTS.md` and `CONTRIBUTING.md` into the sections of template v1, and adds the governance block. Reason: the project standard gives each project one constitution with the same sections and the same governance block.
