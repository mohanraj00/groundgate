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
- `completeness` (optional): the packet's completeness (SPEC §4.16). `expected.completeness` is
  then the receipt's `completeness` member. A vector without it expects a receipt with no such
  member.
- `outline` (optional): the packet's outline (SPEC §4.17). `expected.outline_sha256` is then
  the receipt's `outline_sha256` member. An expected decision of a `passage` field has
  `passage_sha256`: the digest of the passage text, or null for a rejected decision. Both
  digests are computed in `build.py` from the text that the vector states.

Files in `profiles/` are profile vectors (SPEC §4.10). Each one has a `profile` in place of
`schema`, `policy` and `packs`. `expected.profile` is the receipt's `profile` member, with the
digest written by hand in `build.py`, and `expected.error` true marks an invalid packet.

Files in `pins/` are source pin vectors (SPEC §4.14). Each one has a `pin` beside the other
inputs. `expected.pin` is the receipt's `pin` member, with the digest written by hand in
`build.py`, and `expected.error` true marks an invalid packet.

Files in `places/` are places vectors (SPEC §4.15). Each one has a `places` list beside the
other inputs. Each expected decision has its `locator`, and `expected.places_sha256` is the
digest of the places, both written by hand in `build.py`. `expected.error` true marks an
invalid packet.

Files in `invalid/` are invalid packets. An implementation must refuse them (SPEC §2) and emit no
receipt.

The expectations are written by hand in `build.py`. The script only converts quotes into byte offsets,
independently of groundgate. After editing a vector, re-run it and commit the JSON:

```bash
uv run python conformance/build.py
```

CI rebuilds the vectors and fails if the committed JSON differs.

Every reason code appears in at least two vector files; `tests/test_conformance.py` enforces this.
