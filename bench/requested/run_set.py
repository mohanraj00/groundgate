"""Frozen requested-set orchestration with a caller-supplied transport.

This module never selects a provider or reads labels for extraction. Callers must supply
explicit frozen-file digests and an external local source/cache directory. Complete local
caches contain source quotes. Only the returned scoring projection is suitable for export.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

import groundgate as gg

from .metrics import ARMS, measure, same_request, search_limit_fields

Json = dict[str, Any]
_VERSION = "requested-run/1"
_MAX_FILE = 128 * 1024 * 1024
_MAX_TEXT = 16 * 1024 * 1024
_MAX_REPLY = 8 * 1024 * 1024
_MAX_REQUEST_CONTEXT = 4096
_ID = re.compile(r"[a-z][a-z0-9_-]{0,79}\Z")
_ROLES = {"value", "sign", "scale", "unit", "field", "key"}
_LOOP = re.compile(r"loop/[0-9]{2,}\.json\Z")
# Verbatim instruction string from the released own-model guide. The wrapper, bounded chunk
# search_region and current core are declared adaptations, not the entire released pipeline.
BASELINE_INSTRUCTIONS = """\
Extract the fields from the text. Give "value" as the fact is, as a plain number without $,
commas or a unit, with its sign and scale: a number in brackets, or a loss, is negative, and a
table "in thousands" multiplies its numbers by 1000.

Give the evidence as quotes, each copied verbatim from the text:
- role "value": the number as written, such as "(12,040)";
- role "sign": the brackets or the loss word that make the value negative, when the value quote
  does not hold them;
- role "scale": the words that scale the number, such as "(in thousands)";
- role "unit": the unit or $ sign when it is not next to the number;
- role "field": the words that name the field, such as a table row label;
- role "key": the words that name the key, such as a table column heading.
Leave out each role that the value does not need.

