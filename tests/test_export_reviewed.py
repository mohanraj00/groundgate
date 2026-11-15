"""`groundgate export --resolution`: the ``facts@2`` export of a reviewed packet (SPEC §5.2, #675).

The vectors in ``conformance/exports/`` give the expected facts and open slots by hand. This
module adds the keys and the digests from the store and from ``admit``, never from the export
code.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any

import jsonschema
import pytest

import groundgate as gg
from groundgate.canonical import jcs
from groundgate.cli import main
from groundgate.review.tasks import write_tasks
from groundgate.store import FolderStore, reviewer_key
from groundgate.store import key as store_key
from groundgate.store.export import Offsets, facts_schema, selector
from groundgate.store.packets import admit_packet, put_reading

ROOT = Path(__file__).parent.parent / "conformance"
EXPORTS = sorted((ROOT / "exports").glob("*.json"))
EVERY = {
    "format": "review-policy@1",
    "audit": {"rate": "1", "seed": "s"},
    "agree": 1,
    "leads": [],
    "rejected": True,
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text("utf-8"))  # type: ignore[no-any-return]


def _record(task: str, reviewer: str, verdict: str, decision: int | None, candidate: Any) -> Any:
    return {
        "format": "answer@1", "task": task, "reviewer": reviewer, "verdict": verdict,
        "decision": decision, "candidate": candidate, "codes_kept": [], "statements": None,
        "nodes": None, "reason_seen": False, "keys": 1, "ms": 1000,
        "time": "2026-11-15T10:00:00Z",
    }  # fmt: skip


class Reviewed:
    """A vector in a store: the packet, its tasks, the answers and the resolution."""

    def __init__(self, v: dict[str, Any], tmp_path: Path, capsys: Any) -> None:
        self.v = v
        self.source = tmp_path / "source.txt"
        self.source.write_bytes(v["document"].encode("utf-8"))
        self.folder = tmp_path / "store"
        policy_file = tmp_path / "review-policy.json"
        policy_file.write_text(json.dumps(v["review_policy"]), "utf-8")
        with FolderStore(self.folder) as store:
            reading, _ = put_reading(store, self.source)
            self.packet, receipt = admit_packet(
                store, v["document"], v["schema"], v["candidates"], v["policy"],
                reading=reading, references=v.get("references"),
            )  # fmt: skip
            self.receipt = receipt.to_dict()
            self.tasks = {
                (t["slot"]["field"], t["slot"]["key"]): k
                for k, t in write_tasks(store, self.packet, EVERY).tasks
            }
            ids = [d["candidate_id"] for d in self.receipt["decisions"]]
            for a in v["answers"]:
                task = self.tasks[a["slot"]["field"], a["slot"]["key"]]
                decision = ids.index(a["choice"]) if "choice" in a else None
                given = _record(task, a["reviewer"], a["verdict"], decision, a.get("candidate"))
                store.append(("answers", self.packet, reviewer_key(a["reviewer"])), given)
        reviewers = sorted({a["reviewer"] for a in v["answers"]})
        args = ["review", "resolve", "--store", str(self.folder), self.packet,
                "--policy", str(policy_file)]  # fmt: skip
        for name in reviewers:
            args += ["--reviewer", name]
        assert main(args) == 0
        self.resolution = capsys.readouterr().out.splitlines()[0]

    def export(self, capsys: Any, resolution: str | None = None) -> tuple[int, Any, str]:
        code = main(["export", "--store", str(self.folder), self.packet,
                     "--resolution", resolution or self.resolution])  # fmt: skip
        out = capsys.readouterr()
        return code, json.loads(out.out) if out.out else None, out.err

    def expected(self) -> dict[str, Any]:
        """The full ``facts@2`` object from the hand-written expectation of the vector."""
        v = self.v
        refs = {r["id"]: r for r in v.get("references", [])}
        policy = store_key("review-policy@1", jcs(v["review_policy"]).encode("utf-8"))
        with FolderStore(self.folder) as store:
            resolution = json.loads(store.get("resolution@1", self.resolution))
            slots = {(s["field"], s["key"]): s for s in resolution["slots"]}
            logs = {
                name: store.read(("answers", self.packet, reviewer_key(name)))
                for name in {a["reviewer"] for a in v["answers"]}
            }
            facts = []
            for f in v["expected"]["facts"]:
                slot = (f["field"], f["key"])
                review = None
                if f["answers"] is not None:
                    task = self.tasks[slot]
                    answers = []
                    for a in f["answers"]:
                        (entry,) = [r["entry_sha256"] for r in logs[a["reviewer"]]
                                    if r["task"] == task][-1:]  # fmt: skip
                        answers.append({**a, "entry_sha256": entry})
                    review = {"task": task, "policy": policy, "answers": answers}
                source_sha256 = text_sha256 = None
                if f["source"] == "document":
                    source_sha256 = store_key("source@1", self.source.read_bytes())
                    text_sha256 = gg.digest("document", {"text": v["document"]})
                else:
                    text_sha256 = gg.digest("reference", {"text": refs[f["ref"]]["text"]})
                receipt = json.loads(store.get("receipt@1", slots[slot]["receipt"]))
                facts.append(
                    {
                        "field": f["field"], "key": f["key"], "value": f["value"],
                        "unit": f["unit"], "status": f["status"], "review": review,
                        "citation": {
                            "source": f["source"], "ref": f["ref"], "url": None,
                            "source_sha256": source_sha256, "text_sha256": text_sha256,
                            "span": f["span"], "selector": f["selector"],
                            "receipt_sha256": receipt["receipt_sha256"],
                        },
                    }
                )  # fmt: skip
        open_ = [
            {"field": o["field"], "key": o["key"], "status": o["status"],
             "task": self.tasks[o["field"], o["key"]] if o["task"] else None}
            for o in v["expected"]["open"]
        ]  # fmt: skip
        return {
            "format": "facts@2", "packet_sha256": self.packet,
            "resolution_sha256": self.resolution, "policy_sha256": policy,
            "facts": facts, "open": open_,
        }  # fmt: skip


def _texts(v: dict[str, Any]) -> dict[Any, str]:
    return {None: v["document"]} | {r["id"]: r["text"] for r in v.get("references", [])}


@pytest.mark.parametrize("path", EXPORTS, ids=lambda p: p.stem)
def test_export_vector(path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    v = _load(path)
    reviewed = Reviewed(v, tmp_path, capsys)
    by_id = {d["candidate_id"]: d for d in reviewed.receipt["decisions"]}
    for cand, want in zip(v["candidates"], v["expected"]["decisions"], strict=True):
        got = by_id[cand["id"]]
        assert (got["outcome"], got["codes"]) == (want["outcome"], want["codes"])
    assert reviewed.receipt["coverage"] == v["expected"]["coverage"]

    code, exported, err = reviewed.export(capsys)
    assert (code, err) == (0, "")
    assert exported == reviewed.expected()
    jsonschema.Draft202012Validator(facts_schema()).validate(exported)
    for fact in exported["facts"]:  # each exact text is the NFC text at its code point offsets
        text = _texts(v)[fact["citation"]["ref"]]
        assert unicodedata.is_normalized("NFC", text)
        s = fact["citation"]["selector"]
        assert text[s["start"] : s["end"]] == s["exact"]
        assert text[: s["start"]].endswith(s["prefix"]) and len(s["prefix"]) <= 32
        assert text[s["end"] :].startswith(s["suffix"]) and len(s["suffix"]) <= 32
        span = fact["citation"]["span"]
        assert text.encode("utf-8")[span["start"] : span["end"]].decode("utf-8") == s["exact"]


def test_the_example_of_the_issue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Two admitted, one confirmed by a reviewer, one open slot (#675)."""
    reviewed = Reviewed(_load(ROOT / "exports" / "export2-invoice.json"), tmp_path, capsys)
    _, exported, _ = reviewed.export(capsys)
    assert [(f["field"], f["status"]) for f in exported["facts"]] == [
        ("boxes", "admitted"), ("estimate", "confirmed"), ("items", "admitted"),
    ]  # fmt: skip
    confirmed = exported["facts"][1]
    assert [(a["reviewer"], a["verdict"]) for a in confirmed["review"]["answers"]] == [
        ("ana", "confirm")
    ]
    assert confirmed["citation"]["selector"]["exact"] == "4"
    assert [(o["field"], o["status"]) for o in exported["open"]] == [("weight", "open")]
    assert exported["open"][0]["task"] == reviewed.tasks["weight", None]


