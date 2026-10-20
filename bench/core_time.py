"""Measure the CPU time of the core in a replay of a requested set (#384).

The script replays one runner arm of a requested set from its call cache, with no model call.
For each held-out document it records the replay wall time, the CPU time in ``admit``, in
``verify`` and in the targeted search, and the size of the reader text. It also reads the call
timestamps of the live ``runner`` arm (the modification times of the cache files) and gives the
live wall time and the model time of each document. So the share of the core in the live wall
time is known.

The cache is only read. The script writes nothing into it, and it never calls a model: a call
that is not in the cache, or a prompt that differs from its record, stops the run.

    uv run python bench/core_time.py bench/requested3 SOURCES CONFIG CACHE [--json OUT]

CACHE is the binding folder of the run (``<cache>/<binding sha256>``). ``verify`` checks the
final receipt of each document once, as an application does after ``admit``. The run itself
calls only ``admit`` and the targeted search. The reader (PDF to text) is not timed: the texts
are read before the run.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from requested.run_set import FrozenSet, _json, _prompts, _read, _settings, digest

import groundgate as gg
import groundgate.extract.runner as runner_module
from groundgate.extract import RunPolicy, extract

Json = dict[str, Any]
PARTS = ("admit", "search", "verify")


class Clock:
    """CPU time of the outermost core call, for each part. A nested core call is not counted
    twice: it belongs to the part of the call that holds it."""

    def __init__(self) -> None:
        self.cpu: dict[str, float] = defaultdict(float)
        self.count: dict[str, int] = defaultdict(int)
        self.depth = 0

    def wrap(self, part: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def timed(*args: Any, **kwargs: Any) -> Any:
            if self.depth:
                return function(*args, **kwargs)
            self.depth += 1
            start = time.process_time()
            try:
                return function(*args, **kwargs)
            finally:
                self.cpu[part] += time.process_time() - start
                self.count[part] += 1
                self.depth -= 1

        return timed


class Recorded:
    """A client that gives the recorded replies of the runner arm, in order."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.count = 0

    def __call__(self, prompt: str) -> str:
        self.count += 1
        path = self.folder / f"{self.count:04}.json"
        if not path.is_file():
            raise SystemExit(f"no recorded call {path}; this script makes no model call")
        entry = _json(_read(path))
        if entry.get("prompt_sha256") != digest(prompt.encode()):
            raise SystemExit(f"the prompt differs from its record: {path}")
        if entry.get("status") != "ok":
            raise RuntimeError(entry.get("status"))
        return cast(str, entry["reply"])


def live(folder: Path) -> Json | None:
    """The live wall time and model time of one document, from the cache file times.

    The runner publishes ``NNNN.pending.json`` before a call and ``NNNN.json`` after its reply.
    The live wall time starts at the first reservation and stops at ``result.json``."""
    calls = sorted(p for p in (folder / "calls").glob("*.json") if ".pending." not in p.name)
    if not calls:
        return None
    model = 0.0
    for path in calls:
        reserved = path.with_name(path.name.replace(".json", ".pending.json"))
        model += path.stat().st_mtime - reserved.stat().st_mtime
    first = (folder / "calls" / "0001.pending.json").stat().st_mtime
    wall = (folder / "result.json").stat().st_mtime - first
    return {"calls": len(calls), "wall_s": wall, "model_s": model}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("set", type=Path, help="the set folder, such as bench/requested3")
    ap.add_argument("sources", type=Path, help="the folder of the reader texts")
    ap.add_argument("config", type=Path, help="the frozen run configuration")
    ap.add_argument("cache", type=Path, help="the binding folder of the call cache")
    ap.add_argument(
        "--arm", choices=["runner", "runner_drop_rounded"], default="runner_drop_rounded"
    )
    ap.add_argument("--split", default="heldout")
    ap.add_argument("--json", type=Path, help="write the numbers of each document here")
    a = ap.parse_args()

    manifest = _json(_read(a.set / "manifest.json"))
    config = _json(_read(a.config))
    settings = _settings(config["run_policy"])
    policy = gg.Policy.from_dict(config["policy"]).to_dict()
    # FrozenSet.schema needs only the manifest and the settings. A full FrozenSet also pins the
    # code digest of the freeze, which a later version string changes.
    frozen = cast(FrozenSet, SimpleNamespace(manifest=manifest, settings=settings))
    recorded = a.cache / "runner" / a.split
    published = a.cache / a.arm / a.split

    clock = Clock()
    runner_module.admit = clock.wrap("admit", runner_module.admit)  # type: ignore[assignment]
    engine = cast(Any, runner_module._Engine)
    engine.search = clock.wrap("search", engine.search)
    verify = clock.wrap("verify", gg.verify)

    rows = []
    for doc in sorted(manifest["documents"], key=lambda d: d["id"]):
        if doc["split"] != a.split:
            continue
        ident = doc["id"]
        raw = _read(a.sources / f"{ident}.txt")
        if digest(raw) != doc["text_sha256"]:
            raise SystemExit("reader text digest differs: " + ident)
        text = raw.decode("utf-8")
        schema = FrozenSet.schema(frozen, doc)
        client = Recorded(recorded / ident / "calls")
        before = dict(clock.cpu)
        wall = time.perf_counter()
        cpu = time.process_time()
        result = extract(
            text,
            schema,
            client=client,
            model_id=config["model_id"],
            policy=policy,
            run_policy=RunPolicy(**settings, drop_rounded=a.arm == "runner_drop_rounded"),
            document_id=ident,
            document_source=doc["source"],
        )
        check = verify(
            result.receipt.to_dict(),
            text,
            schema,
            result.candidates,
            policy,
            document_source=doc["source"],
        )
        run_cpu = time.process_time() - cpu
        run_wall = time.perf_counter() - wall
        if not check.ok:
            raise SystemExit(f"the receipt does not verify: {ident} {check.problems[:3]}")
        main_result = _json(_read(recorded / ident / "result.json"))
        if _prompts(main_result) != _prompts({"record": result.record}):
            raise SystemExit("the replay calls differ from the runner record: " + ident)
        if (published / ident / "result.json").is_file():
            arm_result = _json(_read(published / ident / "result.json"))
            if arm_result["receipt"] != result.receipt.to_dict():
                raise SystemExit("the receipt differs from the published arm: " + ident)
        part = {p: clock.cpu[p] - before.get(p, 0.0) for p in PARTS}
        rows.append(
            {
                "id": ident,
                "kind": doc["kind"],
                "text_chars": len(text),
                "text_bytes": len(raw),
                "calls": client.count,
                "replay_wall_s": run_wall,
                "replay_cpu_s": run_cpu,
                **{f"{p}_cpu_s": part[p] for p in PARTS},
                "core_cpu_s": sum(part.values()),
                "live": live(recorded / ident),
            }
        )

    report(rows, a.arm, clock)
    if a.json:
        a.json.write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")


