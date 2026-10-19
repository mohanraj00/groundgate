# Conformance vectors

Each file in `vectors/` is a complete, language-agnostic test case:

- `document`: NFC text;
- `schema` and `policy`: inputs as in SPEC §2 (`policy` may be `null`);
- `candidates`: the candidates exactly as proposed; an evidence item has UTF-8 byte offsets, or
  only a quote;
- `judgments`, `references` and `document_source` (optional): inputs as in SPEC §2.1 and §2.6;
- `packs` (optional): the vocabulary packs and kind packs that the caller gives, as in SPEC §4.8
  and §4.9. Each one is a parsed pack file. The schema names each one in its `packs` member, or
  a kind pack that the schema names needs it;
- `expected.decisions`: one `{outcome, codes}` per candidate, in input order, and `missing` where
  a part is missing. `parts` (optional) gives the `role` and `passed` of each listed part, in
  order;
- `expected.coverage`: the coverage findings.
- `expected.relations` (optional): the receipt's relation results (SPEC §5), in receipt order.
  A vector without it has a schema with no relations.

Files in `invalid/` are invalid packets. An implementation must refuse them (SPEC §2) and emit no
receipt.

The expectations are written by hand in `build.py`. The script only converts quotes into byte offsets,
independently of groundgate. After editing a vector, re-run it and commit the JSON:

```bash
uv run python conformance/build.py
```

CI rebuilds the vectors and fails if the committed JSON differs.

Every reason code appears in at least two vector files; `tests/test_conformance.py` enforces this.
