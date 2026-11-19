"""The review API: the review step over HTTP (SPEC §4.20, #649).

A program reads the open tasks of a store and writes answers. ``Service`` gives the four
operations of version 1, and ``server`` puts it behind an HTTP server on 127.0.0.1:

- ``GET /v1/tasks``: the open tasks of the actor, with a page cursor.
- ``GET /v1/tasks/{task}``: one task, with the statements of a model text.
- ``GET /v1/tasks/{task}/document``: the text of its document.
- ``POST /v1/answers``: one answer.

Each request carries a claim. ``check_claim`` verifies a signed claim against the issuers of
the service, and ``check_static`` compares a static token for a local run. The actor of the
claim is the reviewer of the answer.

The service keeps no state outside the store. It opens the store for each request, and
``groundgate.review.serve.Review`` decides each packet again. The answer goes through
``Review.write``, the same call as the page of ``groundgate review serve``, so the two give the
same record.

A task with the mode ``audit`` is blind: no response gives its value, its unit, its evidence,
its places, its codes, its item or its question (SPEC §4.18).

No response gives a key of the store. A store key is a hash of its content, and the object of
a blind task holds the proposed value. So does its packet, and the key of each other task of
that packet is a hash over the packet key. With one such key, a person could test a guess of
the value with no request. So a task has an opaque ID, an HMAC of its task key with a random
key that the service makes at its start, and ``no_keys`` takes each store key out of a task
body and an answer record.

No response gives an index of the receipt. The receipt sorts its decisions by the digest of
the candidate, so the indexes of one task tell where the candidate of a blind task of the same
packet is in that order. A choice has its number in its task, and an answer names a choice by
that number.

The store data and each request are untrusted.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import threading
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .labels import QUESTIONS
from .resolve import CORRECTIONS, VERDICTS
from .serve import MAX_BODY, MAX_PARTS, ROLES, Refused, Review, _printable
from .tasks import DEFAULT_POLICY, check_policy

__all__ = [
    "API",
    "AUDIENCE",
    "BLIND_VERDICTS",
    "STATUS",
    "TASK_LABEL",
    "ApiError",
    "Issuers",
    "Service",
    "Static",
    "check_body",
    "check_claim",
    "check_static",
    "list_page",
    "no_keys",
    "read_issuers",
    "read_token",
    "server",
    "statement_list",
    "task_id",
    "task_view",
]

API = "groundgate-review/1"
AUDIENCE = "groundgate-review"
ISSUERS_FORMAT = 1
MAX_CLAIM = 4096
MAX_ACTOR = 128
MIN_SECRET = 32
MAX_SECRET = 1024
DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_CODES = 64
CSP = "default-src 'none'; frame-ancestors 'none'"
BLIND_VERDICTS = frozenset({"correct", "not_in_document", "unsure"})
TASK_LABEL = b"groundgate-review-task/1:"
ID_KEY_BYTES = 32
STATUS = {
    "wrong_host": 421,
    "no_claim": 401,
    "bad_claim": 401,
    "unknown_issuer": 401,
    "expired_claim": 401,
    "not_found": 404,
    "method_not_allowed": 405,
    "bad_request": 400,
    "unsupported_media_type": 415,
    "length_required": 411,
    "body_too_large": 413,
    "bad_answer": 400,
    "correction_rejected": 409,
    "codes_not_kept": 409,
    "parts_disagree": 409,
    "log_refused": 409,
    "server_error": 500,
}
_KEY = re.compile(r"sha256:[0-9a-f]{64}")  # a key of the store
_ID = re.compile(r"task:[0-9a-f]{64}")  # a task ID
# a key of the store in a message, with or without its prefix, as a store path can have it
_HASH = re.compile(r"(?:sha256[:_-])?[0-9a-f]{64}")
_B64 = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN = re.compile(r"[A-Za-z0-9._~-]{32,512}")
_CODE = re.compile(r"[A-Z][A-Z0-9_]*")
_DIGITS = re.compile(r"[0-9]{1,3}")
_LIMIT = 2**31  # keys and ms
_OFFSET = 2**53  # a span offset
_BODY = frozenset({
    "task", "verdict", "choice", "span", "value", "parts", "codes_kept", "parts_seen",
    "statements", "reason_seen", "keys", "ms",
})  # fmt: skip
_TASK = re.compile(r"/v1/tasks/(task:[0-9a-f]{64})(/document)?")


class ApiError(Exception):
    """A request that the API refuses. ``code`` is an error code of SPEC §4.20. The message
    gives no key of the store: a message from the store can name a log or an object by its
    key."""

    def __init__(self, code: str, message: str, codes: Iterable[str] | None = None) -> None:
        message = _HASH.sub("(a key of the store)", message)
        super().__init__(message)
        self.code = code
        self.message = message
        self.codes = None if codes is None else list(codes)

    @property
    def status(self) -> int:
        return STATUS[self.code]


# The claim


@dataclass(frozen=True)
class Issuers:
    """The issuers of a service: the secret of each issuer name."""

    secrets: Mapping[str, bytes]


@dataclass(frozen=True)
class Static:
    """The static token of a local service, and the reviewer name of its one user."""

    token: str
    reviewer: str


def _actor(name: object, what: str) -> str:
    """A reviewer name: NFC, 1 to 128 characters, one that is not a space, and with UTF-8."""
    if not isinstance(name, str) or not 1 <= len(name) <= MAX_ACTOR or not name.strip():
        raise ValueError(f"{what} must be a string of 1 to {MAX_ACTOR} characters, not only spaces")
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{what} has a lone surrogate") from None
    if not unicodedata.is_normalized("NFC", name):
        raise ValueError(f"{what} must be NFC text")
    return name


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(part: str) -> bytes | None:
    """The bytes of a base64url part with no ``=``, or None. A part with bits after its last
    byte is not valid, so one claim has one text."""
    if not _B64.fullmatch(part) or len(part) % 4 == 1:
        return None
    try:
        data = base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
    except (binascii.Error, ValueError):
        return None
    return data if _b64(data) == part else None


def _object(part: str) -> dict[str, Any] | None:
    data = _unb64(part)
    if data is None:
        return None
    try:
        obj = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):  # ValueError: also bytes that are not UTF-8
        return None
    return obj if isinstance(obj, dict) else None


def _bearer(authorization: Sequence[str]) -> str:
    """The text after ``Bearer`` and one space in the one Authorization header."""
    if not authorization:
        raise ApiError("no_claim", "the request has no Authorization header")
    if len(authorization) != 1 or not authorization[0].startswith("Bearer "):
        raise ApiError("bad_claim", "send one header: Authorization: Bearer and the claim")
    return authorization[0][len("Bearer ") :]


def check_claim(authorization: Sequence[str], issuers: Issuers, now: int) -> str:
    """The actor of a signed claim (SPEC §4.20, steps 1 to 8). ``authorization`` holds the value
    of each Authorization header of the request, and ``now`` is the time in whole seconds."""
    claim = _bearer(authorization)
    bad = ApiError("bad_claim", "the claim is not valid")
    parts = claim.split(".")
    if len(claim) > MAX_CLAIM or len(parts) != 3:  # a valid claim is ASCII
        raise bad
    header, payload, signature = _object(parts[0]), _object(parts[1]), _unb64(parts[2])
    if header is None or payload is None or signature is None:
        raise bad
    if header.get("alg") != "HS256" or set(header) - {"alg", "typ"}:
        raise bad
    if "typ" in header and header["typ"] != "JWT":
        raise bad
    issuer = payload.get("iss")
    secret = issuers.secrets.get(issuer) if isinstance(issuer, str) else None
    if secret is None:
        raise ApiError("unknown_issuer", "the service does not have the issuer of the claim")
    signed = f"{parts[0]}.{parts[1]}".encode("ascii")
    if not hmac.compare_digest(signature, hmac.new(secret, signed, hashlib.sha256).digest()):
        raise bad
    if payload.get("aud") != AUDIENCE:
        raise bad
    exp = payload.get("exp")
    if type(exp) is not int:
        raise bad
    if exp <= now:
        raise ApiError("expired_claim", "the claim expired")
    if "nbf" in payload and (type(payload["nbf"]) is not int or payload["nbf"] > now):
        raise bad
    try:
        return _actor(payload.get("sub"), "sub")
    except ValueError:
        raise bad from None


def check_static(authorization: Sequence[str], static: Static) -> str:
    """The actor of a request to a service with a static token (SPEC §4.20)."""
    sent = _bearer(authorization).encode("utf-8", "surrogateescape")
    if not hmac.compare_digest(sent, static.token.encode("ascii")):
        raise ApiError("bad_claim", "the token is not the token of the service")
    return static.reviewer


def read_token(text: str, reviewer: str) -> Static:
    """The static token of a token file, with the reviewer name of the service. The token is
    the text of the file without the white space at its ends."""
    token = text.strip()
    if not _TOKEN.fullmatch(token):
        raise ValueError(
            "the static token must have 32 to 512 characters from A-Z, a-z, 0-9, '-', '.', '_' "
            "and '~'"
        )
    return Static(token, _actor(reviewer, "the reviewer name"))


def read_issuers(obj: object) -> Issuers:
    """The issuers of an issuers file: ``{"groundgate_review_issuers": 1, "issuers": [{"issuer":
    name, "secret": base64url}]}``. A secret has 32 bytes or more."""
    if not isinstance(obj, dict) or set(obj) != {"groundgate_review_issuers", "issuers"}:
        raise ValueError("an issuers file has the members groundgate_review_issuers and issuers")
    if (
        type(obj["groundgate_review_issuers"]) is not int
        or obj["groundgate_review_issuers"] != ISSUERS_FORMAT
    ):
        raise ValueError(f"groundgate_review_issuers must be {ISSUERS_FORMAT}")
    entries = obj["issuers"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("issuers must be a list of one or more issuers")
    secrets: dict[str, bytes] = {}
    for e in entries:
        if not isinstance(e, dict) or set(e) != {"issuer", "secret"}:
            raise ValueError("each issuer has the members issuer and secret")
        name, secret = e["issuer"], e["secret"]
        if not isinstance(name, str) or not 1 <= len(name) <= 256 or name in secrets:
            raise ValueError("each issuer name is a string of 1 to 256 characters, one time")
        data = _unb64(secret) if isinstance(secret, str) else None
        if data is None or not MIN_SECRET <= len(data) <= MAX_SECRET:
            raise ValueError(
                f"the secret of an issuer is base64url with no '=', of {MIN_SECRET} to "
                f"{MAX_SECRET} bytes"
            )
        secrets[name] = data
    return Issuers(secrets)


# The pure parts of the operations


def no_keys(value: Any) -> Any:
    """``value`` without each key of the store, at each depth. A member of an object whose value
    is a key is left out. A list item that is a key becomes None, so each other item keeps its
    index."""
    if isinstance(value, Mapping):
        return {
            name: no_keys(member)
            for name, member in value.items()
            if not (isinstance(member, str) and _KEY.fullmatch(member))
        }
    if isinstance(value, list):
        return [
            None if isinstance(item, str) and _KEY.fullmatch(item) else no_keys(item)
            for item in value
        ]
    return value


def task_view(
    task: Mapping[str, Any], sources: Mapping[int, Mapping[str, Any]] | Sequence[Any] = ()
) -> dict[str, Any] | None:
    """The members of a task response that come from the ``task@1`` object, or None for a task
    that is not a task of the API: a calibrate label task, and an audit task for a closed set.
    ``sources`` holds the decisions of the receipt, by their index: each choice gets the
    ``source`` and the ``ref`` of its decision.

    The ``body`` has no key of the store and no index of the receipt: its slot has no
    ``decisions``, and each choice has ``choice``, its number in the task, in place of
    ``decision``. A task with the mode ``audit`` is blind, so its ``body`` is None."""
    blind = task["mode"] == "audit"
    if task["template"] in QUESTIONS or (blind and task["item"] == "closed_set"):
        return None
    body = None
    if not blind:
        body = no_keys(task)
        body["slot"] = {name: v for name, v in body["slot"].items() if name != "decisions"}
        body["choices"] = [
            {
                "choice": number,
                **{name: v for name, v in choice.items() if name != "decision"},
                **_source(sources, task["choices"][number - 1]["decision"]),
            }
            for number, choice in enumerate(body["choices"], 1)
        ]
    return {
        "mode": task["mode"],
        "field": task["slot"]["field"],
        "key": task["slot"]["key"],
        "body": body,
    }


def _source(
    sources: Mapping[int, Mapping[str, Any]] | Sequence[Any], index: object
) -> dict[str, Any]:
    """The ``source`` and the ``ref`` of the decision ``index`` of the receipt, or None for each
    when ``sources`` does not have that decision."""
    found: object = None
    if type(index) is int:
        if isinstance(sources, Mapping):
            found = sources.get(index)
        elif 0 <= index < len(sources):
            found = sources[index]
    if not isinstance(found, Mapping):
        return {"source": None, "ref": None}
    source, ref = found.get("source"), found.get("ref")
    return {
        "source": source if isinstance(source, str) else None,
        "ref": ref if isinstance(ref, str) else None,
    }


def task_id(key: bytes, task_key: str) -> str:
    """The ID of a task: ``task:`` and HMAC-SHA-256 of the task key with the key of the
    service. Without the key of the service, the ID tells nothing of the task."""
    data = TASK_LABEL + task_key.encode("ascii")
    return "task:" + hmac.new(key, data, hashlib.sha256).hexdigest()


def statement_list(model_text: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The statements of a ``model-text@1`` object for a task response, in order: the text of
    each statement, and the spans of the document that it cites, in UTF-8 bytes."""
    data = model_text["text"].encode("utf-8")
    return [
        {
            "text": data[s["start"] : s["end"]].decode("utf-8"),
            "cites": [{"start": c["start"], "end": c["end"]} for c in s["cites"]],
        }
        for s in model_text["statements"]
    ]


