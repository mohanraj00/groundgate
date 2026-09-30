# Contributing

Issues and pull requests are welcome. For anything that changes a decision, open an issue first
with the "Spec change" form: decisions are defined by [SPEC.md](SPEC.md), not by the code.

Issues labelled `spec` change a decision and ship as a new spec version. `benchmark` covers
`bench/`. The `0.2` milestone holds what the next spec version is measured on.

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

## Rules that keep the project honest

- **A spec change comes with vectors.** If a rule in SPEC.md changes, add or edit a vector in
  `conformance/build.py`, write the expected outcome by hand, and run
  `uv run python conformance/build.py`. Never generate expectations by running groundgate.
- **Every reason code keeps two vectors.** `tests/test_conformance.py` enforces it.
- **The core has no dependencies.** Anything that needs a package goes behind an extra
  (`[pdf]`, `[langextract]`) and imports it lazily.
- **No model calls in groundgate itself.** Examples may call models; they cache the output so
  they rebuild without keys.
- **Examples rebuild byte for byte.** If you touch `src/`, run
  `uv run python examples/irs-590a/build.py` and commit any change it makes. CI fails otherwise.

## Releasing

1. Set `__version__` in `src/groundgate/__init__.py` and rename `CHANGELOG.md`'s "Unreleased"
   section to the version and date.
2. Commit, then tag: `git tag v0.1.0 && git push origin v0.1.0`.
3. The release workflow builds once, tests that exact wheel on Linux and macOS, publishes it to
   PyPI through trusted publishing (no token is stored), and creates the GitHub release with the
   changelog section as its notes.

## License

By contributing you agree that your work is licensed under Apache-2.0.