def report(rows: list[Json], arm: str, clock: Clock) -> None:
    def total(key: str, kind: str | None = None) -> float:
        return sum(r[key] for r in rows if kind in (None, r["kind"]))

    print(f"arm {arm}: {len(rows)} documents, Python {platform.python_version()}")
    print(f"calls of each part: {dict(clock.count)}")
    print()
    head = "kind", "docs", "MB text", "admit s", "search s", "verify s", "core s", "replay wall s"
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for kind in [*sorted({r["kind"] for r in rows}), None]:
        n = sum(1 for r in rows if kind in (None, r["kind"]))
        cells = [
            kind or "all",
            str(n),
            f"{total('text_bytes', kind) / 1e6:.2f}",
            *(f"{total(f'{p}_cpu_s', kind):.2f}" for p in PARTS),
            f"{total('core_cpu_s', kind):.2f}",
            f"{total('replay_wall_s', kind):.2f}",
        ]
        print("| " + " | ".join(cells) + " |")

    with_live = [r for r in rows if r["live"]]
    core = sum(r["core_cpu_s"] for r in with_live)
    wall = sum(r["live"]["wall_s"] for r in with_live)
    model = sum(r["live"]["model_s"] for r in with_live)
    replay_core = total("core_cpu_s")
    replay_wall = total("replay_wall_s")
    print()
    replay_cpu = total("replay_cpu_s")
    print(f"replay: core CPU {replay_core:.2f} s of {replay_wall:.2f} s wall")
    print(
        f"replay: CPU {replay_cpu:.2f} s, of which the runner outside the core "
        f"{replay_cpu - replay_core:.2f} s"
    )
    print(
        f"live runner: {len(with_live)} documents with calls, "
        f"wall {wall:.0f} s, model {model:.0f} s"
    )
    print(f"share of the core in the live wall time: {100 * core / wall:.3f}%")
    print(f"share of the model calls in the live wall time: {100 * model / wall:.2f}%")
    shares = sorted(100 * r["core_cpu_s"] / r["live"]["wall_s"] for r in with_live)
    print(f"largest share of one document: {shares[-1]:.3f}%")
    print()
    print("documents with the most core CPU time:")
    for r in sorted(rows, key=lambda r: -r["core_cpu_s"])[:5]:
        live_wall = r["live"]["wall_s"] if r["live"] else 0.0
        print(
            f"  {r['id']}: {r['text_bytes'] / 1e6:.2f} MB, {r['calls']} calls, "
            f"core {r['core_cpu_s']:.2f} s (admit {r['admit_cpu_s']:.2f}, search "
            f"{r['search_cpu_s']:.2f}, verify {r['verify_cpu_s']:.2f}), live wall {live_wall:.0f} s"
        )


if __name__ == "__main__":
    sys.exit(main())