def _order(entry: Mapping[str, Any]) -> tuple[str, str, bool, str, str]:
    # only members that the list gives: an order by a hidden key would tell a part of it
    key = entry["key"]
    return entry["document"], entry["field"], key is not None, key or "", entry["task"]


def list_page(
    entries: Iterable[Mapping[str, Any]], query: str
) -> tuple[list[Mapping[str, Any]], str | None]:
    """One page of the list and its ``next`` cursor. ``entries`` holds each task of the API with
    ``task``, its ID, and ``document``, ``field``, ``key`` and ``open``. ``query`` is the query
    string as the request has it: the list reads no percent escape."""
    limit, cursor = DEFAULT_LIMIT, None
    seen = set()
    for pair in query.split("&") if query else []:
        name, eq, value = pair.partition("=")
        if not eq or name not in ("limit", "cursor") or name in seen:
            raise ApiError("bad_request", "the query takes limit and cursor, each one time")
        seen.add(name)
        if name == "cursor":
            cursor = value
        elif not _DIGITS.fullmatch(value) or not 1 <= int(value) <= MAX_LIMIT:
            raise ApiError("bad_request", f"limit must be an integer from 1 to {MAX_LIMIT}")
        else:
            limit = int(value)
    ordered = sorted(entries, key=_order)
    after = None
    if cursor is not None:
        at = [e for e in ordered if e["task"] == cursor] if _ID.fullmatch(cursor) else []
        if not at:
            raise ApiError("bad_request", "the cursor is not the cursor of a page of this list")
        after = _order(at[0])
    rest = [e for e in ordered if e["open"] and (after is None or _order(e) > after)]
    page = rest[:limit]
    return page, page[-1]["task"] if len(rest) > limit else None


