"""Run the two sealed splits with one recorded reply per part.

``--set DIR`` runs another set folder of the family, for example ``bench/regulatory2``. Its
``members.json`` gives the split counts. A set with only held-out parts names a calibration
set there: the calibration and the freeze then use the calibration parts and labels of that
set, and the freeze goes into the manifest of DIR.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import groundgate as gg
from groundgate.calibrate.measure import Gold, GoldDoc, measure
from groundgate.model import PacketError, normal_date
from groundgate.profile import profile_digest

from ..judges.codex import judge
from ..requested.run_set import (
    _Calls,
    _external,
    _json,
    _publish,
    _read,
    _same_or_publish,
    digest,
    encoded,
    source_code_digest,
)
from . import extract, score
from .slots import FIELDS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
Json = extract.Json
Client = Callable[[str], str]
MAX_PROMPT = 512_000
MAX_INPUT = 16 << 20
SHA = re.compile(r"sha256:[0-9a-f]{64}")
PART = re.compile(r"cfr-[0-9]+-[0-9]+")
SPLITS = {"calibration": 5, "heldout": 9}


class Codex(judge.Codex):
    def command(self) -> list[str]:
        cmd = super().command()[:-1]
        for feature in (
            "shell_tool", "unified_exec", "multi_agent", "multi_agent_v2",
            "plugins", "skill_search", "image_generation", "view_image", "sleep_tool",
        ):  # fmt: skip
            cmd += ["--disable", feature]
        return [*cmd, "-"]


def code_digest() -> str:
    return digest(encoded({
        "core_and_cache": source_code_digest(),
        "transport": digest(_read(Path(judge.__file__))),
        "regulatory": {
            name: digest(_read(HERE / name))
            for name in ("run.py", "extract.py", "score.py", "slots.py")
        },
    }))  # fmt: skip


def atomic_text(path: Path, body: str, *, replace: bool = False) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(tmp, path)
        else:
            os.link(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


@dataclass(frozen=True)
class SetConfig:
    splits: dict[str, int]
    calibration: Path | None
    intro: str | None


def set_config(directory: Path) -> SetConfig:
    """The split counts, the calibration set and the report intro of a set folder."""
    path = directory / "members.json"
    if not path.exists():
        return SetConfig(SPLITS, None, None)
    body = _json(_read(path))
    splits = body.get("splits")
    if (
        body.get("format") != "regulatory-members/1"
        or not isinstance(splits, dict)
        or not splits
        or not set(splits) <= set(SPLITS)
        or any(type(n) is not int or n < 0 for n in splits.values())
    ):
        raise ValueError("the member list of the set is not valid")
    name = body.get("calibration_set")
    if name is None:
        if not splits.get("calibration"):
            raise ValueError("the set needs calibration parts or a calibration set")
        return SetConfig(splits, None, body.get("report_intro"))
    calibration = (ROOT / str(name)).resolve()
    if splits.get("calibration") or calibration == directory.resolve():
        raise ValueError("a set with a calibration set has only held-out parts")
    return SetConfig(splits, calibration, body.get("report_intro"))


@dataclass
class Part:
    id: str
    text: str
    slots: list[Json]
    views: dict[str, extract.Section]
    prompt: str


class Benchmark:
    settings: ClassVar = {"max_calls": 1, "max_prompt_chars": MAX_PROMPT}

    def __init__(self, directory: Path, sources: Path, cache: Path) -> None:
        self.directory = directory
        self.sources = _external(sources, ROOT)
        self.cache = _external(cache, ROOT)
        self.manifest_raw = _read(directory / "manifest.json")
        self.slots_raw = _read(directory / "slots.json")
        self.manifest = _json(self.manifest_raw)
        self.requests = _json(self.slots_raw)
        self.code = code_digest()
        config = set_config(directory)
        self.splits = config.splits
        self.calibration_set: Benchmark | None = None
        if config.calibration is not None:
            self.calibration_set = Benchmark(config.calibration, sources, cache)
            if self.calibration_set.calibration_set is not None:
                raise ValueError("the calibration set names a calibration set")
            if self.calibration_set.requests["schema"] != self.requests["schema"]:
                raise ValueError("the schema differs from the calibration set")
        body, request = self.manifest, self.requests
        seal = body.get("labels", {})
        if (
            not body.get("selection_complete")
            or seal.get("file") != "labels.json"
            or normal_date(seal.get("sealed")) is None
            or not SHA.fullmatch(seal.get("sha256", ""))
        ):
            raise ValueError("the set needs a sealed label file and a complete selection")
        if (
            body["slots"]["sha256"] != digest(self.slots_raw)
            or request["seed"] != body["split_rule"]["seed"]
            or request["format"] != "regulatory-slots/1"
        ):
            raise ValueError("the slot file differs from its pin")
        self.members = {d["id"]: d for d in body["documents"]}
        self.slots: dict[str, list[Json]] = defaultdict(list)
        ids = set()
        for s in request["slots"]:
            d = self.members.get(s["id"], {})
            if (
                s["slot"] in ids
                or s["split"] != d.get("split")
                or s["field"] not in FIELDS
                or s["kind"] != FIELDS[s["field"]][0]
            ):
                raise ValueError("a slot differs from the frozen split or schema")
            if s["kind"] == "record" and not 0 < len(s["request"]["columns"]) <= extract.COLUMNS:
                raise ValueError("a request has too many or too few columns")
            self.slots[s["id"]].append(s)
            ids.add(s["slot"])
        if (
            len(self.members) != len(body["documents"])
            or self.members.keys() != self.slots.keys()
            or any(
                not PART.fullmatch(d["id"])
                or d["split"] not in self.splits
                or d["selection_status"] != "frozen_member"
                for d in self.members.values()
            )
            or len(ids) != body["slots"]["count"]
            or any(
                sum(d["split"] == split for d in self.members.values()) != count
                or sum(s["split"] == split for s in request["slots"]) != body["slots"][split]
                for split, count in self.splits.items()
            )
        ):
            raise ValueError("the members or slots differ from the frozen split")
        self.unfrozen = digest(encoded({k: v for k, v in body.items() if k != "freeze"}))
        if self.calibration_set is not None and self.members.keys() & self.calibration_set.members:
            raise ValueError("a part is in the set and in its calibration set")

    def calibration_source(self) -> Benchmark:
        """The set whose calibration parts and labels make the profile of this set."""
        return self.calibration_set or self

    def check_inputs(self) -> None:
        if (
            self.manifest_raw != _read(self.directory / "manifest.json")
            or self.slots_raw != _read(self.directory / "slots.json")
            or self.code != code_digest()
        ):
            raise ValueError("the run inputs changed")
        if self.calibration_set is not None:
            self.calibration_set.check_inputs()

    def prepare(self, split: str) -> list[Part]:
        parts = []
        for name, d in self.members.items():
            if d["split"] != split:
                continue
            raw = _read(self.sources / f"{name}.xml", MAX_INPUT)
            text = _read(self.sources / f"{name}.txt", MAX_INPUT)
            if len(raw) != d["source_bytes"] or digest(raw) != d["source_sha256"]:
                raise ValueError(f"{name}: XML differs from its pin")
            if digest(text) != d["text_sha256"]:
                raise ValueError(f"{name}: reader text differs from its pin")
            text = text.decode("utf-8")
            slots = self.slots[name]
            views = extract.section_views(text, raw, slots)
            prompt = extract.prompt(d["citation"], slots, self.requests["schema"], views)
            if len(prompt) > MAX_PROMPT:
                raise ValueError(f"{name}: prompt exceeds the character limit")
            parts.append(Part(name, text, slots, views, prompt))
        return parts

    def record(self, split: str, parts: list[Part], transport: Json, profile: Json) -> Json:
        record = {
            "format": "regulatory-run/1",
            "split": split,
            "code_sha256": self.code,
            "set_sha256": self.unfrozen,
            "slots_sha256": digest(self.slots_raw),
            "labels_sha256": self.manifest["labels"]["sha256"],
            "profile_sha256": profile_digest(profile),
            "transport": transport,
            "documents": [{"id": p.id, "prompt_sha256": digest(p.prompt.encode())} for p in parts],
        }
        if self.calibration_set is not None:
            record["calibration_set"] = self.calibration_identity()
        return record

    def calibration_identity(self) -> Json | None:
        """The digests of the calibration set, or None for a set with its own calibration."""
        other = self.calibration_set
        if other is None:
            return None
        return {
            "set_sha256": other.unfrozen,
            "slots_sha256": digest(other.slots_raw),
            "labels_sha256": other.manifest["labels"]["sha256"],
        }

    def collect(
        self, split: str, parts: list[Part], record: Json, client: Client | None
    ) -> dict[str, Json]:
        root = self.cache / split
        _same_or_publish(root / "run.json", record, replay_only=client is None)
        binding = digest(encoded(record))
        replies = {}
        for p in parts:
            calls = _Calls(self, root / p.id, binding, client)
            reply = calls(p.prompt)
            calls.finish()
            replies[p.id] = parse_reply(reply, p.slots)
        self.check_inputs()
        return replies

    def labels(self, slots: list[Json], *, calibration: bool) -> dict[str, Json]:
        seal = self.manifest["labels"]
        path = self.directory / seal["file"]
        if calibration:
            raw = calibration_labels(path, seal)
            rows = json.loads(b"[" + raw + b"]")
        else:
            raw = _read(path, MAX_INPUT)
            if digest(raw) != seal["sha256"]:
                raise ValueError("the label file differs from its seal")
            body = _json(raw)
            if body["format"] != "regulatory-labels/1":
                raise ValueError("unknown label format")
            rows = body["labels"]
        labels = {}
        wanted = {s["slot"]: s for s in slots}
        for row in rows:
            key = row["slot"]
            if not calibration and key not in wanted:
                continue
            slot = wanted.get(key)
            if (
                not slot
                or key in labels
                or any(row[k] != slot[k] for k in ("id", "field", "split"))
                or row["status"] not in ("value", "absent")
                or (row["status"] == "absent") != (row["value"] is None)
            ):
                raise ValueError(f"{key}: label differs from the sealed slots")
            labels[key] = row
        if labels.keys() != wanted.keys():
            raise ValueError("sealed labels are missing")
        return labels

    def frozen(self) -> tuple[Json, Json]:
        freeze = self.manifest.get("freeze")
        if not isinstance(freeze, dict) or freeze.get("format") != "regulatory-freeze/1":
            raise ValueError("the held-out freeze is missing")
        if freeze.get("code_sha256") != self.code:
            raise ValueError("the code digest differs from the freeze")
        profile = freeze.get("profile")
        if not isinstance(profile, dict) or profile_digest(profile) != freeze.get("profile_sha256"):
            raise ValueError("the profile digest differs from the freeze")
        if freeze.get("set_sha256") != self.unfrozen:
            raise ValueError("the set digest differs from the freeze")
        if freeze.get("calibration_set") != self.calibration_identity():
            raise ValueError("the calibration set differs from the freeze")
        return freeze, profile

    def calibrate(self, transport: Json, client: Client) -> None:
        if "freeze" in self.manifest:
            raise ValueError("the family is already frozen")
        parts = self.calibration_source().prepare("calibration")
        profile = extract.base_profile(self.requests["schema"])
        record = self.record("calibration", parts, transport, profile)
        self.collect("calibration", parts, record, client)

    def freeze(self, date: str) -> None:
        if "freeze" in self.manifest:
            raise ValueError("the family is already frozen")
        source = self.calibration_source()
        parts = source.prepare("calibration")
        profile = extract.base_profile(self.requests["schema"])
        saved = _json(_read(self.cache / "calibration" / "run.json"))
        record = self.record("calibration", parts, saved["transport"], profile)
        replies = self.collect("calibration", parts, record, None)
        outputs, proposals = admit(parts, replies, profile)
        slots = [s for p in parts for s in p.slots]
        labels = source.labels(slots, calibration=True)
        gold = calibration_gold(parts, proposals, labels)
        # Measure uses "test" for the packets it scores. These are all claim calibration parts.
        split = {p.id: "test" for p in parts}
        split_sha = digest(b"groundgate-split/1:" + encoded({
            "groundgate_split": 1, "documents": split,
        }))  # fmt: skip
        report, draft = measure(profile, gold, split, split_sha, Decimal("0.05"), date)
        local = self.cache / "calibration" / "measure.json"
        _same_or_publish(local, {"measure": report, "score": score.score(slots, labels, outputs)})
        body = self.manifest | {"freeze": {
            "format": "regulatory-freeze/1",
            "date": date,
            "set_sha256": self.unfrozen,
            "code_sha256": self.code,
            "profile_sha256": profile_digest(draft),
            "profile": draft,
            "transport": record["transport"],
            "calibration_run_sha256": digest(encoded(record)),
            "calibration_measure_sha256": digest(_read(local)),
        }}  # fmt: skip
        if self.calibration_set is not None:
            body["freeze"]["calibration_set"] = self.calibration_identity()
        self.check_inputs()
        atomic_text(
            self.directory / "manifest.json",
            json.dumps(body, indent=1, ensure_ascii=False) + "\n",
            replace=True,
        )

    def check_heldout(self) -> tuple[Json, Json]:
        freeze, profile = self.frozen()
        results_path = self.directory / "results.json"
        if results_path.exists() or results_path.is_symlink():
            raise ValueError("the held-out result already exists")
        return freeze, profile

    def heldout(self, transport: Json, client: Client) -> None:
        freeze, profile = self.check_heldout()
        if transport != freeze["transport"]:
            raise ValueError("the transport differs from the freeze")
        parts = self.prepare("heldout")
        record = self.record("heldout", parts, transport, profile)
        self.check_inputs()
        # A cache has one identity. A second cache cannot start another held-out run.
        identity = self.cache / "heldout" / "identity.json"
        with suppress(FileExistsError):
            _publish(identity, {"id": uuid.uuid4().hex})
        run = record | {"cache_id": _json(_read(identity))["id"]}
        _same_or_publish(self.directory / "heldout-run.json", run)
        replies = self.collect("heldout", parts, run, client)
        outputs, _ = admit(parts, replies, profile)
        slots = [s for p in parts for s in p.slots]
        labels = self.labels(slots, calibration=False)
        results = {"format": "regulatory-results/1", "run": run} | score.score(
            slots, labels, outputs
        )
        self.check_inputs()
        _publish(self.directory / "results.json", results)
        render(self.directory)


def parse_reply(reply: str, slots: list[Json]) -> Json:
    reply = reply.strip()
    if reply.startswith("```") and reply.endswith("```"):
        reply = reply.partition("\n")[2][:-3]
    try:
        body = _json(reply.encode())
    except (ValueError, RecursionError):
        return {}
    rows = body.get("slots")
    if (
        set(body) != {"slots"}
        or not isinstance(rows, list)
        or any(not isinstance(r, dict) or not isinstance(r.get("slot"), str) for r in rows)
    ):
        return {}
    answers = {r["slot"]: r for r in rows}
    if len(rows) != len(answers) or not answers.keys() <= {s["slot"] for s in slots}:
        return {}
    return answers


def calibration_labels(path: Path, seal: Json) -> bytes:
    """Seek only to the pinned calibration rows. The full seal is for held-out scoring."""
    chunks = []
    previous = 0
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT:
        raise ValueError("missing, linked or oversized label file")
    with path.open("rb", buffering=0) as stream:
        for start, end in seal["calibration_ranges"]:
            if not previous <= start < end <= MAX_INPUT:
                raise ValueError("invalid calibration label range")
            stream.seek(start)
            chunks.append(stream.read(end - start))
            previous = end
    raw = b",".join(chunks)
    if digest(raw) != seal["calibration_sha256"]:
        raise ValueError("calibration labels differ from their pin")
    return raw


def admit(
    parts: list[Part], replies: dict[str, Json], profile: Json
) -> tuple[dict[str, score.Answer], dict[str, dict[str, list[Json]]]]:
    outputs = {}
    proposals = {}
    for part in parts:
        scalars = {}
        number = 0
        for slot in part.slots:
            key, kind = slot["slot"], slot["kind"]
            view = part.views[slot["request"]["section"]]
            answer = replies[part.id].get(key, {})
            number += kind == "number"
            if kind == "record":
                outputs[key] = admit_table(part.id, slot, answer, view.tables[key], profile)
                continue
            try:
                items = extract.candidates(slot, answer, view, number)
            except extract.ReplyError:
                outputs[key] = score.Answer(invalid=True)
                items = []
            if kind in ("number", "date"):
                scalars[key] = items
                continue
            outputs.setdefault(key, score.Answer())
            if not items:
                continue
            receipt = gg.admit(
                view.text, None, items, document_id=part.id, profile=profile, outline=view.outline
            )
            d = receipt.decisions[0]
            value = None
            if d.outcome == "admitted" and d.evidence is not None:
                value = extract.passage_value(view, d.evidence)
            outputs[key] = score.Answer(d.outcome, value)
        receipt = gg.admit(
            part.text, None, [c for cs in scalars.values() for c in cs],
            document_id=part.id, profile=profile,
        )  # fmt: skip
        for key in scalars:
            outputs.setdefault(key, score.Answer())
        outputs.update({d.candidate_id: score.Answer(d.outcome, d.value, d.unit)
                        for d in receipt.decisions})  # fmt: skip
        proposals[part.id] = scalars
    return outputs, proposals


def admit_table(
    document_id: str, slot: Json, answer: Json, table: extract.Table | None, profile: Json
) -> score.Answer:
    if table is None:
        return score.Answer("needs_verification")
    try:
        items = extract.record_candidates(slot, answer, table)
    except extract.ReplyError:
        return score.Answer(invalid=True)
    if items is None:
        return score.Answer("needs_verification")
    packets = [items]
    if table.spans_rows:
        # Keep evidence that spans rows from confirming a value in another record.
        by_record: dict[str, list[Json]] = defaultdict(list)
        for item in items:
            by_record[item["record"]].append(item)
        packets = list(by_record.values())
    rows = {}
    for packet in packets:
        receipt = gg.admit(table.text, None, packet, document_id=document_id, profile=profile)
        rows.update({row.record: row for row in receipt.records or ()})
    order = [str(i) for i in range(1, len(table.rows) + 1)]
    if any(n not in rows or rows[n].outcome != "admitted" for n in order):
        return score.Answer("needs_verification")
    columns = slot["request"]["columns"]
    value = []
    for n in order:
        members = dict(rows[n].members)
        value.append({name: members[extract.column(c)] for c, name in enumerate(columns)})
    return score.Answer("admitted", value)


def calibration_gold(
    parts: list[Part], proposals: dict[str, dict[str, list[Json]]], labels: dict[str, Json]
) -> Gold:
    """The package measure accepts scalar labels. The family scorer handles whole values."""
    docs, files, gold_labels = {}, {}, {}
    for p in parts:
        candidates, values = [], {}
        number = 0
        for slot in p.slots:
            key, kind = slot["slot"], slot["kind"]
            if key not in proposals[p.id]:
                continue
            items = proposals[p.id][key]
            label = labels[key]
            field = slot["field"]
            if kind == "number":
                number += 1
                field = extract.number_field(number, extract.unit_code(label["unit"]))
            values[field] = label["value"]
            for c in items:
                # A proposal in another unit is wrong, even when its magnitude is right.
                values.setdefault(c["field"], None)
                candidates.append(c)
        docs[p.id] = GoldDoc(p.id, p.text, candidates, None, values)
        files[p.id] = {
            "text": digest(p.text.encode()),
            "candidates": digest(encoded(candidates)),
            "judgments": None,
        }
        gold_labels[p.id] = values
    sha = digest(b"groundgate-gold/1:" + encoded({
        "groundgate_gold": 1, "files": files, "labels": gold_labels,
    }))  # fmt: skip
    return Gold(docs, sha)


def render(directory: Path) -> None:
    raw = _read(directory / "results.json")
    body = score.markdown(_json(raw), set_config(directory).intro)
    path = directory / "RESULTS.md"
    if path.exists():
        if _read(path) != body.encode():
            raise ValueError("the existing report differs from results.json")
    else:
        atomic_text(path, body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="step", required=True)
    for name in ("calibrate", "freeze", "heldout", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--set", type=Path, default=HERE, help="the set folder")
        if name == "report":
            continue
        cmd.add_argument("--sources", type=Path, required=True)
        cmd.add_argument("--cache", type=Path, required=True)
        if name == "freeze":
            cmd.add_argument("--date", type=normal_date, default=datetime.date.today().isoformat())
        else:
            cmd.add_argument("--model", required=True)
            cmd.add_argument("--effort", required=True, choices=judge.EFFORTS)
    args = parser.parse_args()
    try:
        if args.step == "report":
            render(args.set)
            return
        bench = Benchmark(args.set, args.sources, args.cache)
        if args.step == "freeze":
            if args.date is None:
                parser.error("--date must be a real YYYY-MM-DD date")
            bench.freeze(args.date)
            print("Wrote the family freeze to manifest.json.")
            return
        if args.step == "heldout":
            bench.check_heldout()
        bench.cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cli-", dir=bench.cache) as directory:
            client = Codex(args.model, args.effort, workdir=directory)
            transport = {
                "id": "codex-cli-exec",
                "model": args.model,
                "effort": args.effort,
                "version": client.version(),
            }
            if args.step == "calibrate":
                bench.calibrate(transport, client.call)
                print("Cached the calibration replies.")
            else:
                bench.heldout(transport, client.call)
                print("Wrote results.json and RESULTS.md.")
    except (ValueError, RuntimeError, OSError, PacketError, ET.ParseError, judge.JudgeError) as exc:
        parser.exit(1, f"regulatory run: {exc}\n")


if __name__ == "__main__":
    main()
