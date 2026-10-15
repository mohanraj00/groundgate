"""Blind labels from original local PDFs. Never opens or displays model output.

Run after approved sources and manifest exist:
    uv run python bench/requested/label_app.py --source-dir /absolute/LocalWork/sources
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested.metrics import measure, signature

LOCAL_WORK = Path.home() / "Library/Application Support/Codex/LocalWork"
MAX_BODY = 262144
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON member")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def reject_constant(raw: str) -> Any:
    raise ValueError(f"non-finite JSON value: {raw}")


class LabelStore:
    """Fixed-path draft storage. Reading run contents is deliberately unsupported."""

    def __init__(self, directory: Path, sources: Path, work_directory: Path | None = None) -> None:
        self.directory = directory.resolve()
        self.sources = sources.resolve()
        self.work_directory = (work_directory or self.sources.parent / "label-work").resolve()
        self.path = self.directory / "labels.json"
        self.manifest = read_json(self.directory / "manifest.json")
        documents = self.manifest["documents"]
        if not documents:
            raise ValueError("the manifest has no approved documents")
        self.documents = {}
        for document in documents:
            ident = document["id"]
            if not isinstance(ident, str) or not ID.fullmatch(ident):
                raise ValueError("unsafe document ID")
            if ident in self.documents:
                raise ValueError("duplicate manifest document")
            self.documents[ident] = document
        self.lock = threading.Lock()
        self.preview_lock = threading.Lock()
        self.renderer = shutil.which("pdftoppm")
        if self.renderer is None and os.access("/opt/homebrew/bin/pdftoppm", os.X_OK):
            self.renderer = "/opt/homebrew/bin/pdftoppm"

    def schema(self, ident: str) -> dict[str, Any]:
        document = self.documents[ident]
        return document.get("schema", self.manifest["schemas"][document["kind"]])

    def blank_fields(self, ident: str) -> list[dict[str, Any]]:
        return [
            {
                "field": name,
                "key": key,
                "status": "unlabeled",
                "values": [],
                "page": None,
                "note": "",
                "reason": "",
                "second_check": False,
            }
            for name, field in self.schema(ident)["fields"].items()
            for key in field.get("keys") or [None]
        ]

    def labels(self) -> dict[str, Any]:
        if self.path.is_symlink():
            raise ValueError("labels.json must not be a symlink")
        if self.path.exists():
            return read_json(self.path)
        return {
            "status": "draft",
            "documents": [
                {"id": ident, "fields": self.blank_fields(ident)} for ident in self.documents
            ],
        }

    def blocked(self, labels: dict[str, Any]) -> str | None:
        if labels.get("status") != "draft":
            return "labels are sealed or have an unknown status"
        if any(path.is_file() for path in (self.directory / "runs").rglob("*.json")):
            return "cached run JSON exists; label changes need maintainer approval"
        return None

    def validate_fields(self, ident: str, fields: Any, complete: bool = False) -> None:
        if not isinstance(fields, list):
            raise ValueError("fields must be a list")
        expected = {(s["field"], s["key"]) for s in self.blank_fields(ident)}
        seen = set()
        for slot in fields:
            if not isinstance(slot, dict) or set(slot) - {
                "field",
                "key",
                "status",
                "values",
                "page",
                "note",
                "reason",
                "second_check",
            }:
                raise ValueError("unknown label member")
            name, key = slot.get("field"), slot.get("key")
            if not isinstance(name, str) or (key is not None and not isinstance(key, str)):
                raise ValueError("invalid field/key")
            pair = (name, key)
            if pair not in expected or pair in seen:
                raise ValueError("unknown or duplicate field/key")
            seen.add(pair)
            state = slot.get("status")
            if state not in {"unlabeled", "present", "absent", "unclear"}:
                raise ValueError("unknown label state")
            spec = self.schema(ident)["fields"][name]
            values = slot.get("values", [])
            if not isinstance(values, list) or len(values) > 100:
                raise ValueError("values must be a list of at most 100 items")
            if state != "present" and values:
                raise ValueError("only present labels can have values")
            for value in values:
                if not isinstance(value, dict) or set(value) != {"value", "unit"}:
                    raise ValueError("each value needs only value and unit")
                signature(value, spec.get("type", "number"))
                if value["unit"] != spec.get("unit"):
                    raise ValueError("unit must match the requested field")
            if len(values) > 1 and not spec.get("multiple", False):
                raise ValueError("a single-value field has multiple values")
            page = slot.get("page")
            if page is not None and (type(page) is not int or not 1 <= page <= 100000):
                raise ValueError("evidence page must be a positive integer")
            source_pages = self.documents[ident].get("source_pages")
            if source_pages is not None:
                if type(source_pages) is not int or source_pages < 1:
                    raise ValueError("source_pages must be a positive integer")
                if page is not None and page > source_pages:
                    raise ValueError("evidence page exceeds the original PDF page count")
            for member in ("note", "reason"):
                if not isinstance(slot.get(member, ""), str) or len(slot.get(member, "")) > 4000:
                    raise ValueError(f"{member} must be text of at most 4000 characters")
            if type(slot.get("second_check", False)) is not bool:
                raise ValueError("second_check must be boolean")
            if complete:
                if state == "unlabeled":
                    raise ValueError("every field/key needs a label before sealing")
                if state == "present" and (not values or page is None):
                    raise ValueError("present labels need a value and an original PDF page")
                if state == "unclear" and not slot.get("reason", "").strip():
                    raise ValueError("unclear labels need a reason")
                if state == "absent" and slot.get("second_check") is not True:
                    raise ValueError("absent labels need a second blind check")
        if seen != expected:
            raise ValueError("fields must cover every requested field/key exactly once")

    def write(self, labels: dict[str, Any]) -> None:
        self.work_directory.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".labels-", suffix=".tmp", dir=self.work_directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(labels, fp, ensure_ascii=False, indent=2, allow_nan=False)
                fp.write("\n")
                fp.flush()
                os.fsync(fp.fileno())
            # Check the on-disk seal and run-file presence again before replacing any draft.
            if reason := self.blocked(self.labels()):
                raise ValueError(reason)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def save(self, payload: dict[str, Any]) -> None:
        if set(payload) != {"id", "fields"} or not isinstance(payload["id"], str):
            raise ValueError("save requires only id and fields")
        ident = payload["id"]
        if ident not in self.documents:
            raise ValueError("unknown document")
        with self.lock:
            labels = self.labels()
            if reason := self.blocked(labels):
                raise ValueError(reason)
            self.validate_fields(ident, payload["fields"])
            labels = copy.deepcopy(labels)
            docs = labels.get("documents", [])
            if {doc["id"] for doc in docs} != set(self.documents) or len(docs) != len(
                self.documents
            ):
                raise ValueError("draft labels do not match the manifest")
            for document in docs:
                if document["id"] == ident:
                    document["fields"] = payload["fields"]
            self.write(labels)

    def seal(self) -> None:
        with self.lock:
            labels = self.labels()
            if reason := self.blocked(labels):
                raise ValueError(reason)
            if self.manifest.get("status") != "frozen":
                raise ValueError("the complete manifest must be frozen before sealing")
            if read_json(self.directory / "manifest.json") != self.manifest:
                raise ValueError("manifest changed; restart the labeling server")
            candidate = copy.deepcopy(labels)
            for doc in candidate["documents"]:
                if doc["id"] not in self.documents:
                    raise ValueError("unknown label document")
                self.validate_fields(doc["id"], doc["fields"], complete=True)
            for ident in self.documents:
                self.verified_pdf(ident)
            candidate["status"] = "sealed"
            for split in {doc["split"] for doc in self.documents.values()}:
                measure(self.manifest, candidate, {"documents": []}, split)
            self.write(candidate)

    def source(self, ident: str, suffix: str) -> Path:
        if ident not in self.documents or suffix not in {"pdf", "txt"}:
            raise ValueError("unknown source")
        path = (self.sources / f"{ident}.{suffix}").resolve()
        if not path.is_relative_to(self.sources) or not path.is_file():
            raise ValueError("source file not found")
        return path

    def verified_pdf(self, ident: str) -> bytes:
        """Return one verified snapshot, so a path swap cannot change the bytes we serve."""
        path = self.source(ident, "pdf")
        expected = self.documents[ident].get("source_sha256")
        if not isinstance(expected, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", expected):
            raise ValueError("the original PDF needs a pinned source_sha256")
        raw = path.read_bytes()
        if not hmac.compare_digest("sha256:" + hashlib.sha256(raw).hexdigest(), expected):
            raise ValueError("source PDF hash does not match the manifest")
        return raw

    def preview(self, ident: str, page: int) -> bytes:
        """Render one original page. Every request rechecks the source, including cache hits."""
        if ident not in self.documents:
            raise ValueError("unknown source")
        count = self.documents[ident].get("source_pages")
        if type(count) is not int or type(page) is not int or not 1 <= page <= count:
            raise ValueError("preview page must be within the original PDF page count")
        if not self.renderer:
            raise ValueError("page previews are unavailable; open the original PDF")
        raw = self.verified_pdf(ident)
        digest = hashlib.sha256(raw).hexdigest()
        cache = self.work_directory / "previews" / digest / f"page-{page}.png"
        if not cache.resolve().is_relative_to(self.work_directory) or cache.is_symlink():
            raise ValueError("unsafe preview cache path")
        with self.preview_lock:
            if cache.exists():
                return cache.read_bytes()
            cache.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="page-", dir=self.work_directory) as scratch:
                prefix = Path(scratch) / "preview"
                try:
                    subprocess.run(
                        [
                            self.renderer,
                            "-f",
                            str(page),
                            "-l",
                            str(page),
                            "-singlefile",
                            "-scale-to",
                            "1600",
                            "-png",
                            "-",
                            str(prefix),
                        ],
                        input=raw,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=True,
                        timeout=30,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    raise ValueError("page preview failed; open the original PDF") from exc
                image = prefix.with_suffix(".png")
                if not image.is_file() or not image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("the page renderer did not produce a PNG")
                os.replace(image, cache)
            return cache.read_bytes()

    def source_text_available(self, ident: str) -> bool:
        """Report only a manifest document's existing, confined optional text path."""
        try:
            self.source(ident, "txt")
        except (ValueError, OSError):
            return False
        return True

    def state(self) -> dict[str, Any]:
        labels = self.labels()
        return {
            "documents": [
                dict(
                    doc,
                    schema=self.schema(ident),
                    source_text_available=self.source_text_available(ident),
                )
                for ident, doc in self.documents.items()
            ],
            "labels": labels,
            "blocked": self.blocked(labels),
            "can_seal": self.manifest.get("status") == "frozen" and not self.blocked(labels),
            "preview_available": self.renderer is not None,
        }