def _offsets(obj: Mapping[str, Any]) -> bool:
    a, b = obj.get("start"), obj.get("end")
    return type(a) is int and type(b) is int and 0 <= a < b < _OFFSET


def check_body(body: object, blind: bool = False) -> dict[str, Any]:
    """The answer of a request body, with each member that the body can leave out. A body with
    another form raises ``bad_request``. ``blind`` is true for a blind task: it takes only the
    verdicts of ``BLIND_VERDICTS``. An answer that is not a correction and has a member of a
    correction, or a correction with no span, raises ``bad_answer``."""

    def bad(message: str) -> ApiError:
        return ApiError("bad_request", message)

    if not isinstance(body, dict):
        raise bad("the body must be a JSON object")
    if set(body) - _BODY:
        raise bad("the body has a member that an answer does not have")
    task, verdict = body.get("task"), body.get("verdict")
    if not isinstance(task, str) or not _ID.fullmatch(task):
        raise bad("task must be a task ID")
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise bad("verdict must be an answer verdict")
    choice = body.get("choice")
    if choice is not None and (type(choice) is not int or not 1 <= choice < _LIMIT):
        raise bad("choice must be the number of a choice, from 1, or null")
    span = body.get("span")
    if span is not None and not (
        isinstance(span, dict) and set(span) == {"start", "end"} and _offsets(span)
    ):
        raise bad("span must be {start, end} in bytes, with start before end")
    value = body.get("value")
    if value is not None and (not isinstance(value, str) or len(value) > 1000):
        raise bad("value must be a string of 1000 characters at most, or null")
    parts = body.get("parts", [])
    if not isinstance(parts, list) or len(parts) > MAX_PARTS:
        raise bad(f"parts must be a list of {MAX_PARTS} parts at most")
    for p in parts:
        if (
            not isinstance(p, dict)
            or set(p) != {"role", "start", "end"}
            or not isinstance(p["role"], str)
            or p["role"] not in ROLES
            or not _offsets(p)
        ):
            raise bad(f"each part is {{role, start, end}} with a role of {', '.join(ROLES)}")
    kept = body.get("codes_kept", [])
    if (
        not isinstance(kept, list)
        or len(kept) > MAX_CODES
        or not all(isinstance(c, str) and _CODE.fullmatch(c) for c in kept)
    ):
        raise bad("codes_kept must be a list of reason codes")
    for name in ("parts_seen", "reason_seen"):
        if not isinstance(body.get(name, False), bool):
            raise bad(f"{name} must be a boolean")
    for name in ("keys", "ms"):
        n = body.get(name, 0)
        if type(n) is not int or not 0 <= n < _LIMIT:
            raise bad(f"{name} must be an integer from 0 to 2^31 - 1")
    statements = body.get("statements")
    if statements is not None and not isinstance(statements, list):
        raise bad("statements must be a list, or null")
    if blind and (verdict not in BLIND_VERDICTS or choice is not None):
        raise ApiError(
            "bad_answer",
            "a blind task takes only correct, not_in_document and unsure, and no choice: "
            "it shows no value",
        )
    correction = verdict in CORRECTIONS
    if correction and span is None:
        raise ApiError("bad_answer", "a correction needs a span")
    if not correction and (span is not None or value is not None or parts or kept):
        raise ApiError("bad_answer", "only a correction has a span, a value, parts and codes")
    return {
        "task": task,
        "verdict": verdict,
        "choice": choice,
        "span": span,
        "value": value,
        "parts": parts,
        "codes_kept": kept,
        "parts_seen": body.get("parts_seen", False),
        "statements": statements,
        "reason_seen": body.get("reason_seen", False),
        "keys": body.get("keys", 0),
        "ms": body.get("ms", 0),
    }