def test_offsets_differ_in_a_script_other_than_latin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v = _load(ROOT / "exports" / "export2-scripts.json")
    reviewed = Reviewed(v, tmp_path, capsys)
    _, exported, _ = reviewed.export(capsys)
    assert [f["status"] for f in exported["facts"]] == ["corrected", "admitted", "admitted"]
    receipts = [f["citation"]["receipt_sha256"] for f in exported["facts"]]
    assert receipts[1] == receipts[2] == reviewed.receipt["receipt_sha256"]
    assert receipts[0] != receipts[1]  # the corrected fact cites the correction receipt
    for fact in exported["facts"]:
        citation = fact["citation"]
        text = unicodedata.normalize("NFC", _texts(v)[citation["ref"]])
        s = citation["selector"]
        assert text[s["start"] : s["end"]] == s["exact"]
        assert (s["start"], s["end"]) != (citation["span"]["start"], citation["span"]["end"])


def test_facts_1_does_not_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A resolution in the store does not change the export without ``--resolution``."""
    reviewed = Reviewed(_load(ROOT / "exports" / "export2-invoice.json"), tmp_path, capsys)
    assert main(["export", "--store", str(reviewed.folder), reviewed.packet]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["format"] == "facts@1"
    assert sorted(f["field"] for f in exported["facts"]) == ["boxes", "items"]
    assert all(set(f) == {"field", "key", "value", "unit", "citation"} for f in exported["facts"])
    assert all("selector" not in f["citation"] for f in exported["facts"])


def test_a_later_answer_does_not_change_the_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The export reads each log up to the head that the resolution names."""
    reviewed = Reviewed(_load(ROOT / "exports" / "export2-invoice.json"), tmp_path, capsys)
    _, before, _ = reviewed.export(capsys)
    with FolderStore(reviewed.folder) as store:
        late = _record(reviewed.tasks["weight", None], "ana", "not_in_document", None, None)
        store.append(("answers", reviewed.packet, reviewer_key("ana")), late)
    code, after, _ = reviewed.export(capsys)
    assert code == 0 and after == before