class LabelServer(ThreadingHTTPServer):
    def __init__(self, store: LabelStore, port: int = 8784) -> None:
        self.store = store
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), LabelHandler)


class LabelHandler(BaseHTTPRequestHandler):
    server: LabelServer

    def log_message(self, format: str, *args: Any) -> None:
        # No label values or request contents enter server logs.
        return

    def reply(self, status: int, data: bytes, kind: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; frame-src 'self'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(data)

    def error(self, status: int, message: str) -> None:
        self.reply(status, json.dumps({"error": message}).encode())

    def host_ok(self) -> bool:
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def do_GET(self) -> None:
        if not self.host_ok():
            self.error(403, "unknown host")
            return
        route = urlsplit(self.path)
        if route.query or route.fragment:
            self.error(404, "unknown route")
            return
        try:
            if route.path == "/":
                self.reply(200, Path(__file__).with_name("label.html").read_bytes(), "text/html")
            elif route.path == "/api/state":
                state = self.server.store.state() | {"token": self.server.token}
                self.reply(200, json.dumps(state).encode())
            elif route.path.startswith("/page/"):
                parts = route.path.split("/")
                if len(parts) != 4 or not re.fullmatch(r"[1-9][0-9]{0,5}", parts[3]):
                    raise ValueError("invalid page preview route")
                self.reply(200, self.server.store.preview(parts[2], int(parts[3])), "image/png")
            elif route.path.startswith(("/pdf/", "/text/")):
                kind, ident = route.path[1:].split("/", 1)
                if kind == "pdf":
                    self.reply(200, self.server.store.verified_pdf(ident), "application/pdf")
                    return
                source = self.server.store.source(ident, "txt")
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/pdf" if kind == "pdf" else "text/plain; charset=utf-8",
                )
                self.send_header("Content-Length", str(source.stat().st_size))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                with source.open("rb") as fp:
                    shutil.copyfileobj(fp, self.wfile)
            else:
                self.error(404, "unknown route")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.error(400, str(exc))

    def do_POST(self) -> None:
        if not self.host_ok():
            self.error(403, "unknown host")
            return
        expected_origin = f"http://127.0.0.1:{self.server.server_port}"
        token = self.headers.get("X-Label-Token", "")
        if (
            self.headers.get("Origin", expected_origin) != expected_origin
            or not token.isascii()
            or not hmac.compare_digest(token, self.server.token)
        ):
            self.error(403, "invalid request token or origin")
            return
        if self.path not in {"/api/save", "/api/seal"}:
            self.error(404, "unknown route")
            return
        if self.headers.get("Content-Type") != "application/json" or self.headers.get(
            "Transfer-Encoding"
        ):
            self.error(400, "JSON with a Content-Length is required")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.error(413, "request body is too large or empty")
                return
            self.connection.settimeout(5)
            payload = json.loads(
                self.rfile.read(length),
                parse_constant=reject_constant,
                object_pairs_hook=unique_object,
            )
            if not isinstance(payload, dict):
                raise ValueError("request must be a JSON object")
            if self.path == "/api/save":
                self.server.store.save(payload)
            elif payload:
                raise ValueError("seal request must be an empty object")
            else:
                self.server.store.seal()
            self.reply(200, b'{"ok":true}')
        except (ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
            self.error(400, str(exc))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", type=Path, default=Path(__file__).parent)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, help="LocalWork scratch for atomic label writes")
    parser.add_argument("--port", type=int, default=8784)
    args = parser.parse_args()
    if not args.source_dir.resolve().is_relative_to(LOCAL_WORK.resolve()):
        parser.error("source-dir must be inside the local Codex LocalWork directory")
    work_directory = args.work_dir or args.source_dir.resolve().parent / "label-work"
    if not work_directory.resolve().is_relative_to(LOCAL_WORK.resolve()):
        parser.error("work-dir must be inside the local Codex LocalWork directory")
    try:
        store = LabelStore(args.set, args.source_dir, work_directory)
        server = LabelServer(store, args.port)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Blind labels: http://127.0.0.1:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