# The service


class Service:
    """The operations of the review API on the store in the folder ``root``. Each call opens
    the store, reads it again, and closes it, so the service holds no task, no queue and no log
    lock between two requests. ``auth`` is the issuers or the static token. ``id_key`` is the
    key of the task IDs: without it, the service makes a random key, so a task ID is good only
    while this service runs."""

    def __init__(
        self,
        root: str | Path,
        auth: Issuers | Static,
        policy: Mapping[str, Any] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_key: bytes | None = None,
    ) -> None:
        self.root = Path(root)
        self.auth = auth
        self.policy = check_policy(dict(DEFAULT_POLICY) if policy is None else policy)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if id_key is not None and len(id_key) < ID_KEY_BYTES:
            raise ValueError(f"the key of the task IDs must have {ID_KEY_BYTES} bytes or more")
        self._id_key = secrets.token_bytes(ID_KEY_BYTES) if id_key is None else id_key

    def actor(self, authorization: Sequence[str]) -> str:
        """The actor of a request, from the value of each of its Authorization headers."""
        if isinstance(self.auth, Static):
            return check_static(authorization, self.auth)
        return check_claim(authorization, self.auth, int(self._clock().timestamp()))

    def _review(self, store: Any, actor: str, only: list[str] | None = None) -> Review:
        return Review(store, actor, self.policy, clock=self._clock, only=only)

    def skipped(self) -> list[str]:
        """A line for each packet of the store that gives no task, as ``Review.skipped``."""
        from ..store import FolderStore

        with FolderStore(self.root) as store:
            return self._review(store, "groundgate").skipped

    def tasks(self, actor: str, query: str = "") -> dict[str, Any]:
        """GET /v1/tasks: one page of the open tasks of the actor."""
        from ..store import FolderStore

        with FolderStore(self.root) as store:
            entries = [
                {"task": self._id(tk), "document": doc.document, "mode": view["mode"],
                 "field": view["field"], "key": view["key"], "open": tk in doc.open}
                for tk, doc, view in self._served(self._review(store, actor))
            ]  # fmt: skip
        page, cursor = list_page(entries, query)
        return {
            "api": API,
            "actor": actor,
            "tasks": [{k: v for k, v in e.items() if k != "open"} for e in page],
            "next": cursor,
        }

    def _id(self, key: str) -> str:
        """The ID of a task in a response. No response gives the task key."""
        return task_id(self._id_key, key)

    def _served(self, review: Review) -> Iterator[tuple[str, Any, dict[str, Any]]]:
        """The task key, the document and the view of each task of the API."""
        for doc in review.docs.values():
            for key in doc.tasks:
                view = None
                if key not in doc.labels:
                    view = task_view(doc.by_key[key][1], doc.packet.receipt["decisions"])
                if view is not None:
                    yield key, doc, view

    def _one(
        self, store: Any, actor: str, name: str
    ) -> tuple[Review, str, Any, Any, dict[str, Any]]:
        """The review, the task key, the document, the slot and the view of the task of the API
        that the ID ``name`` names.

        The service makes the ID of each task of the API and compares it with ``name``. It
        never looks for ``name`` in the store. So each ID that names no task needs the same
        reads of the store, and the time of the ``not_found`` tells nothing of the store."""
        review = self._review(store, actor)
        found = None
        for key, doc, view in self._served(review):
            if hmac.compare_digest(self._id(key), name):
                found = review, key, doc, doc.by_key[key][0], view
        if found is None:
            raise ApiError("not_found", "the ID names no task of the API")
        return found

    def task(self, actor: str, name: str) -> dict[str, Any]:
        """GET /v1/tasks/{task}: one task. A blind task has no body."""
        from ..store import FolderStore

        with FolderStore(self.root) as store:
            review, key, doc, slot, view = self._one(store, actor, name)
            mine = [r for r in review._logs(doc.key).get(actor, []) if r.get("task") == key]
            model_text = key in doc.texts
            return {
                "api": API,
                "task": name,
                "document": doc.document,
                "mode": view["mode"],
                "field": view["field"],
                "key": view["key"],
                "definition": None if model_text else doc.schema.fields[slot.field].description,
                "answered": mine[-1].get("verdict") if mine else None,
                "body": view["body"],
                # the task holds no model text: the statements come from the model-text@1 input
                "statements": statement_list(doc.texts[key]) if model_text else None,
            }

    def document(self, actor: str, name: str) -> dict[str, Any]:
        """GET /v1/tasks/{task}/document: the text of the document of a task."""
        from ..store import FolderStore

        with FolderStore(self.root) as store:
            _, _, doc, _, _ = self._one(store, actor, name)
            return {"api": API, "task": name, "document": doc.document, "text": doc.units.text}

    def answer(self, actor: str, body: object) -> dict[str, Any]:
        """POST /v1/answers: check one answer, and append it to the answer log of the actor."""
        from ..store import FolderStore

        checked = check_body(body)
        name = checked["task"]
        with FolderStore(self.root) as store:
            review, key, doc, _, view = self._one(store, actor, name)
            blind = view["mode"] == "audit"
            if blind:
                check_body(body, blind=True)
            if checked["statements"] is not None and key not in doc.texts:
                raise ApiError("bad_answer", "only a model text task takes statements")

            def u16(span: Mapping[str, Any]) -> tuple[int, int]:
                chars = doc.units.chars(span["start"], span["end"])
                if chars is None:
                    raise ApiError("bad_answer", "a span is not a span of the document text")
                return doc.units.u16(chars[0]), doc.units.u16(chars[1])

            page: dict[str, Any] = {
                member: checked[member]
                for member in ("verdict", "value", "codes_kept", "parts_seen", "statements",
                               "reason_seen", "keys", "ms")
            }  # fmt: skip
            page["task"] = key
            # An answer names a choice by its number in the task. The record has the index of
            # the decision in the receipt.
            indexes = [choice["decision"] for choice in doc.by_key[key][1]["choices"]]
            number = checked["choice"]
            if number is not None and number > len(indexes):
                raise ApiError("bad_answer", "the task has no choice with this number")
            page["decision"] = None if number is None else indexes[number - 1]
            if checked["span"] is not None:
                page["start"], page["end"] = u16(checked["span"])
            page["parts"] = []
            for p in checked["parts"]:
                start, end = u16(p)
                page["parts"].append({"role": p["role"], "start": start, "end": end})
            try:
                record, _ = review.write(page, blind)
            except Refused as exc:
                code = exc.kind or ("not_found" if exc.code == 404 else "bad_answer")
                codes = exc.codes if code in ("correction_rejected", "codes_not_kept") else None
                message = exc.message
                if code == "log_refused":  # the store message names the log by its path
                    message = "the answer log cannot take the answer now"
                raise ApiError(code, message, codes) from exc
            # The record has the task key, so the response leaves it out, and it gives the
            # number of the choice in place of the index of the decision. The candidate of a
            # correction can hold the unit of the proposed value, so a blind answer gets no
            # record.
            shown = {member: value for member, value in record.items() if member != "task"}
            index = shown.pop("decision", None)
            shown["choice"] = indexes.index(index) + 1 if index in indexes else None
            return {
                "api": API,
                "actor": actor,
                "task": name,
                "record": None if blind else no_keys(shown),
            }


