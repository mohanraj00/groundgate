# Conformance vectors

Each file in `vectors/` is a complete, language-agnostic test case:

- `document`: NFC text;
- `schema` and `policy`: inputs as in SPEC §2 (`policy` may be `null`);
- `candidates`: the candidates exactly as proposed; an evidence item has UTF-8 byte offsets, or
  only a quote;
- `judgments`, `references` and `document_source` (optional): inputs as in SPEC §2.1 and §2.6;
- `expected.decisions`: one `{outcome, codes}` per candidate, in input order, and `missing` where
  a part is missing;
- `expected.coverage`: the coverage findings.

Files in `invalid/` are invalid packets. An implementation must refuse them (SPEC §2) and emit no
receipt.

The expectations are written by hand in `build.py`. The script only converts quotes into byte offsets,
independently of groundgate. After editing a vector, re-run it and commit the JSON:

```bash
uv run python conformance/build.py
```

CI rebuilds the vectors and fails if the committed JSON differs.

Every reason code appears in at least two vector files; `tests/test_conformance.py` enforces this.
