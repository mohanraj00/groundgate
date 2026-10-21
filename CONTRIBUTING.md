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
3. Enable Actions in your fork, and push your branch there. CI runs on a push to any branch of a
   fork. Link the green run in the PR body.
4. Do not edit `CHANGELOG.md`. Put the changelog line in a `## Changelog` section of the PR body
   instead, or write "none" if users will not notice the change.
5. Do not change `.github/`, `SPEC.md` or `conformance/` unless the maintainer approved it on an
   issue. The CI job `outside-pr-paths` fails a fork PR that changes these paths, until I add
   the label `maintainer-approved`.

What happens next is in [docs/maintainers/outside-prs.md](docs/maintainers/outside-prs.md): who
reviews the PR, the labels, and when an open PR closes.

## Rules that keep the project honest

- **A spec change comes with vectors.** If a rule in SPEC.md changes, add or edit a vector in
  `conformance/build.py`, write the expected outcome by hand, and run
  `uv run python conformance/build.py`. Never generate expectations by running groundgate.
- **Every reason code keeps two vectors.** `tests/test_conformance.py` enforces it.
- **The core has no dependencies.** Anything that needs a package goes behind an extra
  (`[pdf]`, `[langextract]`) and imports it lazily.
- **No model inside the decision.** The decision is a pure function of its inputs. A model's
  answer enters only as a recorded input (#66), and the core never imports a model. Examples may
  call models; they cache the output so they rebuild without keys.
- **A rule about keys or layout is measured on two kinds.** One of them is not the kind that the
  rule was written from. The key rules of spec 0.3 came from FDA labels, and `bench/status`
  measures them on IRS publications (#113).
- **Examples rebuild byte for byte.** If you touch `src/`, run
  `uv run python examples/irs-590a/build.py` and commit any change it makes. CI fails otherwise.

## Releasing

1. Set `__version__` in `src/groundgate/__init__.py` and the version and date in `CITATION.cff`,
   and rename `CHANGELOG.md`'s "Unreleased" section to the version and date.
2. Commit, then tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. The release workflow builds once, tests that exact wheel on Linux and macOS, publishes it to
   PyPI through trusted publishing (no token is stored), and creates the GitHub release with the
   changelog section as its notes.

groundgate-calibrate (`calibrate/`) is now a thin wrapper that runs `groundgate calibrate`
(#385). Its last release, 0.4.0, requires `groundgate>=0.11`, so it comes after v0.11.0 is on
PyPI:

1. Set the date of the 0.4.0 section in `calibrate/CHANGELOG.md`, and commit.
2. Tag: `git tag calibrate-v0.4.0 && git push origin calibrate-v0.4.0`.
3. `release-calibrate.yml` builds it, tests that wheel with groundgate from PyPI, publishes it
   through its own trusted publisher, and creates the GitHub release.

## License

By contributing you agree that your work is licensed under Apache-2.0.
