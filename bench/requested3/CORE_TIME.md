# The CPU time of the core (#384)

I measured where the time of the 0.10 runner goes on the 111 held-out documents of this set.
The core uses 2.133% of the live wall time. The model calls use 76.37%. By the rule in #384, a
faster core changes nothing now, so I opened no issue for a second implementation.

## Method

`bench/core_time.py` replays the `runner_drop_rounded` arm from the recorded calls of the
`runner` arm. It makes no model call: a missing call or a changed prompt stops the script. It
checks that the replay sends the same prompts as the `runner` record and that each receipt is
the same as the published receipt of the arm. It writes nothing into the cache.

For each document the script records the CPU time in `admit`, in the targeted search and in
`verify`, the replay wall time and the size of the reader text. The run calls `admit` 952 times
and the search 287 times. `verify` checks the final receipt of each document once, as an
application does after `admit`. The reader (PDF to text) is not in these numbers.

The live numbers come from the call timestamps of the `runner` arm: the cache writes a
reservation before each call and the reply after it. The live wall time of a document starts
at its first reservation and stops at its result. The model time is the sum of the time from
each reservation to its reply.

## Result

The script printed this on 2026-10-20 (Python 3.13.12, one process):

| kind | docs | MB text | admit s | search s | verify s | core s | replay wall s |
|---|---|---|---|---|---|---|---|
| annual | 20 | 11.82 | 116.98 | 53.23 | 7.68 | 177.89 | 304.64 |
| component | 18 | 1.33 | 5.21 | 6.45 | 0.90 | 12.56 | 18.55 |
| sbc | 23 | 0.46 | 2.17 | 0.37 | 0.40 | 2.94 | 7.46 |
| sds | 50 | 1.04 | 4.34 | 5.99 | 0.60 | 10.93 | 19.50 |
| all | 111 | 14.65 | 128.70 | 66.04 | 9.59 | 204.33 | 350.15 |

```
replay: core CPU 204.33 s of 350.15 s wall
replay: CPU 217.60 s, of which the runner outside the core 13.26 s
live runner: 111 documents with calls, wall 9580 s, model 7317 s
share of the core in the live wall time: 2.133%
share of the model calls in the live wall time: 76.37%
largest share of one document: 8.228%
```

The annual reports hold 11.82 of the 14.65 MB of text and 177.89 of the 204.33 s of core
time. The largest single cost is `admit` on annual-c17 (1.86 MB, 38 calls): 31.59 s of its
37.70 s of core time, against a live wall time of 458 s.

## Limits

- Other jobs ran on the machine during the replay, so the replay wall time is higher than the
  CPU time. The CPU times are the measure. A first run of the script gave 223.33 s of core CPU
  time and a share of 2.331%, on the same side of 5%.
- The replay arm runs one more `admit` after the last call (the rounding step), so its core time
  is a little higher than the core time of the live `runner` arm.
- The live wall time is the sum over documents. The live run ran 8 groups at the same time, so
  the elapsed time of the run was shorter, and the share stays the same.
- The targeted search uses 66.04 s of CPU time. A deeper search (#382) adds to this part.
  I will run the script again on the next set before a decision on a second core.

To run it again (the sources and the cache are local work storage, not in the repository):

```bash
uv run python bench/core_time.py bench/requested3 SOURCES CONFIG CACHE/<binding> --json OUT
```
