"""The ``facts@1`` projection of a verified packet (SPEC §5.1), and the ``facts@2`` projection
of a reviewed packet (SPEC §5.2)."""

from __future__ import annotations

import json
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from importlib import resources
from typing import Any

from . import Store, StoreError, key, reviewer_key
from .packets import Packet, load_reading

SELECTOR_CONTEXT = 32  # the code points of a prefix and of a suffix (SPEC §5.2)
FACT_STATUSES = ("admitted", "confirmed", "chosen", "corrected")
OPEN_STATUSES = ("open", "disputed", "not_in_document", "rejected")
_BEFORE_SELECTOR = ("source", "ref", "url", "source_sha256", "text_sha256", "span")


def _document_source_key(store: Store, packet: Packet) -> str | None:
    if packet.reading is not None:
        reading = load_reading(store, packet.reading)
        if reading["text"] != key("text@1", packet.text.encode("utf-8")):
            raise StoreError(f"the reading {packet.reading} is of another text")
        return str(reading["source"])
    if packet.run is not None:
        from ..extract.runner import _load_run_document

        document = _load_run_document(store, packet)
        return document.source if document is not None else None
    return None


Fact = Callable[[Mapping[str, Any]], dict[str, Any]]


def _projection(receipt: Mapping[str, Any], source_key: str | None) -> Fact:
    """The ``facts@1`` fact of one decision of ``receipt`` (SPEC §5.1)."""
    references = {r["id"]: r for r in receipt["references"]}
    # the replaced mark of each record line, by record field and record id (SPEC §5, #659)
    replaced = {(r["field"], r["record"]): r["replaced"] for r in receipt.get("records", [])}

    def fact(decision: Mapping[str, Any]) -> dict[str, Any]:
        source = decision["source"]
        reference = references.get(decision["ref"])
        text_sha256 = url = None
        if source == "document":
            text_sha256 = receipt["document"]["sha256"]
            url = receipt["document"]["source"]
        elif reference is not None:
            text_sha256 = reference["sha256"]
            url = reference["source"]
        elif source == "external":
            url = decision["url"]
        row = {}
        if decision.get("record") is not None:  # only a fact of a member field (#659)
            line = (decision["field"].split(".", 1)[0], decision["record"])
            row = {"record": decision["record"], "replaced": replaced[line]}
        citation_more = {}
        if decision.get("passage_sha256") is not None:  # only a passage field (SPEC §4.17, #638)
            citation_more["passage_sha256"] = decision["passage_sha256"]
        if decision.get("locator") is not None:  # only with places in the packet (#614)
            citation_more["locator"] = decision["locator"]
        return {
            "field": decision["field"],
            "key": decision["key"],
            "value": decision["value"],
            "unit": decision["unit"],
            **row,
            "citation": {
                "source": source,
                "ref": decision["ref"],
                "url": url,
                "source_sha256": source_key if source == "document" else None,
                "text_sha256": text_sha256,
                "span": decision["evidence"],
                "receipt_sha256": receipt["receipt_sha256"],
                **citation_more,
            },
        }

    return fact


def admitted_facts(store: Store, packet: Packet) -> dict[str, Any]:
    """Project admitted decisions in receipt order. The caller must verify the packet first."""
    receipt = packet.receipt
    admitted = [d for d in receipt["decisions"] if d["outcome"] == "admitted"]
    source_key = (
        _document_source_key(store, packet)
        if any(d["source"] == "document" for d in admitted)
        else None
    )
    project = _projection(receipt, source_key)
    out: dict[str, Any] = {
        "format": "facts@1",
        "packet_sha256": packet.key,
        "facts": [project(d) for d in admitted],
    }
    if receipt.get("completeness") is not None:  # only with it in the packet (SPEC §4.16, #615)
        out["completeness"] = receipt["completeness"]
    return out


def facts_schema() -> dict[str, Any]:
    """The JSON Schema of ``facts@2`` (SPEC §5.2)."""
    raw = resources.files(__package__).joinpath("facts@2.schema.json").read_text("utf-8")
    return json.loads(raw)  # type: ignore[no-any-return]


class Offsets:
    """The code point offset of each UTF-8 byte offset of one NFC text. It reads the text one
    time, then a lookup reads one block. Thus many spans of a large text stay cheap."""

    BLOCK = 4096  # code points

    def __init__(self, text: str) -> None:
        self.text = text
        self.starts = [0]  # the byte offset of each block
        for i in range(0, len(text), self.BLOCK):
            self.starts.append(self.starts[-1] + len(text[i : i + self.BLOCK].encode("utf-8")))

    def point(self, byte: int) -> int:
        block = min(bisect_right(self.starts, byte) - 1, max(len(self.starts) - 2, 0))
        first = block * self.BLOCK
        data = self.text[first : first + self.BLOCK].encode("utf-8")
        return first + len(data[: byte - self.starts[block]].decode("utf-8"))


def selector(
    text: str, span: Mapping[str, int] | None, offsets: Offsets | None = None
) -> dict[str, Any] | None:
    """The text selector of a UTF-8 byte span of the NFC ``text`` (SPEC §5.2). ``offsets`` is
    the ``Offsets`` of ``text``, for a caller with more than one span."""
    if span is None:
        return None
    offsets = offsets or Offsets(text)
    start, end = offsets.point(span["start"]), offsets.point(span["end"])
    return {
        "start": start,
        "end": end,
        "exact": text[start:end],
        "prefix": text[max(0, start - SELECTOR_CONTEXT) : start],
        "suffix": text[end : end + SELECTOR_CONTEXT],
    }


def _load(store: Store, kind: str, k: str) -> Any:
    try:
        return json.loads(store.get(kind, k))
    except ValueError as exc:
        raise StoreError(f"the {kind} object {k} is not JSON") from exc