# The server


def server(service: Service, port: int = 0) -> ThreadingHTTPServer:
    """The review API of ``service`` on 127.0.0.1. Port 0 takes a free port."""
    lock = threading.Lock()
    host = ""  # 127.0.0.1 and the bound port, set once the server binds

    class Handler(BaseHTTPRequestHandler):
        timeout = 30  # a client that sends less than its Content-Length holds a thread no longer

        def send(self, body: Mapping[str, Any], status: int = 200, allow: str = "") -> None:
            raw = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            if allow:
                self.send_header("Allow", allow)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def refuse(self, exc: ApiError, allow: str = "") -> None:
            self.close_connection = True
            error: dict[str, Any] = {"code": exc.code, "message": _printable(exc.message)}
            if exc.codes is not None:
                error["codes"] = exc.codes
            self.send({"api": API, "error": error}, exc.status, allow)

        def send_error(
            self, code: int, message: str | None = None, explain: str | None = None
        ) -> None:
            # a request that http.server cannot read: no HTML, and nothing from the request
            self.refuse(ApiError("bad_request", "the request is not an HTTP request of the API"))

        def dispatch(self) -> None:
            try:
                self.route()
            except ApiError as exc:
                self.refuse(exc)
            except Exception:  # never send a trace with store data
                self.refuse(ApiError("server_error", "the service failed on this request"))

        def route(self) -> None:
            if self.headers.get_all("Host") != [host]:
                raise ApiError("wrong_host", "the Host header must be 127.0.0.1 and the port")
            actor = service.actor(self.headers.get_all("Authorization") or [])
            path, mark, query = self.path.partition("?")
            found = _TASK.fullmatch(path)
            if path not in ("/v1/tasks", "/v1/answers") and found is None:
                raise ApiError("not_found", "no operation has this path")
            method = "POST" if path == "/v1/answers" else "GET"
            if self.command != method:
                self.refuse(
                    ApiError("method_not_allowed", f"this path takes only {method}"), method
                )
                return
            if mark and path != "/v1/tasks":
                raise ApiError("bad_request", "only the list takes a query")
            if path == "/v1/tasks":
                self.run(lambda: service.tasks(actor, query))
            elif path == "/v1/answers":
                body = self.body()
                self.run(lambda: service.answer(actor, body), 201)
            elif found is not None:
                key, document = found.group(1), bool(found.group(2))
                self.run(lambda: (service.document if document else service.task)(actor, key))

        def run(self, call: Callable[[], dict[str, Any]], status: int = 200) -> None:
            with lock:
                result = call()
            self.send(result, status)

        def body(self) -> object:
            kind = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if kind != "application/json":
                raise ApiError("unsupported_media_type", "the body must be application/json")
            length = self.headers.get("Content-Length", "")
            # only digits: int() also takes "+5", "1_0" and spaces
            if not (length.isascii() and length.isdigit()) or len(length) > 12:
                raise ApiError("length_required", "the request needs a Content-Length of digits")
            if int(length) > MAX_BODY:
                raise ApiError("body_too_large", f"the body must be {MAX_BODY} bytes at most")
            try:
                body = json.loads(self.rfile.read(int(length)))
            except (ValueError, RecursionError):  # deep nesting fits in 64 KiB
                raise ApiError("bad_request", "the body is not JSON") from None
            if not isinstance(body, dict):
                raise ApiError("bad_request", "the body must be a JSON object")
            return body

        def __getattr__(self, name: str) -> Any:
            if name.startswith("do_"):  # each method gets the checks of ``route``
                return self.dispatch
            raise AttributeError(name)

        def log_message(self, *args: Any) -> None:
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    host = f"127.0.0.1:{httpd.server_port}"
    return httpd