If no text states a value, but you know it, give a "knowledge" item that states the value and
its basis, or an "external" item with the URL of a page that states it, the date that you read
the page, and a quote from it.
"""


class CacheError(ValueError):
    """A frozen input or immutable cache no longer matches its expected bytes."""


class CachedTransportError(RuntimeError):
    """A recorded transport failure; the original exception text is never retained."""


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return gg.jcs(value).encode("utf-8")


def _json(raw: bytes) -> Json:
    def pairs(items: list[tuple[str, Any]]) -> Json:
        result: Json = {}
        for key, value in items:
            if key in result:
                raise CacheError("duplicate JSON member")
            result[key] = value
        return result

    def constant(value: str) -> Any:
        raise CacheError("non-finite JSON number")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(value, dict):
        raise CacheError("expected a JSON object")
    encoded(value)  # Reject unsafe numbers and invalid Unicode before any call.
    return value


def _read(path: Path, cap: int = _MAX_FILE) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > cap:
        raise CacheError("missing, linked or oversized input: " + path.name)
    with path.open("rb") as stream:
        raw = stream.read(cap + 1)
    if len(raw) > cap:
        raise CacheError("input grew beyond its size limit")
    return raw


def source_code_digest() -> str:
    """Hash the actual imported package code/data and this harness, including dirty edits."""
    root = Path(gg.__file__).parent
    files = {
        str(path.relative_to(root)): digest(_read(path))
        for path in sorted(root.rglob("*"))
        if path.suffix in {".py", ".json"}
    }
    files["requested/run_set.py"] = digest(_read(Path(__file__)))
    files["requested/metrics.py"] = digest(_read(Path(__file__).with_name("metrics.py")))
    return digest(encoded(files))


def _validate_blind_labels(manifest: Json, labels: Json) -> None:
    """Validate the entire pinned seal, then let the caller discard its parsed gold labels."""
    try:
        documents = manifest["documents"]
        # measure validates document membership, every requested field/key, values, units and
        # schema compatibility before filtering a split. Validate each populated split as well.
        for split in {doc["split"] for doc in documents}:
            measure(manifest, labels, {"documents": []}, split)
        by_id = {doc["id"]: doc for doc in documents}
        for gold in labels["documents"]:
            document = by_id[gold["id"]]
            page_count = document.get("source_pages")
            if page_count is not None and (type(page_count) is not int or page_count < 1):
                raise ValueError("invalid source page count")
            for slot in gold["fields"]:
                page = slot.get("page")
                if page is not None and (
                    type(page) is not int
                    or page < 1
                    or (page_count is not None and page > page_count)
                ):
                    raise ValueError("invalid label evidence page")
                if slot["status"] == "present" and page is None:
                    raise ValueError("present labels need an original PDF page")
                if slot["status"] == "unclear" and (
                    not isinstance(slot.get("reason"), str) or not slot["reason"].strip()
                ):
                    raise ValueError("unclear labels need a reason")
                if slot["status"] == "absent" and slot.get("second_check") is not True:
                    raise ValueError("absent labels need a second blind check")
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise CacheError(
            "blind labels must completely and validly cover the frozen manifest"
        ) from exc


def _validate_request_contexts(manifest: Json, labels: Json) -> None:
    """Refuse request context that changes in a kind or holds label annotation text.

    Every document of one kind gets the same scope. No subject or scope may hold a label note,
    an unclear reason or a manifest label scope note. schema() checks the context shape.
    """

    def plain(text: Any) -> str | None:
        return " ".join(text.split()) if isinstance(text, str) and text.strip() else None

    notes = {
        note
        for gold in labels["documents"]
        for slot in gold["fields"]
        for note in (plain(slot.get("note")), plain(slot.get("reason")))
        if note is not None
    }
    notes |= {
        note
        for doc in manifest["documents"]
        if (note := plain(doc.get("label_scope_note"))) is not None
    }
    scopes: dict[Any, Any] = {}
    for doc in manifest["documents"]:
        context = doc.get("request_context")
        scope = context.get("scope") if isinstance(context, dict) else None
        if scopes.setdefault(doc.get("kind"), scope) != scope:
            raise CacheError("request_context scope must be one fixed string for each kind")
        if not isinstance(context, dict):
            continue
        for member in context.values():
            text = plain(member)
            if text is not None and any(note in text for note in notes):
                raise CacheError("request_context must not hold label annotation text")


def _unlinked(path: Path) -> Path:
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise CacheError("symlink paths are not supported")
    return path.resolve()


def _external(path: Path, repository: Path) -> Path:
    path = _unlinked(path.absolute())
    if path == repository or repository in path.parents:
        raise CacheError("source and cache storage must stay outside the repository")
    return path


def _publish(path: Path, value: Json) -> None:
    """Publish complete bytes atomically without replacing an existing name."""
    raw = encoded(value)
    _unlinked(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".publish-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _same_or_publish(path: Path, value: Json, replay_only: bool = False) -> None:
    _unlinked(path)
    if path.exists():
        if _read(path) != encoded(value):
            raise CacheError("immutable cache differs: " + path.name)
    elif replay_only:
        raise CacheError("missing replay artifact: " + path.name)
    else:
        try:
            _publish(path, value)
        except FileExistsError:
            # Another process published the name first. Its bytes must be the same.
            if _read(path) != encoded(value):
                raise CacheError("immutable cache differs: " + path.name) from None


def _move(source: Path, target: Path) -> None:
    """Move a file without replacing a name: link the target first, then unlink the source."""
    _unlinked(source)
    _unlinked(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)
    source.unlink()


def _attempts(document: Path) -> int:
    """Count the archived transport attempts of one document."""
    folder = _unlinked(document / "attempts")
    if not folder.exists():
        return 0
    return sum(1 for path in folder.iterdir() if (path / "call.json").is_file())


def _archive_transport_error(document: Path, binding: str) -> bool:
    """Archive a transport error at the last call of a document, so that the call can run again.

    The entry, its reservation and the document result move to ``attempts/NNNN``. Nothing is
    deleted. A transport error before the last call stays refused. Returns True after a move.
    """
    calls = _unlinked(document / "calls")
    if not calls.exists():
        return False
    names = sorted(p.name for p in calls.glob("*.json") if ".pending." not in p.name)
    if not names:
        return False
    if names != [f"{i:04}.json" for i in range(1, len(names) + 1)]:
        raise CacheError("extra or missing cached calls")
    statuses = []
    for number, name in enumerate(names, 1):
        entry = _json(_read(calls / name))
        checksum = entry.pop("entry_sha256", None)
        if (
            checksum != digest(encoded(entry))
            or entry.get("binding_sha256") != binding
            or entry.get("sequence") != number
        ):
            raise CacheError("cached call differs")
        statuses.append(entry.get("status"))
    if "transport_error" in statuses[:-1]:
        raise CacheError("a transport error before the last call cannot be retried")
    if statuses[-1] != "transport_error":
        return False
    pending = calls / names[-1].replace(".json", ".pending.json")
    if not pending.is_file():
        raise CacheError("a transport error without its reservation cannot be retried")
    target = document / "attempts" / f"{_attempts(document) + 1:04}"
    if target.exists():
        raise CacheError("an incomplete transport attempt archive needs inspection")
    result = document / "result.json"
    if result.exists():
        _move(result, target / "result.json")
    _move(pending, target / "call.pending.json")
    _move(calls / names[-1], target / "call.json")
    return True


def _settings(raw: Any) -> Json:
    """Check the frozen runner settings. ``drop_rounded`` is optional and must be false: the
    main runner arm keeps the 0.10 default, and only the replay arm turns the rule on (#376)."""
    if isinstance(raw, dict) and "drop_rounded" in raw:
        if raw["drop_rounded"] is not False:
            raise CacheError("drop_rounded must be false; the runner_drop_rounded arm sets it")
        raw = {k: v for k, v in raw.items() if k != "drop_rounded"}
    if not isinstance(raw, dict) or set(raw) != {
        "chunk_chars",
        "overlap_chars",
        "max_repair_rounds",
        "targeted",
        "search_context_chars",
        "max_target_regions",
        "max_calls",
        "max_prompt_chars",
        "max_reply_bytes",
        "max_candidates_per_reply",
        "max_total_candidates",
        "max_admission_bytes",
    }:
        raise CacheError("freeze every runner setting explicitly")
    for name, value in raw.items():
        if name == "targeted":
            if type(value) is not bool:
                raise CacheError("targeted must be boolean")
        elif type(value) is not int or value < (
            0 if name in {"overlap_chars", "max_repair_rounds"} else 1
        ):
            raise CacheError("invalid runner setting")
    if raw["overlap_chars"] >= raw["chunk_chars"]:
        raise CacheError("overlap must be smaller than chunk size")
    caps = {
        "chunk_chars": _MAX_TEXT,
        "max_repair_rounds": 16,
        "search_context_chars": _MAX_TEXT,
        "max_target_regions": 64,
        "max_calls": 256,
        "max_prompt_chars": 1024 * 1024,
        "max_reply_bytes": 4 * 1024 * 1024,
        "max_candidates_per_reply": 1024,
        "max_total_candidates": 4096,
        "max_admission_bytes": 32 * 1024 * 1024,
    }
    if any(raw[name] > cap for name, cap in caps.items()):
        raise CacheError("runner setting exceeds harness processing cap")
    return copy.deepcopy(raw)


def chunks(text: str, settings: Json) -> list[tuple[int, int]]:
    """The fixed shared initial chunk algorithm, including newline break and terminal stop."""
    result = []
    start = 0
    while start < len(text):
        end = min(len(text), start + settings["chunk_chars"])
        if end < len(text):
            newline = text.rfind("\n", start + (end - start) // 2, end)
            if newline >= 0:
                end = newline + 1
        result.append((start, end))
        if len(result) > settings["max_calls"]:
            raise CacheError("initial chunks exceed the frozen call budget")
        if end == len(text):
            break
        start = max(start + 1, end - settings["overlap_chars"])
    return result


class _Calls:
    def __init__(
        self,
        owner: FrozenSet,
        folder: Path,
        binding: str,
        client: Callable[[str], str] | None,
        missing_message: str = "missing replay call",
    ):
        self.owner, self.folder, self.binding, self.client = owner, folder, binding, client
        self.missing_message = missing_message
        self.count = 0
        self.missing = False
        self.failure: CacheError | None = None
        self.transport_error = False

    def __call__(self, prompt: str) -> str:
        try:
            return self._invoke(prompt)
        except CacheError as exc:
            self.failure = exc
            raise

    def _invoke(self, prompt: str) -> str:
        _unlinked(self.folder)
        self.owner.check_inputs()
        self.count += 1
        if self.count > self.owner.settings["max_calls"]:
            raise CacheError("call budget exceeded")
        if len(prompt) > self.owner.settings["max_prompt_chars"]:
            raise CacheError("prompt budget exceeded")
        path = self.folder / f"{self.count:04}.json"
        pending = self.folder / f"{self.count:04}.pending.json"
        request = {
            "binding_sha256": self.binding,
            "sequence": self.count,
            "prompt": prompt,
            "prompt_sha256": digest(prompt.encode()),
        }
        if path.exists():
            entry = _json(_read(path))
            checksum = entry.pop("entry_sha256", None)
            if checksum != digest(encoded(entry)) or any(
                entry.get(k) != v for k, v in request.items()
            ):
                raise CacheError("cached call differs")
            _same_or_publish(pending, request, replay_only=True)
        else:
            if self.client is None:
                self.missing = True
                raise CacheError(self.missing_message)
            if pending.exists():
                raise CacheError("unresolved call reservation; automatic retry refused")
            _publish(pending, request)
            entry = dict(request)
            try:
                reply = self.client(prompt)
            except Exception as exc:
                entry |= {"status": "transport_error", "exception_type": type(exc).__name__}
            else:
                if not isinstance(reply, str):
                    entry |= {"status": "reply_type"}
                else:
                    try:
                        raw = reply.encode("utf-8")
                    except UnicodeError:
                        entry |= {"status": "reply_encoding"}
                    else:
                        entry |= {"reply_sha256": digest(raw), "reply_bytes": len(raw)}
                        if len(raw) > _MAX_REPLY:
                            entry |= {"status": "transport_reply_limit"}
                        else:
                            entry |= {"status": "ok", "reply": reply}
            entry["entry_sha256"] = digest(encoded(entry))
            _publish(path, entry)
        if entry["status"] != "ok":
            self.transport_error = True
            raise CachedTransportError(entry["status"])
        reply = entry["reply"]
        if not isinstance(reply, str) or digest(reply.encode()) != entry["reply_sha256"]:
            raise CacheError("cached reply differs")
        if len(reply.encode()) != entry["reply_bytes"] or entry["reply_bytes"] > _MAX_REPLY:
            raise CacheError("cached reply length differs")
        return reply

    def finish(self) -> None:
        if self.failure is not None:
            raise self.failure
        if self.missing:
            raise CacheError("replay requires every recorded call")
        if self.folder.exists():
            completed = sorted(
                p.name for p in self.folder.glob("*.json") if ".pending." not in p.name
            )
            if completed != [f"{i:04}.json" for i in range(1, self.count + 1)]:
                raise CacheError("extra or missing cached calls")


def _baseline_reply(raw: str, schema: Json, limit: int) -> list[Json]:
    reply = _json(raw.encode())
    if set(reply) != {"candidates"} or not isinstance(reply["candidates"], list):
        raise CacheError("baseline expects only a candidates envelope")
    if len(reply["candidates"]) > limit:
        raise CacheError("too many candidates")
    for candidate in reply["candidates"]:
        if not isinstance(candidate, dict) or set(candidate) != {
            "field",
            "value",
            "unit",
            "key",
            "evidence",
        }:
            raise CacheError("invalid baseline candidate members")
        field = candidate["field"]
        if (
            not isinstance(field, str)
            or field not in schema["fields"]
            or not isinstance(candidate["value"], str)
        ):
            raise CacheError("invalid baseline field or value")
        if any(
            candidate[k] is not None and not isinstance(candidate[k], str) for k in ("unit", "key")
        ):
            raise CacheError("invalid baseline key or unit")
        if not isinstance(candidate["evidence"], list):
            raise CacheError("invalid evidence list")
        for item in candidate["evidence"]:
            if not isinstance(item, dict):
                raise CacheError("invalid evidence item")
            source = item.get("source")
            keys = {
                "document": {"source", "role", "text"},
                "knowledge": {"source", "text"},
                "external": {"source", "url", "retrieved", "text"},
            }
            if not isinstance(source, str) or source not in keys or set(item) != keys[source]:
                raise CacheError("invalid evidence members")
            if any(not isinstance(v, str) for v in item.values()):
                raise CacheError("evidence members must be strings")
            if source == "document" and item["role"] not in _ROLES:
                raise CacheError("invalid evidence role")
    return reply["candidates"]


def _prompts(result: Json) -> list[Any]:
    """The prompt digests of the model calls in a runner result, in order."""
    record = result.get("record")
    if not isinstance(record, list) or any(not isinstance(e, dict) for e in record):
        raise CacheError("a runner result needs its record")
    return [e.get("prompt_sha256") for e in record if e.get("kind") == "call"]


def _projection(decision: Json) -> Json:
    return {
        k: decision[k]
        for k in ("candidate_id", "field", "key", "value", "unit", "outcome", "codes")
    }


def storage_outcomes(rounds: list[Json], schema: Json) -> list[Json]:
    """Released app storage, applied to independently admitted rounds and chunks."""
    decisions = [d for round_ in rounds for d in round_["receipt"]["decisions"]]
    admitted: dict[tuple[Any, Any], set[tuple[Any, Any]]] = defaultdict(set)
    for d in decisions:
        if d["outcome"] == "admitted":
            admitted[d["field"], d["key"]].add((d["value"], d["unit"]))
    result = []
    for d in decisions:
        out = _projection(d) | {"origin": "application_storage", "core_outcome": d["outcome"]}
        sigs = admitted[d["field"], d["key"]]
        if (
            d["outcome"] == "admitted"
            and not schema["fields"][d["field"]].get("multiple", False)
            and len(sigs) > 1
        ):
            out |= {
                "outcome": "needs_verification",
                "application_reason": "conflicting_round_admits",
            }
        result.append(out)
    return result


class FrozenSet:
    """A file-bound run session. Construct only after the complete set has been frozen."""

    def __init__(
        self,
        directory: Path,
        sources: Path,
        cache: Path,
        configuration: Path,
        *,
        manifest_sha256: str,
        labels_sha256: str,
        configuration_sha256: str,
    ):
        self.directory = _unlinked(directory.absolute())
        repository = Path(__file__).resolve().parents[2]
        self.sources = _external(sources, repository)
        self.cache = _external(cache, repository)
        self.paths = {
            self.directory / "manifest.json": manifest_sha256,
            self.directory / "labels.json": labels_sha256,
            _unlinked(configuration.absolute()): configuration_sha256,
        }
        raw = {path: _read(path) for path in self.paths}
        if any(digest(raw[path]) != sha for path, sha in self.paths.items()):
            raise CacheError("frozen file digest differs")
        self.manifest = _json(raw[self.directory / "manifest.json"])
        if (
            self.manifest.get("status") != "frozen"
            or self.manifest.get("selection_complete") is not True
        ):
            raise CacheError("complete manifest must be frozen")
        # Validate the full seal before any client/cache work, without retaining parsed gold.
        gold = _json(raw[self.directory / "labels.json"])
        _validate_blind_labels(self.manifest, gold)
        try:
            _validate_request_contexts(self.manifest, gold)
        except (KeyError, TypeError, AttributeError) as exc:
            raise CacheError("request_context check needs a valid manifest") from exc
        del gold
        self.config = _json(raw[_unlinked(configuration.absolute())])
        if set(self.config) != {
            "model_id",
            "transport",
            "policy",
            "run_policy",
            "code_sha256",
            "source_commit",
            "reader",
            "baseline_guide_commit",
        }:
            raise CacheError("unknown or missing frozen configuration member")
        for name in ("model_id", "source_commit", "baseline_guide_commit"):
            if not isinstance(self.config[name], str) or not self.config[name].strip():
                raise CacheError("missing provenance: " + name)
        for name, keys in (
            ("transport", {"id", "version", "effort"}),
            ("reader", {"id", "commit", "code_sha256"}),
        ):
            value = self.config[name]
            if (
                not isinstance(value, dict)
                or set(value) != keys
                or any(not isinstance(v, str) or not v.strip() for v in value.values())
            ):
                raise CacheError("incomplete provenance: " + name)
        self.settings = _settings(self.config["run_policy"])
        self.policy = gg.Policy.from_dict(self.config["policy"]).to_dict()
        if self.policy["sources"] != gg.Policy.from_dict({}).to_dict()["sources"]:
            raise CacheError("freeze default external and knowledge review policy")
        self.code_sha256 = source_code_digest()
        if self.code_sha256 != self.config["code_sha256"]:
            raise CacheError("source code digest differs")
        documents = self.manifest.get("documents")
        if not isinstance(documents, list) or not documents:
            raise CacheError("manifest has no documents")
        self.documents: dict[str, Json] = {}
        self.texts: dict[str, str] = {}
        total = 0
        for doc in documents:
            ident = doc.get("id")
            if not isinstance(ident, str) or not _ID.fullmatch(ident) or ident in self.documents:
                raise CacheError("unsafe or duplicate document id")
            if doc.get("split") not in {"development", "heldout"}:
                raise CacheError("unknown split")
            for suffix, member, cap in (
                (".pdf", "source_sha256", _MAX_FILE),
                (".txt", "text_sha256", _MAX_TEXT),
            ):
                path = _unlinked(self.sources / (ident + suffix))
                body = _read(path, cap)
                if digest(body) != doc.get(member):
                    raise CacheError("source or reader text digest differs: " + ident)
                self.paths[path] = doc[member]
                if suffix == ".pdf":
                    if (
                        len(body) != doc.get("source_bytes")
                        or type(doc.get("approved_max_bytes")) is not int
                        or len(body) > doc["approved_max_bytes"]
                    ):
                        raise CacheError("source size differs or exceeds approval")
                else:
                    text = body.decode("utf-8")
                    if unicodedata.normalize("NFC", text) != text:
                        raise CacheError("reader text must already be NFC")
                    total += len(body)
                    if total > _MAX_FILE:
                        raise CacheError("set text exceeds processing limit")
                    self.texts[ident] = text
            schema = self.schema(doc)
            gg.admit(self.texts[ident], schema, [], self.policy)
            self.documents[ident] = copy.deepcopy(doc)
        self._manifest_state_sha256 = digest(encoded(self.manifest))
        self._documents_state_sha256 = digest(encoded(self.documents))
        # Commit, reader and transport labels are caller declarations. Actual imported code,
        # configuration and source/text bytes are independently pinned and checked here.
        self.header = {
            "harness": _VERSION,
            "manifest_sha256": manifest_sha256,
            "labels_sha256": labels_sha256,
            "configuration_sha256": configuration_sha256,
            "configuration": self.config,
            "code_sha256": self.code_sha256,
            "baseline_instructions_sha256": digest(BASELINE_INSTRUCTIONS.encode()),
            "baseline_adapter": (
                "released feedback loop; same current core; shared chunks; "
                "chunk search_region; separate application storage"
            ),
            "transport_reply_retention_limit": _MAX_REPLY,
        }
        self.binding = digest(encoded(self.header))

    def _check_heldout_freeze(self) -> None:
        """Refuse a held-out run of a set with a split rule or a held-out freeze (#383).

        The run configuration, the manifest code_freeze and the imported code must have one
        code digest. The freeze names the last learning-loop record. The cache keeps one
        held-out binding for the set: a held-out run measures a frozen change once. A set
        without a split_rule and without a held-out freeze keeps its earlier behavior.
        """
        freeze = self.manifest.get("code_freeze")
        if "split_rule" not in self.manifest and not (
            isinstance(freeze, dict) and freeze.get("applies_to") == "heldout"
        ):
            return
        if (
            not isinstance(freeze, dict)
            or freeze.get("applies_to") != "heldout"
            or not isinstance(freeze.get("last_loop"), str)
            or not _LOOP.fullmatch(freeze["last_loop"])
        ):
            raise CacheError(
                "a held-out run needs a code_freeze that applies to heldout and names its last loop"
            )
        if not (freeze.get("code_sha256") == self.config["code_sha256"] == source_code_digest()):
            raise CacheError("a held-out run needs the frozen code digest in config and code")
        if self.cache.exists():
            for other in _unlinked(self.cache).iterdir():
                if other.name == self.binding.removeprefix("sha256:"):
                    continue
                if any(_unlinked(other / arm / "heldout").exists() for arm in ARMS):
                    raise CacheError("the cache already holds another held-out binding of the set")

    def schema(self, doc: Json) -> Json:
        """Return a fresh schema with only explicit pre-label request context appended.

        Each context member is bounded to 4096 Unicode characters. Combined serialized
        description content must fit max_prompt_chars before context is repeated. Canonical
        JSON distinguishes subject and scope without reading label or source-note members.
        """
        template = self.manifest["schemas"][doc["kind"]]
        schema = doc.get("schema", template)
        if not same_request(template, schema):
            raise CacheError("document schema changes fixed requests or types")
        effective = gg.Schema.from_dict(schema).to_dict()
        if "request_context" in doc:
            context = doc["request_context"]
            if (
                not isinstance(context, dict)
                or set(context) != {"subject", "scope"}
                or any(
                    not isinstance(value, str)
                    or not value.strip()
                    or len(value) > _MAX_REQUEST_CONTEXT
                    for value in context.values()
                )
            ):
                raise CacheError(
                    "request_context requires only nonblank subject and scope strings "
                    "of at most 4096 characters each"
                )
            suffix = "Request context: " + encoded(context).decode()
            # Count JSON string content before allocating a copy of the suffix per field.
            # The cheap length check also avoids serializing a huge existing description.
            remaining = self.settings["max_prompt_chars"]
            suffix_chars = len(gg.jcs(suffix)) - 2
            for field in effective["fields"].values():
                description = field.get("description")
                separator_chars = 4 if description is not None else 0  # Two escaped newlines.
                if len(description or "") + separator_chars + suffix_chars > remaining:
                    raise CacheError("request_context descriptions exceed frozen prompt budget")
                remaining -= suffix_chars + separator_chars
                if description is not None:
                    remaining -= len(gg.jcs(description)) - 2
                if remaining < 0:
                    raise CacheError("request_context descriptions exceed frozen prompt budget")
            for field in effective["fields"].values():
                description = field.get("description")
                field["description"] = (
                    description + "\n\n" + suffix if description is not None else suffix
                )
        return effective

    def check_inputs(self) -> None:
        if (
            digest(encoded(self.manifest)) != self._manifest_state_sha256
            or digest(encoded(self.documents)) != self._documents_state_sha256
        ):
            raise CacheError("frozen manifest or document metadata changed in memory")
        if any(digest(_read(path)) != sha for path, sha in self.paths.items()):
            raise CacheError("frozen source, text, label, manifest or configuration changed")
        if source_code_digest() != self.code_sha256:
            raise CacheError("source code changed")

    def _prompt(self, text: str, schema: Json, start: int, end: int, feedback: str | None) -> str:
        body = {
            "instructions": BASELINE_INSTRUCTIONS,
            "schema": schema,
            "text": text[start:end],
            "output_format": gg.extractor_schema(schema),
            "chunk": {"start": len(text[:start].encode()), "end": len(text[:end].encode())},
        }
        if feedback is not None:
            body["feedback"] = feedback
        return encoded(body).decode()

    def _baseline(self, ident: str, calls: _Calls) -> Json:
        text, doc = self.texts[ident], self.documents[ident]
        schema = self.schema(doc)
        plan = chunks(text, self.settings)
        for start, end in plan:
            if (
                len(self._prompt(text, schema, start, end, None))
                > self.settings["max_prompt_chars"]
            ):
                raise CacheError("baseline initial prompt exceeds frozen budget")
        rounds: list[Json] = []
        complete, stop = True, None
        count, history = 0, 0
        for chunk, (start, end) in enumerate(plan, 1):
            feedback = None
            for retry in (False, True):
                prompt = self._prompt(text, schema, start, end, feedback)
                if (
                    len(prompt) > self.settings["max_prompt_chars"]
                    or calls.count >= self.settings["max_calls"]
                ):
                    complete, stop = (
                        False,
                        "prompt_limit"
                        if len(prompt) > self.settings["max_prompt_chars"]
                        else "call_limit",
                    )
                    break
                try:
                    raw = calls(prompt)
                except CachedTransportError:
                    complete, stop = False, "transport_error"
                    break
                try:
                    if len(raw.encode()) > self.settings["max_reply_bytes"]:
                        raise CacheError("baseline reply parsing limit")
                    proposed = _baseline_reply(
                        raw, schema, self.settings["max_candidates_per_reply"]
                    )
                except (ValueError, TypeError, RecursionError, UnicodeError):
                    complete, stop = False, "invalid_reply"
                    break
                if count + len(proposed) > self.settings["max_total_candidates"]:
                    complete, stop = False, "candidate_limit"
                    break
                packet = []
                for i, candidate in enumerate(proposed, 1):
                    item = copy.deepcopy(candidate) | {
                        "id": f"chunk{chunk}-{'retry' if retry else 'initial'}-{i}"
                    }
                    if any(e["source"] == "document" for e in item["evidence"]):
                        item["search_region"] = {
                            "start": len(text[:start].encode()),
                            "end": len(text[:end].encode()),
                        }
                    packet.append(item)
                receipt = gg.admit(
                    text,
                    schema,
                    packet,
                    self.policy,
                    document_id=ident,
                    document_source=doc["source"],
                )
                record = {
                    "chunk": chunk,
                    "retry": retry,
                    "candidates": packet,
                    "receipt": receipt.to_dict(),
                }
                history += len(encoded(record))
                if history > self.settings["max_admission_bytes"]:
                    complete, stop = False, "admission_history_limit"
                    break
                if not gg.verify(
                    receipt.to_dict(),
                    text,
                    schema,
                    packet,
                    self.policy,
                    document_source=doc["source"],
                ).ok:
                    raise CacheError("baseline receipt did not verify")
                rounds.append(record)
                count += len(packet)
                if retry:
                    break
                by_id = {c["id"]: c for c in packet}
                messages = [
                    gg.feedback_message(d, by_id[d.candidate_id], schema, text=text)
                    for d in sorted(receipt.decisions, key=lambda d: d.candidate_id)
                ]
                eligible = [m for m in messages if m is not None]
                if not eligible:
                    break
                feedback = "\n".join(eligible)
            if not complete:
                break
        outcomes = storage_outcomes(rounds, schema)
        return {
            "rounds": rounds,
            "application_outcomes": outcomes,
            "complete": complete,
            "stop": stop,
            "output": {"id": ident, "decisions": outcomes, "not_found": []},
        }

    def run(
        self,
        arm: str,
        client: Callable[[str], str] | None = None,
        *,
        split: str = "heldout",
        documents: Collection[str] | None = None,
        retry_transport_errors: bool = False,
    ) -> Json:
        """Run one arm, or replay it with client=None. Never overwrite cache artifacts.

        ``documents`` runs only those documents of the split, so separate processes can fill the
        cache in parallel. A partial run publishes no projection; a later run of the whole split
        reuses the completed documents without transport.

        ``retry_transport_errors`` archives a transport error at the last call of a document,
        with its reservation, its result and the split projection, then runs that call again.
        It needs a client. The projection records the retries of each document.

        ``runner_drop_rounded`` runs the runner with ``drop_rounded`` on (#376). It takes no
        client and makes no model call: it reads the recorded calls of the ``runner`` arm of the
        same split, in order, and checks each prompt against its record. A missing, extra or
        changed call stops the run. The rounding step runs after the last model call, so each
        prompt is the same as in the main arm. It publishes its own results and projection.
        """
        if arm not in ARMS or split not in {"development", "heldout"}:
            raise CacheError("unknown arm or split")
        replayed = arm == "runner_drop_rounded"
        if replayed and client is not None:
            raise CacheError(
                "the runner_drop_rounded arm takes no client: "
                "it replays the recorded calls of the runner arm"
            )
        if retry_transport_errors and client is None:
            raise CacheError("a transport retry needs a client")
        selected = None
        if documents is not None:
            selected = set(documents)
            known = {i for i, d in self.documents.items() if d["split"] == split}
            if not selected or not selected <= known:
                raise CacheError("documents must be a nonempty subset of the split")
        if split == "heldout":
            self._check_heldout_freeze()
        runner_api = None
        if arm != "baseline":
            try:
                from groundgate.extract import RunPolicy, extract, replay
            except ImportError as exc:
                raise CacheError("runner execution requires the integrated runner API") from exc
            runner_api = (RunPolicy, replay, extract)
        self.check_inputs()
        root = self.cache / self.binding.removeprefix("sha256:")
        folder = root / arm / split
        _unlinked(folder)
        # The replay arm publishes its own artifacts, because it never has a client.
        replay_only = client is None and not replayed
        recorded = root / "runner" / split
        if replayed:
            # The main runner arm must have run this split with the same binding.
            _same_or_publish(
                recorded / "header.json", self.header | {"arm": "runner", "split": split}, True
            )
        _same_or_publish(
            folder / "header.json", self.header | {"arm": arm, "split": split}, replay_only
        )
        outputs = []
        for ident, doc in sorted(self.documents.items()):
            if doc["split"] != split or (selected is not None and ident not in selected):
                continue
            binding = digest(
                encoded({"run": self.binding, "arm": arm, "split": split, "document": ident})
            )
            if retry_transport_errors and _archive_transport_error(folder / ident, binding):
                projection = folder / "projection.json"
                if projection.exists():
                    archive = folder / "_attempts"
                    count = len(list(archive.glob("projection-*.json"))) if archive.exists() else 0
                    _move(projection, archive / f"projection-{count + 1:04}.json")
            main: Json | None = None
            if replayed:
                if not _unlinked(recorded / ident / "result.json").is_file():
                    raise CacheError("the runner arm has no result to replay: " + ident)
                main = _json(_read(recorded / ident / "result.json"))
                source = digest(
                    encoded(
                        {"run": self.binding, "arm": "runner", "split": split, "document": ident}
                    )
                )
                calls = _Calls(
                    self,
                    recorded / ident / "calls",
                    source,
                    None,
                    "missing recorded call of the runner arm; the replay arm makes no model call",
                )
            else:
                calls = _Calls(self, folder / ident / "calls", binding, client)
            if arm == "baseline":
                local = self._baseline(ident, calls)
            else:
                assert runner_api is not None
                settings_type, replay_runner, run_runner = runner_api
                result = run_runner(
                    self.texts[ident],
                    self.schema(doc),
                    client=calls,
                    model_id=self.config["model_id"],
                    policy=self.policy,
                    run_policy=settings_type(**self.settings, drop_rounded=replayed),
                    document_id=ident,
                    document_source=doc["source"],
                )
                if not replay_runner(
                    result.record,
                    result.artifacts,
                    self.texts[ident],
                    self.schema(doc),
                    self.policy,
                ).ok:
                    raise CacheError("runner record did not replay")
                decisions = [
                    _projection(d.to_dict()) | {"origin": "core_receipt"}
                    for d in result.receipt.decisions
                ]
                represented = {c["field"] for c in result.candidates}
                searches = {e["field"]: e for e in result.record if e["kind"] == "search"}
                missing = []
                for field, states in result.record[-1]["fields"].items():
                    spec = self.schema(doc)["fields"][field]
                    searched = searches.get(field, {})
                    completed = (
                        "empty_source" in states
                        or "targeted_not_found" in states
                        or "search_no_match" in states
                        or (not self.settings["targeted"] and "model_not_found" in states)
                    )
                    if (
                        result.complete
                        and field not in represented
                        and completed
                        and searched.get("status") != "search_truncated"
                        and not spec.get("keys")
                    ):
                        missing.append({"field": field, "key": None})
                local = {
                    "record": result.record,
                    "artifacts": result.artifacts,
                    "candidates": result.candidates,
                    "receipt": result.receipt.to_dict(),
                    "complete": result.complete,
                    "output": {"id": ident, "decisions": decisions, "not_found": missing},
                }
            calls.finish()
            # The runner result must come from the same recorded calls as this replay.
            if main is not None and (
                main.get("binding_sha256") != self.binding or _prompts(main) != _prompts(local)
            ):
                raise CacheError("the runner result does not match its recorded calls: " + ident)
            self.check_inputs()
            local |= {
                "binding_sha256": self.binding,
                "source_sha256": doc["source_sha256"],
                "text_sha256": doc["text_sha256"],
                "schema_sha256": digest(encoded(self.schema(doc))),
                "policy_sha256": digest(encoded(self.policy)),
            }
            _same_or_publish(folder / ident / "result.json", local, replay_only)
            outputs.append(
                local["output"]
                | {
                    "complete": local["complete"],
                    "transport_error": calls.transport_error,
                    "transport_retries": _attempts((recorded if replayed else folder) / ident),
                    # The baseline arm has no targeted search, so no field stops there.
                    "search_limit": 0
                    if arm == "baseline"
                    else search_limit_fields(local["record"]),
                }
            )
        if selected is not None:
            return {"arm": arm, "split": split, "documents": outputs, "partial": True}
        public = {
            "manifest_sha256": self.header["manifest_sha256"],
            "labels_sha256": self.header["labels_sha256"],
            "binding_sha256": self.binding,
            "arm": arm,
            "split": split,
            "documents": outputs,
            "provenance": self.header,
        }
        _same_or_publish(folder / "projection.json", public, replay_only)
        return public