def reviewed_facts(
    store: Store, packet_key: str, resolution_key: str
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """The ``facts@2`` object of the packet and its stored resolution (SPEC §5.2), and the
    problems that stop it. When the receipt or the resolution does not match its inputs, the
    object is None and the problems are not empty."""
    from ..review.model_text import stored_model_texts
    from ..review.resolve import _agreed, resolve
    from ..review.tasks import check_policy, checked_packet, slots

    packet, schema, layout, problems = checked_packet(store, packet_key)
    if problems or schema is None:
        return None, problems
    stored = _load(store, "resolution@1", resolution_key)
    if not isinstance(stored, dict) or stored.get("format") != "resolution@1":
        raise StoreError(f"the object {resolution_key} is not a resolution@1 object")
    if stored.get("packet") != packet_key:
        raise StoreError(f"the resolution {resolution_key} is of another packet")
    heads = stored.get("answers")
    if (
        not isinstance(stored.get("policy"), str)
        or not isinstance(heads, list)
        or not all(
            isinstance(h, dict)
            and isinstance(h.get("reviewer"), str)
            and isinstance(h.get("head"), str)
            for h in heads
        )
    ):  # the store checks only that an object is canonical JSON
        raise StoreError(f"the resolution {resolution_key} has no policy key or no log heads")
    policy = check_policy(_load(store, "review-policy@1", stored["policy"]))
    logs: dict[str, Sequence[Mapping[str, Any]]] = {}
    for head in heads:
        name = head["reviewer"]
        records = store.read(("answers", packet_key, reviewer_key(name)))
        at = [i for i, r in enumerate(records) if r.get("entry_sha256") == head["head"]]
        if not at:
            return None, (f"the answer log of the reviewer {name!r} has no entry {head['head']}",)
        logs[name] = records[: at[0] + 1]
    seen: list[Any] = []
    again, _ = resolve(
        packet_key, packet, schema, policy, logs, layout=layout, seen=seen,
        model_texts=stored_model_texts(store, packet_key),
    )  # fmt: skip
    if again != stored:
        return None, (f"the resolution {resolution_key} does not match its inputs",)

    latest: dict[str, dict[str, Any]] = {}  # task key -> reviewer -> the latest Seen
    for s in seen:
        latest.setdefault(s.task_key, {})[s.reviewer] = s
    receipt = packet.receipt
    decisions = receipt["decisions"]
    texts = {None: packet.text} | {r["id"]: r["text"] for r in packet.references or []}
    offsets: dict[str | None, Offsets] = {}  # one for each cited text
    source_key: list[str | None] = []  # read only for the first fact with a document source
    projections: dict[str, Fact] = {}

    def project(decision: Mapping[str, Any], cited: Mapping[str, Any]) -> dict[str, Any]:
        digest = cited["receipt_sha256"]
        if digest not in projections:
            projections[digest] = _projection(cited, None)
        fact = projections[digest](decision)
        if decision["source"] == "document":  # the key is not in the projection: it comes late
            if not source_key:
                source_key.append(_document_source_key(store, packet))
            fact["citation"]["source_sha256"] = source_key[0]
        return fact

    facts, open_ = [], []
    model_text_slots = len(slots(receipt, schema))  # the slots of model texts come after these
    for slot in again["slots"][:model_text_slots]:
        status, task = slot["status"], slot["task"]
        if status in OPEN_STATUSES:
            open_.append({"field": slot["field"], "key": slot["key"], "status": status,
                          "task": task})  # fmt: skip
            continue
        if status not in FACT_STATUSES:
            raise StoreError(f"a slot of the resolution has the status {status!r}")
        review = None
        cited: Mapping[str, Any] = receipt
        if status == "admitted":
            passed = [i for i in slot["decisions"] if decisions[i]["outcome"] != "rejected"]
            decision = decisions[passed[0]]
        else:
            answers = {r: s.answer for r, s in latest[task].items()}
            _, first = _agreed(answers, policy)
            assert first is not None  # a confirmed, chosen or corrected slot has an answer
            if first.correction is not None:  # the status corrected
                decision = first.correction.decision
                cited = _load(store, "receipt@1", first.correction.receipt)
            else:
                assert first.decision is not None
                decision = decisions[first.decision]
            used = [
                {"reviewer": r, "verdict": s.record["verdict"],
                 "entry_sha256": s.record["entry_sha256"]}
                for r, s in sorted(latest[task].items())
                if s.answer.target is not None and s.answer.target == first.target
            ]  # fmt: skip
            review = {"task": task, "policy": stored["policy"], "answers": used}
        fact = project(decision, cited)
        citation = fact.pop("citation")
        span = citation["span"]
        chosen = None
        if citation["source"] in ("document", "reference") and citation["ref"] in texts:
            ref = citation["ref"]
            if ref not in offsets:
                offsets[ref] = Offsets(texts[ref])
            chosen = selector(texts[ref], span, offsets[ref])
        citation = {
            **{k: citation[k] for k in _BEFORE_SELECTOR},
            "selector": chosen,
            **{k: v for k, v in citation.items() if k not in _BEFORE_SELECTOR},
        }
        row: dict[str, Any] = {k: fact.pop(k) for k in ("record", "replaced") if k in fact}
        facts.append({**fact, "status": status, "review": review, **row, "citation": citation})
    out: dict[str, Any] = {
        "format": "facts@2",
        "packet_sha256": packet_key,
        "resolution_sha256": resolution_key,
        "policy_sha256": stored["policy"],
        "facts": facts,
        "open": open_,
    }
    if receipt.get("completeness") is not None:  # as in facts@1 (SPEC §4.16)
        out["completeness"] = receipt["completeness"]
    return out, ()
