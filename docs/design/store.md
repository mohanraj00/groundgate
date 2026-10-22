# The store: one data model for all the tools

Status: approved on 2026-10-20, issue #288. Code issue 1 is built: `groundgate.store` (#402).
Code issue 2 is built: packets and readings (#403).
Code issue 3 is built: `store check`, `store rebuild` and `store forget` (#404).
The `splits` log of code issue 5 is built (#406). The calibrate labels of issue 5 are not.
The rest is not built. The note changes no decision and no receipt.
[review.md](review.md) (#287) keeps its data here. The last section lists the code issues.

## 1. The answers in short

| Question (#288) | My answer | Section |
|---|---|---|
| What the store holds | Objects that never change, logs that only grow, and views that the store can build again. | 3 |
| The key | `sha256:` and SHA-256 over `groundgate-object/1:`, the kind, a zero byte and the exact bytes. The kind has a version, for example `text@1`. The prefix names the key scheme, not the spec or the runner. | 4 |
| The manifest | Two objects: `reading@1` (from source to text) and `packet@1` (one `admit` call). The run record stays the manifest of a run, and the packet names it. | 5 |
| The interface | Five operations: `put`, `get`, `append`, `read` and `forget`. | 6 |
| The reference store | A folder, with the standard library only. Views are JSON files. No SQLite in format 1. | 7 |
| Two writers at the same time | Each log has one writer. Two reviewers write two logs. | 7.3 |
| Deletion | `forget` removes each object with document content and records it. `verify` then says "input deleted". | 8 |
| The runner | It takes the store key at its next record version, with #382 if #382 changes the record. | 9 |
| Calibrate and the bench | Calibrate reads its labels and its split from the store after #385. The published bench sets keep their files. | 10 |

## 2. Three options

**A. A folder of objects, logs and views.** Each object is a file named by its key. Each log is a
file of canonical JSON lines. This is what the runner already does: `RunResult.write` keeps
`objects/<hex>` and `run.jsonl`. This note makes that layout general.

**B. A SQLite file as the truth.** One file, with transactions and more than one writer. But
`sqlite3` is absent from some Python builds. The data then needs a migration for each format
version. An app with other storage must also map tables, not files.

**C. A manifest only.** groundgate defines the manifest, and the app keeps the files. This is the
smallest change. But each app must then solve the same key, deletion and concurrency problems,
and the review server has no place to write.

I choose A. If a view becomes slow, a SQLite index can come later as a view.

## 3. Three kinds of data

1. **Objects** never change: source bytes, text, layout, schema, policy, packs of the app,
   references, candidate lists, judgments, receipts, prompts, replies, admission packets,
   readings, packets, review tasks and resolutions. The runner writes its record one time, at
   the end of a run. Thus the store keeps the record as one object, and the chain stays inside it.
2. **Logs** only grow: the review answers, the splits of #383 and the deletions. Each record holds
   the digest of the record before it.
3. **Views** are derived: the reading cache, the review queue, the latest resolution, the labels
   for calibrate and the measures. A view comes only from objects and logs, so the store can
   always build it again. A view needs no backup and no audit, and the user can delete it.

## 4. The key

```text
key = "sha256:" + hex(SHA-256("groundgate-object/1:" + kind + "\0" + bytes))
```

The key cannot be the core digest. `digest()` in `src/groundgate/canonical.py` puts the spec
version in its prefix. That is correct for a receipt, because it binds the decision to one spec.
For a store it is wrong: the same text gets a new key in each spec version, so the cache misses
and the store keeps two copies.

The runner prefix has the same problem one level down. `groundgate-run/2:<kind>` names the
record version. When `groundgate-run/1` became `groundgate-run/2` in 0.10, the same text got a
new key. The store prefix changes only when the key scheme changes.

| Kind | Bytes | Written by |
|---|---|---|
| `source@1` | the exact source file | `read` |
| `text@1` | the UTF-8 of the NFC text | `read`, `extract`, `admit` |
| `layout@1` | canonical JSON of the pages and word boxes | `read` |
| `reading@1` | section 5.1 | `read` |
| `schema@1`, `policy@1`, `reference@1` | canonical JSON of the object that `admit` took | `extract`, `admit` |
| `pack@1` | canonical JSON of a pack of the app. Built-in packs stay in the wheel. | `admit` |
| `candidates@1`, `judgments@1` | canonical JSON of the list | `extract`, `admit` |
| `receipt@1` | canonical JSON of `Receipt.to_dict()` | `admit` |
| `prompt@1`, `reply@1` | the exact strings | `extract` |
| `admission@1` | canonical JSON of an admission packet | `extract` |
| `run@N` | the run record, one canonical JSON line for each entry. `N` is the record version. | `extract` |
| `packet@1` | section 5.2 | `extract`, `admit` |
| `review-policy@1`, `task@1`, `resolution@1` | review.md §5 | `review` |
| `document@1` | the document model of #285, in 0.12 | `read` |

- `put` refuses JSON bytes that are not canonical, so one object has one key.
- The version of a kind is the version of its store format, not the spec version. A receipt
  names its own spec in its member `groundgate`.
- `verify` gets each object by its store key and calculates the core digest again. The receipt
  format does not change.

## 5. The manifest

The runner header is the manifest of a run, and I do not change it. But two steps have no run:
`read` before an extraction, and an app that calls `admit` with its own extractor. So I add two
small objects. They name the same keys as the run header, so no data is copied.

### 5.1 The reading

```json
{"format": "reading@1",
 "source": "sha256:...",
 "reader": {"name": "groundgate.read", "version": "0.11.0"},
 "options": {"pages": null},
 "text": "sha256:...", "layout": "sha256:...", "document": null}
```

The reading cache maps the source key, the reader name and version, and the options to the
reading. If the reader changes, the key changes, so a stale entry never applies (#285, §2).
`document` stays null until the document model of #285.

### 5.2 The packet

```json
{"format": "packet@1", "spec": "0.11",
 "document": {"id": "lease-0417", "source": null, "text": "sha256:..."},
 "reading": "sha256:...",
 "schema": "sha256:...", "policy": "sha256:...",
 "references": ["sha256:..."], "packs": ["sha256:..."],
 "candidates": "sha256:...", "judgments": null,
 "receipt": "sha256:...", "run": "sha256:..."}
```

- `reading`, `judgments` and `run` can be null.
- `packs` names only the packs of the app. The receipt names the built-in packs, and they stay
  in the wheel (packs.md §11).
- `run` is the store key of the run record. The run header names the same input keys, and
  `store check` compares them.
- The packet key is the one handle that the user keeps. `verify`, `report`, `replay` and
  `review` take it.

The packet holds no review data, because the packet never changes and answers come later. Tasks
and resolutions name the packet, and the answer logs of a packet are filed under its key.

## 6. The interface

| Operation | Use |
|---|---|
| `put(kind, bytes) -> key` | Write an object. Equal bytes give the same key, and the store keeps one copy. |
| `get(kind, key) -> bytes` | Read an object. The store calculates the key again on each read and stops on a difference. |
| `append(log, record) -> head` | Add a record to a chain. |
| `read(log) -> records` | Read a chain in order, and check each link. |
| `forget(key, reason)` | Remove an object and record the deletion (section 8). |

`get` takes the kind, because the key covers it. A log name is a log kind and one or two keys,
for example `("answers", packet, reviewer)`. The reviewer part is the store key of the kind
`reviewer@1` over the UTF-8 of the reviewer name. The set part of a `splits` log is the store
key of the kind `set@1` over the UTF-8 of the set name. Thus the file name is a digest, not the
name that the CLI takes, and a name never becomes a path.

Each log record has `sequence`, `previous` and `entry_sha256`, as the run record has.
`entry_sha256` is a store key of the kind `<log>-entry@1` over the record without that member.

An app with other storage implements the five operations. groundgate ships a contract test
module, and the app runs it against its own store. The core holds no storage code: `admit` and
`verify` take and give plain values, and `groundgate.store` calls them.

## 7. The folder store

### 7.1 Layout

```text
store/
  objects/ab/cdef...                         one file for each object, named by its key
  logs/answers/<packet>/<reviewer>.jsonl     one answer log for each packet and reviewer
  logs/splits/<set>.jsonl                    the splits of #383, one log for each set
  logs/deleted.jsonl                         the deletions
  views/...                                  JSON files; delete them at any time
```

Each path part is a 64-digit hex digest or a fixed word.

### 7.2 Write and read

- Write each object to a temporary file in the same folder, then rename it. A crash never
  leaves half an object.
- If an object file has bytes that do not match its key, `put` writes it again.
- Append each log record as one line, then flush and sync the file. A last line with no line
  break is a torn write. `read` refuses that log and names it. `groundgate store check --repair`
  cuts the line and prints it.
- Read only regular files, not symlinks, within a byte limit of 1 GiB by default, as
  `RunResult.read` does. A FIFO or a device fails before any read.
- Make files with mode 0600 and folders with mode 0700, because documents can be private. An
  option permits group read.

### 7.3 Two writers

Each log has one writer. Before its first append, a writer makes `<log>.lock` with an exclusive
create, and it removes the lock at the end. A second writer on the same log stops with a message
that names the lock. A writer that reads a log and then appends to it makes the lock before
the read: the splits writer does this, so a second writer stops before its append. Two reviewers write two logs, so they can answer at the same time. Objects
need no lock, because two writers of one key write the same bytes.

### 7.4 Views

Views are JSON files under `views/`. `groundgate store rebuild` builds them again from the
objects and logs. Format 1 has five views: the reading cache, the review queue, the latest
resolution of each packet, the labels for calibrate and the measures.

`store rebuild` builds the reading cache now, as `views/readings.json`. It maps each source,
reader and options to its readings, and it leaves out a reading whose text is deleted. The other
four views need the review formats (review.md §13) and the calibrate labels (issue 5), and each
comes with its issue (#432).

## 8. Rules

1. **Name objects only by their digest.** A path or a name from a document, a reply, a manifest
   or a request never becomes a file path. That data is untrusted. A key must match
   `sha256:[0-9a-f]{64}` before the store builds a path from it.
2. **Version each format.** A new version is a new kind tag, for example `answer@2`. An old key
   never gets a new meaning.
3. **Plan for deletion.** Documents can be private, and an app can have to delete them.
   `forget` removes these objects and keeps the others:

   | Removed | Kept |
   |---|---|
   | `source@1`, `text@1`, `layout@1`, `document@1`, `reference@1`, `candidates@1`, `prompt@1`, `reply@1`, `admission@1` | `packet@1`, `reading@1`, `receipt@1`, `schema@1`, `policy@1`, `pack@1`, `judgments@1`, `run@N`, `task@1`, `resolution@1`, the answer logs |

   The kept objects hold digests, values, offsets, codes and questions, and no document text
   other than the values. A review question and its choices can quote a value.
   Issue 3 checks that no line of a run record holds document text, and `forget` removes the
   record if a line does. A line holds document text if one of its strings has 8 or more
   characters and is in the text. A store key, a field name of the schema, the document id and
   the document source do not count, because the kept objects hold them. This check is not a
   proof. If the text is already gone, `check` cannot check the lines and prints "not
   checked", and `forget` removes the record. If `forget` cannot read an object, it prints
   "unchecked", removes the rest and exits 1. A run record whose lines cannot be read stays,
   because only the record names its prompts, replies and admissions. With `--all`, its packet
   stays too, so a second `forget` can finish after a repair of the record.
   If a run record names an object that `forget` cannot find, each object of the store that it
   cannot read is "unchecked".
   A value is still document data. If an app must also remove the values,
   `groundgate store forget --all PACKET` removes each object and log of the packet. An object
   of the "Kept" column that another packet names stays.
   One object can serve two packets, because the same text has one key. `forget` of that text
   removes it for both packets, which is correct for one document.
   After `forget`, `verify` reports "input deleted", with the key, the time and the reason from
   `logs/deleted.jsonl`. An absent object with no deletion record gives "input missing". Neither
   gives "mismatch".
4. **Do not store page images.** The review page calculates a crop from the source and the box
   when it needs one, and it keeps the crop as a view. After `forget`, no crop is possible.
5. **Encryption at rest belongs to the app.** The reference store writes plain files.
6. **Use one layout for review and calibrate.** Review answers then become labels for
   `groundgate calibrate` with no conversion (section 10).

## 9. Verify, report, replay and the runner

- `groundgate verify --store DIR PACKET` and `groundgate report --store DIR PACKET` get each
  input from the store. The current options stay.
- The run record names its objects by `groundgate-run/2:<kind>` keys. To take store keys, the
  record format must change, and with it the runner version. 0.11 already changes the runner
  (#382). If #382 makes `groundgate-run/3`, run/3 also takes the store keys, so there is one
  break, not two. If #382 keeps run/2, the key change waits for the next record change.
- `RunResult.write(folder)` stays for run folders. A new `RunResult.save(store)` writes the
  objects, the record and the packet into the store, and returns the packet key.
- A run/2 folder cannot move into the store with new keys, because its record names the old keys.
  It stays a folder, and `RunResult.read` replays it as today.

## 10. Fit with other work

- **#383, the development split.** A `splits` record is
  `{"set": "requested4", "document": "sha256:...", "split": "development"}`, where `document` is
  the source key, or the text key when there is no source. Write it one time, before any label
  or model output for the document. If a second record gives one document another split, the
  view fails and the learning loop stops. The loop reads only packets in the development split.
  A change that the loop freezes (a pack, a prompt or a feedback text) is an object. The
  held-out run names its key, so the store shows that the held-out run used the frozen bytes.
- **#385, calibrate in groundgate.** Calibrate keeps its work folder in 0.11. After #385,
  issue 5 lets `groundgate calibrate` read its labels from a view of the answer logs, and
  `calibrate split` writes the `splits` log. A work folder from 0.10 still works.
- **The bench.** The published sets keep their files, and their numbers never change. A new set
  uses the store only when its issue says so.
- **#287, the review step.** Tasks, policies and resolutions are objects, and answers are logs.
- **#285, the document model.** `document@1` and the reading cache come in 0.12.

## 11. Changes to other design notes

- [runner.md](runner.md) §8: the line "A shared store for all the tools is #288" points here.
  The note gets the store keys and `RunResult.save(store)` when the runner takes them.
- [packs.md](packs.md) §11: `verify` also finds a pack of the app in the store as a `pack@1`
  object, beside `--pack-dir`.
- `docs/howto/keep-packs.md` and `docs/howto/review.md` get the store when issue 2 ships.

## 12. Code issues

I open these after the maintainer approves this note. No issue changes a decision or the receipt
format.

1. **`groundgate.store`.** The key, the five operations, the folder store, the byte limits and
   the locks, and a contract test module. No CLI. Needs a security review.
2. **Packets and readings.** `read --store` writes a reading. `admit --store` writes the inputs,
   the receipt and the packet, and prints the packet key. `verify --store` and `report --store`
   take that key, with "input deleted" and "input missing". Needs a security review.
3. **`store check`, `store rebuild` and `store forget`.** Check each chain and each named object,
   build the views again, and remove objects as section 8 says.
4. **The runner writes to the store.** `RunResult.save(store)`, and the store keys at the next
   record version: with #382 if it changes the record.
5. **Splits and calibrate labels.** The `splits` log for #383, and calibrate labels from the
   answer logs after #385.
6. **Later.** `document@1` and the reading cache with #285 in 0.12, and the crop view with #7.
