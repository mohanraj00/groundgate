# The CPU time of the core (#480)

I measured where the time of the 0.11 runner goes on the 59 held-out documents of this set.
This runner has the deeper search of #390. The core uses 2.984% of the live wall time. The model
calls use 91.27%. On `bench/requested3` the core used 2.133%, so the share is 0.851 points
higher and stays under 5%. By the rule in #384, a faster core changes nothing now, so I opened
no issue for a second implementation.

## Method

`bench/core_time.py` replays the `runner_drop_rounded` arm from the recorded calls of the
`runner` arm, as in [bench/requested3/CORE_TIME.md](../requested3/CORE_TIME.md). The script did
not change. It makes no model call: a missing call or a changed prompt stops the script. It
checks that the replay sends the same prompts as the `runner` record and that each receipt is
the same as the published receipt of the arm. It writes nothing into the cache.

For each document the script records the CPU time in `admit`, in the targeted search and in
`verify`, the replay wall time and the size of the reader text. The run calls `admit` 591 times
and the search 107 times. `verify` checks the final receipt of each document once, as an
application does after `admit`. The reader (PDF to text) is not in these numbers.

The live numbers come from the call timestamps of the `runner` arm: the cache writes a
reservation before each call and the reply after it. The live wall time of a document starts
at its first reservation and stops at its result. The model time is the sum of the time from
each reservation to its reply.

The run configuration is the `provenance.configuration` of `runs/runner.json`. The record
digest is the sha256 of the bytes of the configuration file. An earlier copy of this file had
the same content but other bytes, so its digest did not match. I wrote the file again from
`provenance.configuration` with an indent of 2 and no newline at the end. Its digest is the
record digest, `sha256:6ba231ce6edf6ee50540f2c13bc876f671295b18eec6a9375af1e4d93b88e5a4`.

## Result

The script printed this on 2026-10-22 (Python 3.13.12, one process):

| kind | docs | MB text | admit s | search s | verify s | core s | replay wall s |
|---|---|---|---|---|---|---|---|
| annual | 16 | 10.57 | 152.05 | 8.55 | 8.83 | 169.43 | 272.78 |
| component | 9 | 0.20 | 1.53 | 0.58 | 0.24 | 2.35 | 8.86 |
| sbc | 16 | 0.38 | 2.18 | 0.29 | 0.36 | 2.83 | 12.10 |
| sds | 18 | 0.42 | 1.95 | 3.40 | 0.28 | 5.63 | 15.13 |
| all | 59 | 11.57 | 157.71 | 12.82 | 9.72 | 180.24 | 308.87 |

```
replay: core CPU 180.24 s of 308.87 s wall
replay: CPU 191.12 s, of which the runner outside the core 10.88 s
live runner: 59 documents with calls, wall 6040 s, model 5513 s
share of the core in the live wall time: 2.984%
share of the model calls in the live wall time: 91.27%
largest share of one document: 8.306%
```

The annual reports hold 10.57 of the 11.57 MB of text and 169.43 of the 180.24 s of core time.
The largest single cost is `admit` on annual-c20 (1.26 MB, 28 calls): 31.00 s of its 36.17 s
of core time, against a live wall time of 435 s.

The targeted search uses 12.82 s of CPU time, against 66.04 s on requested3. The two sets have
different documents, so this is not a measure of the deeper search alone.

## Limits

- The replay wall time is higher than the CPU time, so other work on the machine took time
  from the replay. The CPU times are the measure.
- The replay arm runs one more `admit` after the last call (the rounding step), so its core time
  is a little higher than the core time of the live `runner` arm.
- The live wall time is the sum over documents. The live run ran groups at the same time, so
  the elapsed time of the run was shorter, and the share stays the same.

To run it again (the sources and the cache are local work storage, not in the repository):

```bash
uv run python bench/core_time.py bench/requested4 SOURCES CONFIG CACHE/<binding> --json OUT
```
