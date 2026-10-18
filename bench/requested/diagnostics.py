"""Paired decisions and observable layout diagnostics from sealed local caches.

No model, reader heuristic or primary requested-field score runs here. Companion packets must
already exist for explicitly declared keyed schemas. All source-bearing artifacts stay local.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import selectors
import subprocess
import time
import unicodedata
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

import groundgate as gg

from .metrics import measure
from .run_set import (
    CacheError,
    _json,
    _publish,
    _read,
    _unlinked,
    _validate_blind_labels,
    source_code_digest,
)

Json = dict[str, Any]
_MAX = 16 * 1024 * 1024
_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}\Z")
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_ROUTES = {"empty_cells", "ambiguous_columns", "running_heads"}


class DiagnosticError(ValueError):
    """A diagnostic input, pinned worker or immutable cache is invalid."""


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return gg.jcs(value).encode("utf-8")


def core_digest(spec: str, kind: str, value: Any) -> str:
    return digest(f"groundgate/{spec}:{kind}\0".encode() + encoded(value))


def file_digest(path: Path, cap: int = 128 * 1024 * 1024) -> str:
    if not path.is_file() or path.stat().st_size > cap:
        raise DiagnosticError("missing or oversized diagnostic file")
    result = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            size += len(chunk)
            if size > cap:
                raise DiagnosticError("diagnostic file grew beyond cap")
            result.update(chunk)
    return "sha256:" + result.hexdigest()


def _object(value: Any, keys: set[str]) -> Json:
    if not isinstance(value, dict) or set(value) != keys:
        raise DiagnosticError("unknown or missing diagnostic member")
    return value


def _ident(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise DiagnosticError("unsafe diagnostic identifier")
    return value


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise DiagnosticError("invalid diagnostic digest")
    return value


def _load(path: Path, expected: str, cap: int = _MAX) -> Json:
    try:
        raw = _read(_unlinked(path), cap)
        if digest(raw) != _sha(expected):
            raise DiagnosticError("diagnostic file digest differs")
        return _json(raw)
    except (CacheError, OSError, TypeError, UnicodeError, RecursionError) as exc:
        raise DiagnosticError("invalid diagnostic file") from exc


def _child(root: Path, name: Any) -> Path:
    if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
        raise DiagnosticError("diagnostic path escapes its input root")
    path = _unlinked(root / name)
    if root not in path.parents:
        raise DiagnosticError("diagnostic path escapes its input root")
    return path


def _same(path: Path, value: Json, replay: bool) -> None:
    _unlinked(path)
    if path.exists():
        if _read(path, _MAX) != encoded(value):
            raise DiagnosticError("immutable diagnostic cache differs")
    elif replay:
        raise DiagnosticError("missing diagnostic replay artifact")
    else:
        _publish(path, value)


def _span(raw: bytes, start: Any, end: Any, empty: bool = False) -> None:
    if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(raw):
        raise DiagnosticError("invalid diagnostic byte span")
    if start == end and not empty:
        raise DiagnosticError("empty diagnostic word span")
    if any(pos < len(raw) and (raw[pos] & 0xC0) == 0x80 for pos in (start, end)):
        raise DiagnosticError("diagnostic offset splits UTF-8")


def serialized_layout(text: str, layout: Json) -> Json:
    """Parse only actual emitted delimiters and join exact existing Word ranges/boxes."""
    if not isinstance(text, str) or len(text.encode()) > _MAX:
        raise DiagnosticError("oversized layout text")
    _object(layout, {"groundgate_layout", "document_sha256", "pages", "words"})
    if layout["groundgate_layout"] != "0.1" or layout["document_sha256"] not in {
        core_digest(spec, "document", {"text": text}) for spec in ("0.8", "0.9")
    }:
        raise DiagnosticError("layout text digest differs")
    raw = text.encode()
    if raw.count(b"\n") > 200000 or raw.count(b"\t") > 200000:
        raise DiagnosticError("serialized row/cell cap")
    if not isinstance(layout["pages"], list) or not isinstance(layout["words"], list):
        raise DiagnosticError("invalid layout arrays")
    if len(layout["pages"]) > 10000 or len(layout["words"]) > 200000:
        raise DiagnosticError("layout processing cap")
    pages, rows, words = {}, [], []
    prior = 0
    for p in layout["pages"]:
        _object(p, {"page", "width", "height", "start", "end"})
        if type(p["page"]) is not int or p["page"] < 1 or p["page"] in pages:
            raise DiagnosticError("invalid layout page")
        if any(
            type(p[n]) not in {int, float} or not math.isfinite(p[n]) or p[n] <= 0
            for n in ("width", "height")
        ):
            raise DiagnosticError("invalid page dimensions")
        _span(raw, p["start"], p["end"], True)
        if p["start"] < prior or (pages and raw[prior : p["start"]] != b"\n\f"):
            raise DiagnosticError("page delimiter or order differs")
        prior = p["end"]
        pages[p["page"]] = p
    if pages and (next(iter(pages.values()))["start"] != 0 or prior != len(raw)):
        raise DiagnosticError("layout does not cover emitted text")
    prior = 0
    for item in layout["words"]:
        if not isinstance(item, list) or len(item) != 7:
            raise DiagnosticError("invalid layout word")
        start, end, page, *box = item
        _span(raw, start, end)
        if start < prior or page not in pages:
            raise DiagnosticError("word order or page differs")
        p = pages[page]
        if not p["start"] <= start < end <= p["end"]:
            raise DiagnosticError("word outside its page")
        if any(type(x) not in {int, float} or not math.isfinite(x) for x in box):
            raise DiagnosticError("invalid word geometry")
        if not 0 <= box[0] <= box[2] <= p["width"] or not 0 <= box[1] <= box[3] <= p["height"]:
            raise DiagnosticError("word geometry outside page")
        words.append({"start": start, "end": end, "page": page, "box": box})
        prior = end
    # Each row/cell is a byte span in actual output, not an inferred table classification.
    wi, cell_count = 0, 0
    for page, p in pages.items():
        offset, block, row_number = p["start"], 0, 0
        for line in raw[p["start"] : p["end"]].split(b"\n"):
            if not line:
                block += 1
                offset += 1
                continue
            cells, pos = [], offset
            for column, cell in enumerate(line.split(b"\t")):
                cell_count += 1
                if cell_count > 200000:
                    raise DiagnosticError("serialized cell cap")
                cells.append(
                    {
                        "column": column,
                        "start": pos,
                        "end": pos + len(cell),
                        "empty": not cell,
                        "words": [],
                    }
                )
                pos += len(cell) + 1
            row = {
                "page": page,
                "block": block,
                "row": row_number,
                "start": offset,
                "end": offset + len(line),
                "cells": cells,
            }
            ci = 0
            while wi < len(words) and words[wi]["start"] < row["end"]:
                w = words[wi]
                while ci < len(cells) and cells[ci]["end"] <= w["start"]:
                    ci += 1
                if (
                    w["page"] != page
                    or ci == len(cells)
                    or not cells[ci]["start"] <= w["start"] < w["end"] <= cells[ci]["end"]
                ):
                    raise DiagnosticError("word cannot join an emitted cell")
                cells[ci]["words"].append(w)
                wi += 1
            rows.append(row)
            if len(rows) > 200000:
                raise DiagnosticError("layout row cap")
            row_number += 1
            offset += len(line) + 1
    if wi != len(words):
        raise DiagnosticError("unjoined layout word")
    return {"rows": rows, "pages": list(pages), "text_sha256": digest(raw)}


def score_layout(annotations: list[Json], observations: list[Json]) -> Json:
    """Score only blind geometry anchors that join an actual serialized observation."""
    if not annotations:
        return {
            "status": "unassessed",
            "routes": {},
            "limitations": ["No sealed layout annotations supplied."],
        }
    routes: dict[str, Any] = {}
    work = 0

    def joins(obs: Json, page: int, box: list[float]) -> list[tuple[Json, Json]]:
        nonlocal work
        matches = []
        for emitted in obs["trace"]["rows"]:
            work += 1 + sum(len(cell["words"]) for cell in emitted["cells"])
            if work > 20_000_000:
                raise DiagnosticError("layout geometry work cap")
            if emitted["page"] != page:
                continue
            for cell in emitted["cells"]:
                if any(
                    min(w["box"][2], box[2]) > max(w["box"][0], box[0])
                    and min(w["box"][3], box[3]) > max(w["box"][1], box[1])
                    for w in cell["words"]
                ):
                    matches.append((emitted, cell))
        return matches

    for doc in annotations:
        for route in doc["routes"]:
            name = route["route"]
            if name not in _ROUTES:
                raise DiagnosticError("unknown layout route")
            for obs in observations:
                if obs["document"] != doc["id"]:
                    continue
                k = "/".join(x for x in (obs.get("kind"), obs["reader"], name) if x)
                row = routes.setdefault(
                    k,
                    {
                        "evaluated": 0,
                        "correct": 0,
                        "unclear": 0,
                        "unassessed": 0,
                        "not_applicable": 0,
                        "reviewed_pages": 0,
                        "unreviewed_pages": 0,
                        "partial_documents": 0,
                    },
                )
                row["reviewed_pages"] += len(doc["reviewed_pages"])
                row["unreviewed_pages"] += doc["source_pages"] - len(doc["reviewed_pages"])
                row["partial_documents"] += not doc["complete"]
                if route["assessment"] == "not_applicable":
                    if not doc["complete"] or route["cases"]:
                        raise DiagnosticError("not-applicable needs complete blind coverage")
                    row["not_applicable"] += 1
                elif route["assessment"] == "unassessed":
                    if route["cases"]:
                        raise DiagnosticError("unassessed route cannot have scored cases")
                    row["unassessed"] += 1
                elif route["assessment"] != "applicable" or not route["cases"]:
                    raise DiagnosticError("applicable layout needs real cases")
                for case in route["cases"]:
                    if case["state"] == "unclear":
                        row["unclear"] += 1
                        continue
                    if case["state"] != "observed":
                        row["unassessed"] += 1
                        continue
                    matches = joins(obs, case["page"], case["box"])
                    if len(matches) != 1:
                        row["unassessed"] += 1
                        continue
                    emitted, cell = matches[0]
                    if name == "empty_cells":
                        column = case["expected"]
                        actual = (
                            emitted["cells"][column]["empty"]
                            if column < len(emitted["cells"])
                            else None
                        )
                        correct = actual is True
                    elif name == "ambiguous_columns":
                        correct = cell["column"] == case["expected"]
                    else:
                        target = case["target"]
                        targets = joins(obs, target["page"], target["box"])
                        if len(targets) != 1:
                            row["unassessed"] += 1
                            continue
                        target_row, _ = targets[0]
                        associated = (emitted["page"], emitted["block"]) == (
                            target_row["page"],
                            target_row["block"],
                        )
                        correct = associated == case["expected"]
                    row["evaluated"] += 1
                    row["correct"] += correct
    for row in routes.values():
        row["rate"] = row["correct"] / row["evaluated"] if row["evaluated"] else None
    coverage = [
        {
            "document": doc["id"],
            "reviewed_pages": len(doc["reviewed_pages"]),
            "unreviewed_pages": doc["source_pages"] - len(doc["reviewed_pages"]),
            "complete": doc["complete"],
        }
        for doc in annotations
    ]
    return {
        "status": "assessed" if routes else "unassessed",
        "routes": routes,
        "coverage": coverage,
        "missing_observations": sorted(
            {doc["id"] for doc in annotations} - {obs["document"] for obs in observations}
        ),
        "limitations": [
            "Only exact emitted spans/geometry joins are assessed; missing joins are unassessed.",
            "Running heads compare page/block association with a separately anchored target row.",
            "Views and repeated source pages are correlated, not independent trials.",
        ],
    }


class DiagnosticSession:
    """Validate a frozen execution bundle before any isolated decision worker is called."""

    def __init__(
        self,
        plan: Path,
        directory: Path,
        sources: Path,
        inputs: Path,
        cache: Path,
        *,
        plan_sha256: str,
    ):
        try:
            self.plan_path = _unlinked(plan.absolute())
            self.sources, self.inputs, self.cache = (
                _unlinked(p.absolute()) for p in (sources, inputs, cache)
            )
            repository = Path(__file__).resolve().parents[2]
            if any(
                p == repository or repository in p.parents
                for p in (self.sources, self.inputs, self.cache)
            ):
                raise DiagnosticError("diagnostic source/cache storage must be external")
            self.plan = _load(self.plan_path, plan_sha256, 1024 * 1024)
            _object(
                self.plan,
                {
                    "format",
                    "status",
                    "split",
                    "manifest_sha256",
                    "labels_sha256",
                    "reader",
                    "versions",
                    "views",
                    "packets",
                    "layout",
                },
            )
            if (
                self.plan["format"] != "requested-diagnostics/1"
                or self.plan["status"] != "frozen"
                or self.plan["split"] not in {"development", "heldout"}
            ):
                raise DiagnosticError("diagnostic declaration must be frozen")
            directory = _unlinked(directory.absolute())
            self.paths = {
                self.plan_path: plan_sha256,
                directory / "manifest.json": self.plan["manifest_sha256"],
                directory / "labels.json": self.plan["labels_sha256"],
            }
            self.manifest = _load(directory / "manifest.json", self.plan["manifest_sha256"])
            self.labels = _load(directory / "labels.json", self.plan["labels_sha256"])
            if (
                self.manifest.get("status") != "frozen"
                or self.manifest.get("selection_complete") is not True
            ):
                raise DiagnosticError("primary manifest must be frozen and complete")
            _validate_blind_labels(self.manifest, self.labels)
            if len(self.manifest["documents"]) > 1024:
                raise DiagnosticError("document count cap")
            self.docs = {x["id"]: x for x in self.manifest["documents"]}
            self.gold = {x["id"]: x for x in self.labels["documents"]}
            self.texts = {}
            total = 0
            for ident, doc in self.docs.items():
                _ident(ident)
                for suffix, member, cap in (
                    ("pdf", "source_sha256", 128 * 1024 * 1024),
                    ("txt", "text_sha256", _MAX),
                ):
                    path = _child(self.sources, ident + "." + suffix)
                    if file_digest(path, cap) != _sha(doc[member]):
                        raise DiagnosticError("source or text digest differs")
                    self.paths[path] = doc[member]
                    if suffix == "pdf":
                        if (
                            type(doc.get("approved_max_bytes")) is not int
                            or path.stat().st_size != doc.get("source_bytes")
                            or path.stat().st_size > doc["approved_max_bytes"]
                        ):
                            raise DiagnosticError("source byte approval differs")
                    else:
                        text = _read(path, _MAX).decode("utf-8")
                        if unicodedata.normalize("NFC", text) != text:
                            raise DiagnosticError("diagnostic text must already be NFC")
                        total += path.stat().st_size
                        if total > 128 * 1024 * 1024:
                            raise DiagnosticError("diagnostic text total cap")
                        self.texts[ident] = text
            _object(self.plan["reader"], {"id", "commit", "code_sha256", "serializer"})
            if self.plan["reader"]["serializer"] != "pdf-delimiters/1":
                raise DiagnosticError("unknown reader serializer")
            _sha(self.plan["reader"]["code_sha256"])
            _ident(self.plan["reader"]["id"])
            if (
                not isinstance(self.plan["reader"]["commit"], str)
                or not self.plan["reader"]["commit"].strip()
            ):
                raise DiagnosticError("missing reader commit")
            if not isinstance(self.plan["versions"], list) or len(self.plan["versions"]) != 2:
                raise DiagnosticError("exactly two pinned versions required")
            for version in self.plan["versions"]:
                _object(
                    version,
                    {
                        "id",
                        "package_version",
                        "spec_version",
                        "code_sha256",
                        "python",
                        "python_sha256",
                        "commit",
                    },
                )
                _ident(version["id"])
                if version["spec_version"] == "0.8" and version["package_version"] != "0.8.0":
                    raise DiagnosticError("released 0.8.0 required")
                for name in ("code_sha256", "python_sha256"):
                    _sha(version[name])
                if (
                    not all(isinstance(v, str) and v for v in version.values())
                    or not Path(version["python"]).is_absolute()
                ):
                    raise DiagnosticError("incomplete worker provenance")
            for version in self.plan["versions"]:
                executable = Path(version["python"]).resolve()
                if file_digest(executable) != version["python_sha256"]:
                    raise DiagnosticError("worker interpreter differs")
                self.paths[executable] = version["python_sha256"]
            if [v["spec_version"] for v in self.plan["versions"]] != ["0.8", "0.9"] or len(
                {v["id"] for v in self.plan["versions"]}
            ) != 2:
                raise DiagnosticError("pair must pin released 0.8 and draft 0.9")
            if not isinstance(self.plan["views"], list) or not 1 <= len(self.plan["views"]) <= 1024:
                raise DiagnosticError("companion view cap")
            self.views = {}
            for view in self.plan["views"]:
                self._view(view)
            if (
                not isinstance(self.plan["packets"], list)
                or not 1 <= len(self.plan["packets"]) <= 1024
            ):
                raise DiagnosticError("packet count cap")
            self.packets, ids, represented = [], set(), set()
            total = 0
            for item in self.plan["packets"]:
                _object(
                    item,
                    {
                        "id",
                        "document",
                        "view",
                        "path",
                        "sha256",
                        "acquisition",
                        "proposer_binding_sha256",
                    },
                )
                ident = _ident(item["id"])
                if (
                    ident in ids
                    or item["view"] not in self.views
                    or item["document"] != self.views[item["view"]]["document"]
                    or item["acquisition"] != "genuine"
                ):
                    raise DiagnosticError("genuine predeclared companion packet required")
                _sha(item["proposer_binding_sha256"])
                ids.add(ident)
                represented.add(item["view"])
                path = _child(self.inputs, item["path"])
                packet = _load(path, item["sha256"])
                self.paths[path] = item["sha256"]
                total += path.stat().st_size
                if total > 128 * 1024 * 1024:
                    raise DiagnosticError("packet total cap")
                _object(
                    packet,
                    {
                        "text",
                        "schema",
                        "candidates",
                        "policy",
                        "document_id",
                        "document_source",
                        "references",
                        "judgments",
                    },
                )
                doc = self.docs[item["document"]]
                if (
                    packet["text"] != self.texts[doc["id"]]
                    or packet["schema"] != self.views[item["view"]]["schema"]
                    or packet["document_id"] != doc["id"]
                    or packet["document_source"] != doc["source"]
                ):
                    raise DiagnosticError("packet text/schema/source differs")
                if not isinstance(packet["candidates"], list) or len(packet["candidates"]) > 1024:
                    raise DiagnosticError("candidate count cap")
                gg.Policy.from_dict(packet["policy"])
                if any(
                    not isinstance(c, dict) or c.get("field") not in packet["schema"]["fields"]
                    for c in packet["candidates"]
                ):
                    raise DiagnosticError("companion candidate names an undeclared field")
                self._offsets(packet)
                self.packets.append((item, packet))
            if represented != set(self.views):
                raise DiagnosticError("missing genuine companion packet")
            self.layout_annotations, self.layout_observations = self._layout()
            self.layout_result = score_layout(self.layout_annotations, self.layout_observations)
            code_paths = (
                Path(__file__),
                Path(__file__).with_name("diagnostic_worker.py"),
                Path(__file__).with_name("metrics.py"),
                Path(__file__).with_name("run_set.py"),
            )
            code_hashes = {p.name: file_digest(p) for p in code_paths}
            self.coordinator_code = source_code_digest()
            code_hashes["coordinator_package"] = self.coordinator_code
            self.code = digest(encoded(code_hashes))
            self.paths.update({p: code_hashes[p.name] for p in code_paths})
            self.binding = digest(encoded({"plan_sha256": plan_sha256, "code_sha256": self.code}))
            self.folder = self.cache / self.binding.removeprefix("sha256:")
            self._states = [
                (obj, digest(encoded(obj)))
                for obj in (
                    self.plan,
                    self.manifest,
                    self.labels,
                    *[p for _, p in self.packets],
                    self.layout_annotations,
                    self.layout_observations,
                    self.layout_result,
                )
            ]
        except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
            if isinstance(exc, DiagnosticError):
                raise
            raise DiagnosticError("invalid diagnostic declaration") from exc

    def _view(self, view: Json) -> None:
        _object(view, {"id", "document", "schema", "mapping", "comparator_adapter"})
        ident = _ident(view["id"])
        if ident in self.views or view["document"] not in self.docs:
            raise DiagnosticError("duplicate or unknown companion view")
        doc = self.docs[view["document"]]
        if doc["split"] != self.plan["split"]:
            raise DiagnosticError("companion split differs")
        schema = view["schema"]
        fields = schema.get("fields") if isinstance(schema, dict) else None
        if not isinstance(fields, dict) or not 1 <= len(fields) <= 1024:
            raise DiagnosticError("companion field count cap")
        slots = 0
        for spec in fields.values():
            keys = spec.get("keys") if isinstance(spec, dict) else None
            if not isinstance(keys, list) or not 1 <= len(keys) <= 4096:
                raise DiagnosticError("companion key count cap")
            slots += len(keys)
            if slots > 4096:
                raise DiagnosticError("companion aggregate slot cap")
        # Bound the Cartesian expansion before schema construction or materializing any slots.
        gg.Schema.from_dict(schema)
        source_schema = doc.get("schema", self.manifest["schemas"][doc["kind"]])
        expected = {
            (f, k) for f, s in view["schema"]["fields"].items() for k in s.get("keys") or []
        }
        if (
            not expected
            or len(expected) > 4096
            or not isinstance(view["mapping"], list)
            or len(view["mapping"]) != len(expected)
        ):
            raise DiagnosticError("complete keyed companion mapping required")
        targets, sources = set(), set()
        for m in view["mapping"]:
            _object(
                m,
                {
                    "field",
                    "key",
                    "source_field",
                    "source_key",
                    "source_comparator",
                    "target_comparator",
                },
            )
            target, source = (m["field"], m["key"]), (m["source_field"], m["source_key"])
            if target not in expected or target in targets or source in sources:
                raise DiagnosticError("colliding companion mapping")
            targets.add(target)
            sources.add(source)
            original = source_schema["fields"][m["source_field"]]
            if m["source_key"] not in (original.get("keys") or [None]):
                raise DiagnosticError("unrequested source slot")
            mapped = view["schema"]["fields"][m["field"]]
            if (original.get("type", "number"), original.get("unit")) != (
                mapped.get("type", "number"),
                mapped.get("unit"),
            ):
                raise DiagnosticError("companion type/unit differs")
            if m["source_comparator"] != original.get("comparator", "eq") or m[
                "target_comparator"
            ] != mapped.get("comparator", "eq"):
                raise DiagnosticError("comparator declaration differs")
            if m["source_comparator"] != m["target_comparator"] and not (
                view["comparator_adapter"] == "keyed_endpoint_eq"
                and m["source_comparator"] in {"ge", "le"}
                and m["target_comparator"] == "eq"
            ):
                raise DiagnosticError("undeclared comparator adapter")
        if view["comparator_adapter"] not in {None, "keyed_endpoint_eq"}:
            raise DiagnosticError("unknown comparator adapter")
        self.views[ident] = view

    @staticmethod
    def _offsets(packet: Json) -> None:
        if not isinstance(packet["references"], list) or not isinstance(packet["judgments"], list):
            raise DiagnosticError("invalid recorded packet inputs")
        texts = {None: packet["text"]}
        for ref in packet["references"]:
            if (
                not isinstance(ref, dict)
                or not isinstance(ref.get("text"), str)
                or not isinstance(ref.get("id"), str)
                or ref["id"] in texts
            ):
                raise DiagnosticError("invalid reference")
            texts[ref["id"]] = ref["text"]
        for candidate in packet["candidates"]:
            if not isinstance(candidate, dict):
                raise DiagnosticError("companion candidates must be recorded objects")
            for evidence in candidate.get("evidence", []):
                if isinstance(evidence, dict) and ("start" in evidence or "end" in evidence):
                    text = texts.get(
                        evidence.get("ref") if evidence.get("source") == "reference" else None
                    )
                    if text is None:
                        raise DiagnosticError("unknown evidence reference")
                    _span(text.encode(), evidence.get("start"), evidence.get("end"))

    def _layout(self) -> tuple[list[Json], list[Json]]:
        config = self.plan["layout"]
        if config is None:
            return [], []
        _object(config, {"annotations", "observations"})
        ref = _object(config["annotations"], {"path", "sha256"})
        path = _child(self.inputs, ref["path"])
        ann = _load(path, ref["sha256"])
        self.paths[path] = ref["sha256"]
        _object(ann, {"format", "status", "manifest_sha256", "labels_sha256", "documents"})
        if (
            ann["format"] != "requested-layout-labels/1"
            or ann["status"] != "sealed"
            or any(ann[k] != self.plan[k] for k in ("manifest_sha256", "labels_sha256"))
        ):
            raise DiagnosticError("layout annotation seal differs")
        if (
            not isinstance(ann["documents"], list)
            or len(ann["documents"]) > 1024
            or not isinstance(config["observations"], list)
            or len(config["observations"]) > 2048
        ):
            raise DiagnosticError("layout count cap")
        seen = set()
        for doc in ann["documents"]:
            _object(
                doc, {"id", "source_sha256", "source_pages", "reviewed_pages", "complete", "routes"}
            )
            if (
                doc["id"] in seen
                or doc["id"] not in self.docs
                or doc["source_sha256"] != self.docs[doc["id"]]["source_sha256"]
                or doc["source_pages"] != self.docs[doc["id"]]["source_pages"]
            ):
                raise DiagnosticError("layout source differs")
            if self.docs[doc["id"]]["split"] != self.plan["split"]:
                raise DiagnosticError("layout split differs")
            seen.add(doc["id"])
            if (
                type(doc["complete"]) is not bool
                or not isinstance(doc["reviewed_pages"], list)
                or any(
                    type(x) is not int or not 1 <= x <= doc["source_pages"]
                    for x in doc["reviewed_pages"]
                )
                or len(set(doc["reviewed_pages"])) != len(doc["reviewed_pages"])
            ):
                raise DiagnosticError("invalid layout coverage")
            if doc["complete"] and len(doc["reviewed_pages"]) != doc["source_pages"]:
                raise DiagnosticError("incomplete layout coverage")
            if not isinstance(doc["routes"], list) or len(doc["routes"]) > 3:
                raise DiagnosticError("layout route cap")
            cases, route_names, case_ids = 0, set(), set()
            for route in doc["routes"]:
                _object(route, {"route", "assessment", "cases"})
                if (
                    route["route"] not in _ROUTES
                    or route["assessment"] not in {"applicable", "not_applicable", "unassessed"}
                    or not isinstance(route["cases"], list)
                ):
                    raise DiagnosticError("invalid blind layout route")
                if route["route"] in route_names:
                    raise DiagnosticError("duplicate layout route")
                route_names.add(route["route"])
                if route["assessment"] == "not_applicable" and (
                    not doc["complete"] or route["cases"]
                ):
                    raise DiagnosticError("not-applicable needs complete blind coverage")
                if route["assessment"] == "unassessed" and route["cases"]:
                    raise DiagnosticError("unassessed route cannot have scored cases")
                if route["assessment"] == "applicable" and not route["cases"]:
                    raise DiagnosticError("applicable route needs actual cases")
                cases += len(route["cases"])
                if cases > 4096:
                    raise DiagnosticError("layout case cap")
                for case in route["cases"]:
                    case_keys = {"id", "page", "state", "box", "expected", "reason"}
                    if route["route"] == "running_heads":
                        case_keys.add("target")
                    _object(case, case_keys)
                    _ident(case["id"])
                    if (
                        case["id"] in case_ids
                        or not isinstance(case["reason"], str)
                        or (case["state"] != "observed" and not case["reason"].strip())
                    ):
                        raise DiagnosticError("duplicate case or missing annotation reason")
                    case_ids.add(case["id"])
                    if case["page"] not in doc["reviewed_pages"] or case["state"] not in {
                        "observed",
                        "unclear",
                        "unannotated",
                    }:
                        raise DiagnosticError("invalid blind layout case")
                    boxes = [case["box"]]
                    if route["route"] == "running_heads":
                        target = _object(case["target"], {"page", "box"})
                        if (
                            type(target["page"]) is not int
                            or target["page"] not in doc["reviewed_pages"]
                        ):
                            raise DiagnosticError("running-head target needs blind page coverage")
                        boxes.append(target["box"])
                    for box in boxes:
                        if (
                            not isinstance(box, list)
                            or len(box) != 4
                            or any(type(x) not in {int, float} or not math.isfinite(x) for x in box)
                            or not 0 <= box[0] < box[2]
                            or not 0 <= box[1] < box[3]
                        ):
                            raise DiagnosticError("invalid blind geometry")
                    expected = case["expected"]
                    if (
                        type(expected) is not bool
                        if route["route"] == "running_heads"
                        else type(expected) is not int or not 0 <= expected <= 4096
                    ):
                        raise DiagnosticError("invalid blind layout expectation")
        observations, seen, total = [], set(), 0
        for ref in config["observations"]:
            _object(ref, {"document", "reader", "commit", "code_sha256", "path", "sha256"})
            pair = (ref["document"], ref["reader"])
            if pair in seen or ref["document"] not in self.docs:
                raise DiagnosticError("duplicate/unknown reader observation")
            if self.docs[ref["document"]]["split"] != self.plan["split"]:
                raise DiagnosticError("layout split differs")
            seen.add(pair)
            _ident(ref["reader"])
            _sha(ref["code_sha256"])
            path = _child(self.inputs, ref["path"])
            total += path.stat().st_size
            if total > 32 * 1024 * 1024:
                raise DiagnosticError("layout input total cap")
            obs = _load(path, ref["sha256"])
            self.paths[path] = ref["sha256"]
            _object(
                obs,
                {
                    "source_sha256",
                    "reader",
                    "commit",
                    "code_sha256",
                    "text_sha256",
                    "text",
                    "layout",
                },
            )
            if (
                obs["source_sha256"] != self.docs[ref["document"]]["source_sha256"]
                or any(obs[k] != ref[k] for k in ("reader", "commit", "code_sha256"))
                # Layout comes only from the frozen reader and the document's frozen text.
                or ref["reader"] != self.plan["reader"]["id"]
                or any(ref[k] != self.plan["reader"][k] for k in ("commit", "code_sha256"))
                or obs["text_sha256"] != self.docs[ref["document"]]["text_sha256"]
                or not isinstance(obs["text"], str)
                or digest(obs["text"].encode()) != obs["text_sha256"]
            ):
                raise DiagnosticError("reader observation provenance differs")
            if unicodedata.normalize("NFC", obs["text"]) != obs["text"]:
                raise DiagnosticError("layout text must be NFC")
            observations.append(
                {
                    "document": ref["document"],
                    "kind": self.docs[ref["document"]]["kind"],
                    "reader": ref["reader"],
                    "trace": serialized_layout(obs["text"], obs["layout"]),
                }
            )
        return ann["documents"], observations

    def check_inputs(self) -> None:
        if source_code_digest() != self.coordinator_code:
            raise DiagnosticError("diagnostic coordinator package changed")
        if any(digest(encoded(obj)) != expected for obj, expected in self._states):
            raise DiagnosticError("in-memory diagnostic input changed")
        for path, expected in self.paths.items():
            if file_digest(_unlinked(path)) != expected:
                raise DiagnosticError("frozen diagnostic input changed")

    @staticmethod
    def _receipt(version: Json, packet: Json, value: Json) -> list[Json]:
        _object(
            value,
            {
                "package_version",
                "spec_version",
                "code_sha256",
                "packet_sha256",
                "schema",
                "policy",
                "receipt",
            },
        )
        if any(
            value[k] != version[k] for k in ("package_version", "spec_version", "code_sha256")
        ) or value["packet_sha256"] != digest(encoded(packet)):
            raise DiagnosticError("worker fingerprint or packet differs")
        schema, policy = (
            gg.Schema.from_dict(packet["schema"]).to_dict(),
            gg.Policy.from_dict(packet["policy"]).to_dict(),
        )
        if value["schema"] != schema or value["policy"] != policy:
            raise DiagnosticError("worker schema/policy normalization differs")
        receipt = copy.deepcopy(value["receipt"])
        _object(
            receipt,
            {
                "groundgate",
                "document",
                "references",
                "schema_sha256",
                "policy_sha256",
                "decisions",
                "coverage",
                "judgments",
                "summary",
                "receipt_sha256",
            },
        )
        checksum = receipt.pop("receipt_sha256", None)
        spec = version["spec_version"]
        if (
            checksum != core_digest(spec, "receipt", receipt)
            or receipt.get("groundgate") != spec
            or receipt.get("schema_sha256") != core_digest(spec, "schema", schema)
            or receipt.get("policy_sha256") != core_digest(spec, "policy", policy)
            or receipt.get("document")
            != {
                "id": packet["document_id"],
                "source": packet["document_source"],
                "sha256": core_digest(spec, "document", {"text": packet["text"]}),
            }
        ):
            raise DiagnosticError("worker receipt binding differs")
        references = [
            {
                "id": ref["id"],
                "sha256": core_digest(spec, "reference", {"text": ref["text"]}),
                "source": ref.get("source"),
            }
            for ref in sorted(packet["references"], key=lambda ref: ref["id"])
        ]
        if (
            receipt["references"] != references
            or not isinstance(receipt["coverage"], list)
            or not isinstance(receipt["judgments"], list)
        ):
            raise DiagnosticError("worker reference/recorded metadata differs")
        decisions = receipt["decisions"]
        if not isinstance(decisions, list) or len(decisions) > 1024:
            raise DiagnosticError("worker decision cap")
        by_sha: dict[str, deque[Json]] = defaultdict(deque)
        for decision in decisions:
            if (
                not isinstance(decision, dict)
                or decision.get("outcome") not in {"admitted", "needs_verification", "rejected"}
                or not isinstance(decision.get("codes"), list)
                or any(
                    not isinstance(x, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", x)
                    for x in decision["codes"]
                )
                or not isinstance(decision.get("candidate_sha256"), str)
            ):
                raise DiagnosticError("invalid worker decision")
            by_sha[decision["candidate_sha256"]].append(decision)
        counts = dict.fromkeys(("admitted", "needs_verification", "rejected"), 0)
        for decision in decisions:
            counts[decision["outcome"]] += 1
        if receipt["summary"] != counts:
            raise DiagnosticError("worker receipt counts differ")
        expected = Counter(core_digest(spec, "candidate", c) for c in packet["candidates"])
        if {sha: len(items) for sha, items in by_sha.items()} != expected:
            raise DiagnosticError("missing or extra candidate decision")
        return [by_sha[core_digest(spec, "candidate", c)].popleft() for c in packet["candidates"]]

    def run(
        self, *, worker: Callable[[Json, Json], Json] | None = None, replay_only: bool = False
    ) -> Json:
        self.check_inputs()
        _same(
            self.folder / "header.json",
            {
                "plan_sha256": self.paths[self.plan_path],
                "code_sha256": self.code,
                "binding_sha256": self.binding,
            },
            replay_only,
        )
        transitions, added, removed, by_view, failures = Counter(), Counter(), Counter(), {}, []
        by_kind, incomplete = {}, set()
        projections: dict[tuple[str, str], list[Json]] = {}
        for item, packet in self.packets:
            paired = []
            for version in self.plan["versions"]:
                self.check_inputs()
                name = digest(encoded([item["id"], version["id"]])).removeprefix("sha256:")
                path, pending = (
                    self.folder / (name + ".json"),
                    self.folder / (name + ".pending.json"),
                )
                request = {
                    "packet_sha256": digest(encoded(packet)),
                    "version": version,
                    "binding_sha256": self.binding,
                }
                _unlinked(path)
                _unlinked(pending)
                if path.exists():
                    try:
                        entry = _json(_read(path, _MAX))
                    except (CacheError, UnicodeError, RecursionError) as exc:
                        raise DiagnosticError("invalid cached worker JSON") from exc
                    checksum = entry.pop("entry_sha256", None)
                    if checksum != digest(encoded(entry)) or entry.get("request") != request:
                        raise DiagnosticError("cached worker result differs")
                    status = entry.get("status")
                    keys = (
                        {"request", "status", "value"}
                        if status == "ok"
                        else {"request", "status", "exception_type"}
                    )
                    _object(entry, keys)
                    if status not in {"ok", "error"} or (
                        status == "error"
                        and not re.fullmatch(
                            r"[A-Za-z_][A-Za-z0-9_]{0,127}", entry["exception_type"]
                        )
                    ):
                        raise DiagnosticError("invalid cached worker status")
                    _same(pending, request, True)
                else:
                    if replay_only or pending.exists():
                        raise DiagnosticError("missing or unresolved worker reservation")
                    _publish(pending, request)
                    try:
                        value = (
                            worker(version, copy.deepcopy(packet))
                            if worker is not None
                            else run_worker(version, copy.deepcopy(packet), temporary=self.folder)
                        )
                    except Exception as exc:
                        entry = {
                            "request": request,
                            "status": "error",
                            "exception_type": type(exc).__name__
                            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", type(exc).__name__)
                            else "Exception",
                        }
                    else:
                        if len(encoded(value)) > _MAX:
                            raise DiagnosticError("worker result cap")
                        self._receipt(version, packet, value)
                        entry = {"request": request, "status": "ok", "value": value}
                    _publish(path, entry | {"entry_sha256": digest(encoded(entry))})
                if entry["status"] != "ok":
                    failures.append(
                        {
                            "packet": item["id"],
                            "version": version["id"],
                            "status": "incomplete",
                            "exception_type": entry["exception_type"],
                        }
                    )
                    incomplete.add((item["view"], version["id"]))
                    paired.append(None)
                    continue
                ordered = self._receipt(version, packet, entry["value"])
                projections.setdefault((item["view"], version["id"]), []).extend(ordered)
                paired.append(ordered)
            if all(x is not None for x in paired):
                for before, after in zip(paired[0], paired[1], strict=True):
                    transition = before["outcome"] + "->" + after["outcome"]
                    transitions[transition] += 1
                    kind = self.docs[item["document"]]["kind"]
                    by_kind.setdefault(kind, Counter())[transition] += 1
                    added.update(set(after["codes"]) - set(before["codes"]))
                    removed.update(set(before["codes"]) - set(after["codes"]))
        for view_id, view in self.views.items():
            doc = self.docs[view["document"]]
            labels = {(f["field"], f.get("key")): f for f in self.gold[doc["id"]]["fields"]}
            slots = []
            for mapping in view["mapping"]:
                label = copy.deepcopy(labels[(mapping["source_field"], mapping["source_key"])])
                label.update(field=mapping["field"], key=mapping["key"])
                slots.append(label)
            by_view[view_id] = {}
            for version in self.plan["versions"]:
                if (view_id, version["id"]) in incomplete:
                    by_view[view_id][version["id"]] = {"status": "incomplete"}
                    continue
                decisions = projections.get((view_id, version["id"]))
                if decisions is None:
                    continue
                result = measure(
                    {
                        "schemas": {doc["kind"]: view["schema"]},
                        "documents": [
                            {"id": doc["id"], "kind": doc["kind"], "split": self.plan["split"]}
                        ],
                    },
                    {"status": "sealed", "documents": [{"id": doc["id"], "fields": slots}]},
                    {"documents": [{"id": doc["id"], "decisions": decisions, "not_found": []}]},
                    self.plan["split"],
                )["total"]
                by_view[view_id][version["id"]] = {
                    k: result[k]
                    for k in (
                        "admitted",
                        "escapes",
                        "present",
                        "hits",
                        "reviews",
                        "silent_misses",
                        "excluded",
                    )
                }
        diagnostic = {
            "format": "requested-diagnostics/1",
            "binding_sha256": self.binding,
            "provenance": {
                "plan_sha256": self.paths[self.plan_path],
                "code_sha256": self.code,
                "reader": self.plan["reader"],
                "versions": self.plan["versions"],
            },
            "decision_pair": {
                "transitions": dict(sorted(transitions.items())),
                "added_codes": dict(sorted(added.items())),
                "removed_codes": dict(sorted(removed.items())),
                "by_view": by_view,
                "by_kind": {k: dict(sorted(v.items())) for k, v in sorted(by_kind.items())},
                "failures": failures,
            },
            "reader_layout": self.layout_result,
            "companion_views": {
                "mapping_sha256": digest(encoded(self.plan["views"])),
                "source_documents": sorted({v["document"] for v in self.views.values()}),
                "correlated_views": True,
                "limitations": [
                    "Companion views do not add independent primary trials or bounds.",
                    "Explicit endpoint eq adaptation differs from original ge/le comparators.",
                    "No absence claim is inferred from missing candidates or unkeyed envelopes.",
                ],
            },
        }
        output = {
            "format": "requested-diagnostics-export/1",
            "manifest_sha256": self.plan["manifest_sha256"],
            "labels_sha256": self.plan["labels_sha256"],
            "split": self.plan["split"],
            "diagnostics": diagnostic,
        }
        self.check_inputs()
        expected_names = {"header.json", "diagnostic-export.json"}
        for item, _ in self.packets:
            for version in self.plan["versions"]:
                stem = digest(encoded([item["id"], version["id"]])).removeprefix("sha256:")
                expected_names.update({stem + ".json", stem + ".pending.json"})
        actual_names = {p.name for p in self.folder.iterdir()}
        if actual_names - expected_names:
            raise DiagnosticError("extra diagnostic cache artifact")
        _same(self.folder / "diagnostic-export.json", output, replay_only)
        return output


def run_worker(version: Json, packet: Json, *, temporary: Path) -> Json:
    """Launch only the fixed public-decision worker in a pinned interpreter, with bounded pipes."""
    python = Path(version["python"])
    if file_digest(python.resolve()) != version["python_sha256"]:
        raise DiagnosticError("worker interpreter changed")
    script = Path(__file__).with_name("diagnostic_worker.py")
    request = encoded({"expected": version, "packet": packet})
    if len(request) > _MAX:
        raise DiagnosticError("worker packet cap")
    # Source-bearing stdin is a regular bounded temporary file, never a shell argument.
    import tempfile

    with tempfile.TemporaryFile(dir=temporary) as stdin:
        stdin.write(request)
        stdin.seek(0)
        proc = subprocess.Popen(
            [str(python), "-I", str(script)],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        selector = selectors.DefaultSelector()
        assert proc.stdout is not None and proc.stderr is not None
        for stream in (proc.stdout, proc.stderr):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ)
        chunks = {proc.stdout: bytearray(), proc.stderr: bytearray()}
        deadline = time.monotonic() + 60
        try:
            while selector.get_map():
                if time.monotonic() > deadline:
                    raise DiagnosticError("worker timeout")
                for key, _ in selector.select(0.1):
                    body = os.read(key.fileobj.fileno(), 65536)
                    if not body:
                        selector.unregister(key.fileobj)
                        continue
                    target = chunks[key.fileobj]
                    if len(target) + len(body) > (_MAX if key.fileobj is proc.stdout else 65536):
                        raise DiagnosticError("worker output cap")
                    target.extend(body)
            if proc.wait(timeout=max(0.1, deadline - time.monotonic())) != 0:
                raise DiagnosticError("worker process failed")
            return _json(bytes(chunks[proc.stdout]))
        finally:
            selector.close()
            if proc.poll() is None:
                import signal

                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()


def load_export(
    path: Path, expected_sha256: str, manifest_sha256: str, labels_sha256: str, split: str
) -> Json:
    """Validate an explicitly pinned diagnostic export before primary-score integration."""
    output = _load(path, expected_sha256)
    _object(output, {"format", "manifest_sha256", "labels_sha256", "split", "diagnostics"})
    if (
        output["format"] != "requested-diagnostics-export/1"
        or output["manifest_sha256"] != manifest_sha256
        or output["labels_sha256"] != labels_sha256
        or output["split"] != split
    ):
        raise DiagnosticError("diagnostic export seal/split differs")
    diagnostic = _object(
        output["diagnostics"],
        {
            "format",
            "binding_sha256",
            "provenance",
            "decision_pair",
            "reader_layout",
            "companion_views",
        },
    )
    if diagnostic["format"] != "requested-diagnostics/1":
        raise DiagnosticError("unknown diagnostic result format")
    _sha(diagnostic["binding_sha256"])
    provenance = _object(
        diagnostic["provenance"], {"plan_sha256", "code_sha256", "reader", "versions"}
    )
    _sha(provenance["plan_sha256"])
    _sha(provenance["code_sha256"])
    pair = _object(
        diagnostic["decision_pair"],
        {"transitions", "added_codes", "removed_codes", "by_view", "by_kind", "failures"},
    )

    def counts(value: Any) -> None:
        if (
            not isinstance(value, dict)
            or len(value) > 4096
            or any(
                not isinstance(k, str)
                or not re.fullmatch(r"[A-Za-z0-9_.>/-]{1,200}", k)
                or type(v) is not int
                or v < 0
                for k, v in value.items()
            )
        ):
            raise DiagnosticError("invalid diagnostic counts")

    for name in ("transitions", "added_codes", "removed_codes"):
        counts(pair[name])
    if (
        not isinstance(pair["by_kind"], dict)
        or not isinstance(pair["by_view"], dict)
        or not isinstance(pair["failures"], list)
    ):
        raise DiagnosticError("invalid diagnostic slices")
    for kind, transitions in pair["by_kind"].items():
        _ident(kind)
        counts(transitions)
    metric_keys = {"admitted", "escapes", "present", "hits", "reviews", "silent_misses", "excluded"}
    for view, versions in pair["by_view"].items():
        _ident(view)
        if not isinstance(versions, dict):
            raise DiagnosticError("invalid diagnostic view versions")
        for version, stats in versions.items():
            _ident(version)
            if stats == {"status": "incomplete"}:
                continue
            _object(stats, metric_keys)
            counts(stats)
    layout = diagnostic["reader_layout"]
    if (
        not isinstance(layout, dict)
        or layout.get("status") not in {"assessed", "unassessed"}
        or not isinstance(layout.get("routes"), dict)
        or not isinstance(layout.get("limitations"), list)
        or not isinstance(layout.get("missing_observations", []), list)
        or len(layout.get("missing_observations", [])) > 1024
    ):
        raise DiagnosticError("invalid diagnostic layout result")
    for ident in layout.get("missing_observations", []):
        _ident(ident)
    for name, row in layout["routes"].items():
        if not isinstance(name, str) or len(name) > 200 or not isinstance(row, dict):
            raise DiagnosticError("invalid layout slice")
        count_keys = {
            "evaluated",
            "correct",
            "unclear",
            "unassessed",
            "not_applicable",
            "reviewed_pages",
            "unreviewed_pages",
            "partial_documents",
        }
        _object(row, count_keys | {"rate"})
        counts({k: row[k] for k in count_keys})
        expected_rate = row["correct"] / row["evaluated"] if row["evaluated"] else None
        if row["correct"] > row["evaluated"] or row["rate"] != expected_rate:
            raise DiagnosticError("layout rate differs from counts")
    if not all(isinstance(s, str) and len(s) <= 4096 for s in layout["limitations"]):
        raise DiagnosticError("invalid layout limitations")
    companion = _object(
        diagnostic["companion_views"],
        {"mapping_sha256", "source_documents", "correlated_views", "limitations"},
    )
    _sha(companion["mapping_sha256"])
    if companion["correlated_views"] is not True or not isinstance(
        companion["source_documents"], list
    ):
        raise DiagnosticError("diagnostic views must remain correlated")
    for ident in companion["source_documents"]:
        _ident(ident)
    return diagnostic | {"export_sha256": expected_sha256}


def main() -> None:
    """Execute pinned local decision workers, or replay without starting them."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--set", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--replay", action="store_true")
    args = parser.parse_args()
    try:
        session = DiagnosticSession(
            args.plan, args.set, args.sources, args.inputs, args.cache, plan_sha256=args.plan_sha256
        )
        session.run(replay_only=args.replay)
    except (DiagnosticError, CacheError, OSError, KeyError, TypeError) as exc:
        parser.error("diagnostic input/cache/worker check failed: " + type(exc).__name__)
    print(
        json.dumps(
            {
                "binding_sha256": session.binding,
                "export": str(session.folder / "diagnostic-export.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
