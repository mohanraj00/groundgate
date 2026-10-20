# Keep pack files with receipts

A receipt names each pack that decided it, by id, version and digest. It does not hold the pack.
To verify the receipt later, `verify` needs each pack again with the same digest. groundgate
holds its built-in packs. Your own packs are your files, so you keep them. This page shows a
folder layout that I advise: the pack files in a `packs` folder next to the receipts, with the
digest in each file name. The grant letter and the numbers are made up.

## 1. Admit with your own pack

The pack `lac-x-myapp` adds the Indian scale word "lac" (10^5). The schema names it, and you give
it to `admit`:

```python
import json
import tempfile
from pathlib import Path

import groundgate as gg

lac = {
    "groundgate_pack": 1,
    "type": "vocabulary",
    "id": "lac-x-myapp",
    "version": "1.0.0",
    "scale": {"words": {"lac": 5}},
}
text = "Grant letter\n\nThe grant is 5 lac rupees. The term is 3 years.\n"
schema = {
    "packs": [{"id": "lac-x-myapp", "version": "1.0.0"}],
    "fields": {"grant": {"type": "integer"}, "term_years": {"type": "integer"}},
}
candidates = [
    {"id": "grant", "field": "grant", "value": "500000", "evidence": [{"text": "5 lac"}]},
    {"id": "term", "field": "term_years", "value": "3", "evidence": [{"text": "3 years"}]},
]
receipt = gg.admit(text, schema, candidates, packs=[lac], document_id="grant-0042")
for d in receipt.decisions:
    print(d.candidate_id, d.outcome)
for entry in receipt.to_dict()["packs"]:
    print(entry["id"], entry["version"], entry["sha256"][:23])
```

```text
grant admitted
term admitted
lac-x-myapp 1.0.0 sha256:8b6a2af1f165caa8
```

In a real app, `gg.load_pack(path)` reads the pack from its file and runs the loader checks.

## 2. Store the receipt and its packs

Write the receipt, then write each pack that it names into `packs/`. Skip a built-in pack:
groundgate holds it. Put the id, the version and the start of the digest in the file name. Then
two versions of one pack, or two copies with different words, never take the same name.

```python
work = Path(tempfile.mkdtemp())
receipts = work / "receipts"
(receipts / "packs").mkdir(parents=True)

stored = receipt.to_dict()
(receipts / "grant-0042.json").write_text(json.dumps(stored, indent=2), encoding="utf-8")

mine = {(lac["id"], lac["version"]): lac}  # each pack that you gave to admit
for entry in stored["packs"]:
    pack = mine.get((entry["id"], entry["version"]))
    if pack is None:
        continue  # a built-in pack
    name = f"{entry['id']}-{entry['version']}-{entry['sha256'][7:19]}.json"
    path = receipts / "packs" / name
    if not path.exists():
        path.write_text(json.dumps(pack, indent=2), encoding="utf-8")

print(sorted(p.name for p in (receipts / "packs").iterdir()))
```

```text
['lac-x-myapp-1.0.0-8b6a2af1f165.json']
```

The folder now looks like this:

```text
receipts/
  grant-0042.json
  packs/
    lac-x-myapp-1.0.0-8b6a2af1f165.json
```

The digest is over the canonical JSON of the pack (SPEC §4.8), so the indent of the file does
not change it. Never edit a pack file after a receipt names it. For a new word, write a new
version.

## 3. Verify a stored receipt

Give `verify` the folder as `pack_dir`. It finds each pack by the digest in the receipt, not by
the file name:

```python
stored = json.loads((receipts / "grant-0042.json").read_text(encoding="utf-8"))
check = gg.verify(stored, text, schema, candidates, pack_dir=receipts / "packs")
print(check.ok, check.problems)
```

```text
True ()
```

The command line does the same:

```bash
groundgate verify receipts/grant-0042.json grant.txt schema.json candidates.json --pack-dir receipts/packs
```

The review page verifies the receipt first, so give it the same folder. In Python, `render`
takes `pack_dir`:

```python
from groundgate.report import render

html = render(stored, text, candidates, schema=schema, pack_dir=receipts / "packs")
print("receipt verified" in html)
```

```text
True
```

On the command line, `report` takes `--pack-dir`:

```bash
groundgate report receipts/grant-0042.json grant.txt schema.json candidates.json --pack-dir receipts/packs -o grant-0042.html
```

Without the folder, `report` gives the problem of the missing pack and does not write the page.

## 4. A pack that is not there, or that changed

If the folder does not hold the pack, `verify` names the id, the version and the digest. Then
you know which file to find. It checks nothing more:

```python
import re

empty = work / "empty"
empty.mkdir()
check = gg.verify(stored, text, schema, candidates, pack_dir=empty)
for problem in check.problems:
    print(re.sub(r"(sha256:\w{16})\w+", r"\1...", problem))
```

The digests in the output are cut to 16 digits:

```text
pack 'lac-x-myapp' 1.0.0 with the digest sha256:8b6a2af1f165caa8... is not built in, not given and not in the pack folder
```

If someone edits the pack file, its digest changes, and `verify` names both digests:

```python
path = receipts / "packs" / "lac-x-myapp-1.0.0-8b6a2af1f165.json"
changed = dict(lac, scale={"words": {"lac": 5, "lakh": 5}})
path.write_text(json.dumps(changed), encoding="utf-8")
check = gg.verify(stored, text, schema, candidates, pack_dir=receipts / "packs")
for problem in check.problems:
    print(re.sub(r"(sha256:\w{16})\w+", r"\1...", problem))
```

```text
pack 'lac-x-myapp' 1.0.0: the receipt names the digest sha256:8b6a2af1f165caa8..., and the pack folder has only the digest sha256:c6287f1f327d6bc8...
```

## 5. What `verify` reads from the folder

`verify` treats the folder as untrusted input. `report` and `render` read the folder through
`verify`, so the same rules apply:

- It reads only the `.json` files directly in the folder, at most 256 files.
- It does not follow a link, so a link cannot point it out of the folder.
- It refuses a file of more than 1 MiB before it parses the file.
- It runs the loader checks of SPEC §4.8 on each file, and computes the digest itself.
- It uses a file only when that digest is the digest in the receipt. A file that fails a check
  is never used. If a pack is then not found, a problem names the first three files that failed.

Keep the folder where only your app writes. `verify` cannot use a wrong file, but a file that is
not there makes an old receipt fail.

A receipt also needs the groundgate release of its spec version, for the base pack and the
built-in packs. See [Pin the groundgate version](review.md#6-pin-the-groundgate-version).
