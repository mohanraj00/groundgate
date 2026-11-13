"""The ``facts@1`` projection of a verified packet (SPEC §5.1)."""

from __future__ import annotations

from typing import Any

from . import Store, StoreError, key
from .packets import Packet, load_reading


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


def admitted_facts(store: Store, packet: Packet) -> dict[str, Any]:
    """Project admitted decisions in receipt order. The caller must verify the packet first."""
    receipt = packet.receipt
    admitted = [d for d in receipt["decisions"] if d["outcome"] == "admitted"]
    source_key = (
        _document_source_key(store, packet)
        if any(d["source"] == "document" for d in admitted)
        else None
    )
    references = {r["id"]: r for r in receipt["references"]}
    facts = []
    for decision in admitted:
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
        citation_more = {}
        if decision.get("locator") is not None:  # only with places in the packet (#614)
            citation_more["locator"] = decision["locator"]
        facts.append(
            {
                "field": decision["field"],
                "key": decision["key"],
                "value": decision["value"],
                "unit": decision["unit"],
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
        )
    return {"format": "facts@1", "packet_sha256": packet.key, "facts": facts}