def test_export_refuses_a_resolution_that_does_not_rederive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewed = Reviewed(_load(ROOT / "exports" / "export2-invoice.json"), tmp_path, capsys)
    with FolderStore(reviewed.folder) as store:
        forged = json.loads(store.get("resolution@1", reviewed.resolution))
        (slot,) = [s for s in forged["slots"] if s["field"] == "weight"]
        slot.update(status="admitted", value="8", evidence={"start": 64, "end": 65})
        forged_key = store.put("resolution@1", jcs(forged).encode("utf-8"))
    code, exported, err = reviewed.export(capsys, forged_key)
    assert (code, exported) == (1, None)
    assert "does not match its inputs" in err


def test_export_refuses_a_head_that_is_not_in_the_log(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewed = Reviewed(_load(ROOT / "exports" / "export2-invoice.json"), tmp_path, capsys)
    with FolderStore(reviewed.folder) as store:
        forged = json.loads(store.get("resolution@1", reviewed.resolution))
        forged["answers"][0]["head"] = "sha256:" + "0" * 64
        forged_key = store.put("resolution@1", jcs(forged).encode("utf-8"))
    code, exported, err = reviewed.export(capsys, forged_key)
    assert (code, exported) == (1, None)
    assert "has no entry" in err


def test_export_refuses_the_resolution_of_another_packet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    reviewed = Reviewed(_load(ROOT / "exports" / "export2-invoice.json"), tmp_path, capsys)
    with FolderStore(reviewed.folder) as store:
        other, _ = admit_packet(store, "Items: 9\n", reviewed.v["schema"], [], None)
    code = main(["export", "--store", str(reviewed.folder), other,
                 "--resolution", reviewed.resolution])  # fmt: skip
    out = capsys.readouterr()
    assert (code, out.out) == (2, "")
    assert "another packet" in out.err
    assert main(["export", "--store", str(reviewed.folder), reviewed.packet,
                 "--resolution", "sha256:" + "0" * 64]) == 2  # fmt: skip
    assert capsys.readouterr().out == ""
    assert main(["export", "--store", str(reviewed.folder), reviewed.packet, "--pack-dir",
                 str(tmp_path), "--resolution", reviewed.resolution]) == 2  # fmt: skip


def test_selector_cuts_the_context_at_32_code_points() -> None:
    text = "д" * 40 + "値" + "ж" * 40
    assert selector(text, {"start": 80, "end": 83}) == {
        "start": 40, "end": 41, "exact": "値", "prefix": "д" * 32, "suffix": "ж" * 32,
    }  # fmt: skip
    assert selector(text, None) is None


def test_offsets_match_one_decode_of_the_text_at_each_block_end() -> None:
    """A lookup reads one block of 4096 code points. The result is the same as with one
    decode of all the bytes before the offset."""
    text = ("aд値😀" * 3000)[:-1]  # 11999 code points, 1 to 4 bytes each
    offsets = Offsets(text)
    data = text.encode("utf-8")
    at = [0, 1, 3, len(data)]
    for block in (4096, 8192):
        at += [len(text[:n].encode("utf-8")) for n in (block - 1, block, block + 1)]
    for byte in at:
        assert offsets.point(byte) == len(data[:byte].decode("utf-8"))
    assert Offsets("").point(0) == 0
    assert Offsets("д" * 4096).point(8192) == 4096
    last = len(data) - 3  # the text ends with a character of 3 bytes
    assert selector(text, {"start": last, "end": len(data)}, offsets)["exact"] == "値"


def test_a_document_fact_after_a_reference_fact_keeps_its_source_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The fact of the reference comes first in the export. The fact of the document after it
    has the same ``source_sha256`` as in ``facts@1``."""
    v = {
        "document": "Boxes: 3\n",
        "schema": {"fields": {"a": {"type": "integer"}, "z": {"type": "integer"}}},
        "candidates": [
            {"id": "z", "field": "z", "value": 3, "evidence": {"start": 7, "end": 8, "text": "3"}},
            {"id": "a", "field": "a", "value": 5,
             "evidence": {"ref": "stock", "source": "reference", "start": 8, "end": 9,
                          "text": "5"}},
        ],
        "policy": None,
        "references": [{"id": "stock", "text": "Crates: 5"}],
        "review_policy": EVERY,
        "answers": [],
    }  # fmt: skip
    reviewed = Reviewed(v, tmp_path, capsys)
    _, exported, _ = reviewed.export(capsys)
    assert main(["export", "--store", str(reviewed.folder), reviewed.packet]) == 0
    first = {f["field"]: f["citation"] for f in json.loads(capsys.readouterr().out)["facts"]}
    assert [f["field"] for f in exported["facts"]] == ["a", "z"]
    assert [f["citation"]["source"] for f in exported["facts"]] == ["reference", "document"]
    key = store_key("source@1", reviewed.source.read_bytes())
    for fact in exported["facts"]:
        expected = key if fact["field"] == "z" else None
        assert fact["citation"]["source_sha256"] == expected
        assert first[fact["field"]]["source_sha256"] == expected
