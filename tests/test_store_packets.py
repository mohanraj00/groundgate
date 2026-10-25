"""Readings and packets in the store (docs/design/store.md §5, §9): read, admit, verify and
report from one store and the packet key alone."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import groundgate as gg
from groundgate.canonical import jcs
from groundgate.cli import main
from groundgate.model import PacketError
from groundgate.store import FolderStore, StoreError, key
from groundgate.store.maintain import rebuild
from groundgate.store.packets import InputGone, admit_packet, load_packet, put_reading

from pdfgen import make_pdf

SCHEMA: dict[str, Any] = {
    "fields": {
        "fee": {"type": "integer", "unit": "USD", "required": True},
        "term": {"type": "integer"},
    }
}
TEXT = "Lease\n\nThe fee is $500 per year. The term is 3 years.\n"
LAC = {
    "groundgate_pack": 1,
    "type": "vocabulary",
    "id": "lac-x-test",
    "version": "1.0.0",
    "scale": {"words": {"lac": 5}},
}


def ev(quote: str, text: str = TEXT) -> dict[str, Any]:
    start = text.encode().index(quote.encode())
    return {"start": start, "end": start + len(quote.encode()), "text": quote}


def cands(text: str = TEXT) -> list[Any]:
    return [
        {"id": "fee", "field": "fee", "value": "500", "unit": "USD", "evidence": ev("$500", text)},
        {"id": "term", "field": "term", "value": 3, "evidence": ev("3 years", text)},
    ]


def clock() -> datetime:
    return datetime(2026, 10, 20, 9, 30, tzinfo=timezone.utc)


def files(tmp_path: Path, **objects: Any) -> dict[str, str]:
    out = {}
    for name, value in objects.items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        out[name] = str(path)
    return out


def test_read_admit_verify_report_from_the_packet_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = str(tmp_path / "store")
    pdf = tmp_path / "lease.pdf"
    pdf.write_bytes(make_pdf([[(72, 700, "Intro")], [(72, 700, "The fee is $500 per year.")]]))
    doc = tmp_path / "doc.txt"
    assert main(["read", "--store", store, str(pdf), "-o", str(doc)]) == 0
    reading = capsys.readouterr().out.strip()
    assert reading.startswith("sha256:") and len(reading) == 71
    text = doc.read_text(encoding="utf-8")
    given = files(
        tmp_path,
        schema=SCHEMA,
        cands=[{"field": "fee", "value": "500", "unit": "USD", "evidence": ev("$500", text)}],
    )
    args = [doc, given["schema"], given["cands"], "--document-id", "lease-1"]
    cmd = ["admit", "--store", store, "--reading", reading, *map(str, args)]
    assert main(cmd) == 0
    packet = capsys.readouterr().out.strip()
    assert packet.startswith("sha256:")
    assert main(cmd) == 0  # the same inputs give the same packet key
    assert capsys.readouterr().out.strip() == packet

    assert main(["verify", "--store", store, packet]) == 0
    assert capsys.readouterr().out == "receipt verified\n"
    html = tmp_path / "r.html"
    assert main(["report", "--store", store, packet, "-o", str(html)]) == 0
    page = html.read_text(encoding="utf-8")
    assert "<title>lease-1</title>" in page and "page 2 · " in page
    assert "receipt verified" in page

    with FolderStore(store) as s:
        found = load_packet(s, packet)
        assert found.reading == reading and found.layout is None  # layout only on request
        assert json.loads(s.get("reading@1", reading))["options"] == {"pages": None}


def test_admit_store_writes_the_receipt_to_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = str(tmp_path / "store")
    doc = tmp_path / "doc.txt"
    doc.write_text(TEXT, encoding="utf-8")
    given = files(tmp_path, schema=SCHEMA, cands=cands(), policy={"min_confidence": 1.0})
    receipt = tmp_path / "r.json"
    cmd = ["admit", "--store", store, str(doc), given["schema"], given["cands"]]
    assert main([*cmd, "--policy", given["policy"], "-o", str(receipt)]) == 0
    packet = capsys.readouterr().out.strip()
    with FolderStore(store) as s:
        stored = json.loads(s.get("receipt@1", json.loads(s.get("packet@1", packet))["receipt"]))
    assert json.loads(receipt.read_text(encoding="utf-8")) == stored
    assert main(["verify", "--store", store, packet]) == 0


def test_the_packet_names_each_input(tmp_path: Path) -> None:
    text = "Grant letter\n\nThe grant is 5 lac rupees. The fee is $500 per year.\n"
    schema = {
        "packs": [{"id": "lac-x-test", "version": "1.0.0"}],
        "fields": {"grant": {"type": "integer"}, "fee": {"type": "integer", "unit": "USD"}},
    }
    refs = [{"id": "r1", "text": "The term is 3 years.", "source": "https://example.org/t"}]
    candidates = [
        {"id": "g", "field": "grant", "value": "500000", "evidence": [{"text": "5 lac"}]},
        {"id": "f", "field": "fee", "value": "500", "unit": "USD", "evidence": ev("$500", text)},
    ]
    policy = {"min_confidence": 0.5}
    with FolderStore(tmp_path / "s") as store:
        k, receipt = admit_packet(
            store,
            text,
            schema,
            candidates,
            policy,
            "grant-1",
            [],
            references=refs,
            document_source="https://example.org/grant",
            packs=[LAC],
        )
        assert receipt.to_dict()["packs"][0]["id"] == "lac-x-test"
        packet = json.loads(store.get("packet@1", k))
        assert packet["format"] == "packet@1" and packet["spec"] == "0.12"
        assert packet["document"] == {
            "id": "grant-1",
            "source": "https://example.org/grant",
            "text": key("text@1", text.encode()),
        }
        assert packet["packs"] == [key("pack@1", jcs(LAC).encode())]
        assert packet["references"] == [key("reference@1", jcs(refs[0]).encode())]
        assert packet["reading"] is None and packet["run"] is None
        found = load_packet(store, k)
        assert (found.text, found.schema, found.candidates) == (text, schema, candidates)
        assert found.inputs() == {
            "policy": policy,
            "judgments": [],
            "references": refs,
            "document_source": "https://example.org/grant",
            "packs": [LAC],
        }
        check = gg.verify(
            found.receipt, found.text, found.schema, found.candidates, **found.inputs()
        )
        assert check.ok, check.problems
        k2, _ = admit_packet(store, text, schema, candidates, policy, "grant-1", [],
                             references=refs, document_source="https://example.org/grant",
                             packs=[LAC])  # fmt: skip
        assert k2 == k
        k3, _ = admit_packet(store, text, schema, candidates, policy, "grant-2", [],
                             references=refs, document_source="https://example.org/grant",
                             packs=[LAC])  # fmt: skip
        assert k3 != k


def test_no_references_and_an_empty_list_verify(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        for refs in (None, []):
            k, _ = admit_packet(store, TEXT, SCHEMA, cands(), references=refs)
            found = load_packet(store, k)
            assert found.references is None and found.policy is None and found.judgments is None
            check = gg.verify(found.receipt, found.text, found.schema, found.candidates)
            assert check.ok, check.problems


def test_a_change_from_canonical_json_is_refused(tmp_path: Path) -> None:
    with FolderStore(tmp_path / "s") as store:
        bad = [dict(cands()[1], value=3.0)]  # a fraction is not allowed, but 3 is
        with pytest.raises(PacketError, match=r"5, not 5\.0"):
            admit_packet(store, TEXT, SCHEMA, bad)
        assert not (tmp_path / "s" / "objects").exists()  # nothing written
        tuples = [dict(c, evidence=c["evidence"]) for c in cands()]
        k, _ = admit_packet(store, TEXT, SCHEMA, tuple(tuples), {"min_confidence": 1.0})
        found = load_packet(store, k)
        assert gg.verify(found.receipt, found.text, found.schema, found.candidates,
                         **found.inputs()).ok  # fmt: skip


def test_input_deleted_and_input_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "s"
    with FolderStore(root, clock=clock) as store:
        k, _ = admit_packet(store, TEXT, SCHEMA, cands())
        packet = json.loads(store.get("packet@1", k))
        store.forget(packet["document"]["text"], "the tenant asked\x1b[31m\U000e0001")
    assert main(["verify", "--store", str(root), k]) == 2
    err = capsys.readouterr().err
    text_key = packet["document"]["text"]
    assert err == (
        f"groundgate: input deleted: the text@1 object {text_key} was deleted at "
        "2026-10-20T09:30:00Z, reason: the tenant asked\\u001b[31m\\U000e0001\n"
    )
    assert "mismatch" not in err
    assert main(["report", "--store", str(root), k]) == 2
    assert "input deleted" in capsys.readouterr().err

    root = tmp_path / "s2"
    with FolderStore(root) as store:
        k, _ = admit_packet(store, TEXT, SCHEMA, cands())
    hexes = packet["candidates"][7:]
    os.unlink(root / "objects" / hexes[:2] / hexes[2:])  # no record in the deleted log
    with FolderStore(root) as store, pytest.raises(InputGone) as gone:
        load_packet(store, k)
    assert gone.value.deleted is None and gone.value.kind == "candidates@1"
    assert str(gone.value) == (
        f"input missing: the candidates@1 object {packet['candidates']} is not in the store"
    )
    other = key("packet@1", b"{}")
    assert main(["verify", "--store", str(root), other]) == 2
    assert f"input missing: the packet@1 object {other}" in capsys.readouterr().err


def test_untrusted_store_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        k, _ = admit_packet(store, TEXT, SCHEMA, cands())
        packet = json.loads(store.get("packet@1", k))

        def put(changed: dict[str, Any]) -> str:
            return store.put("packet@1", jcs(changed).encode())

        cases = {
            "extra member": put({**packet, "path": "../../etc"}),
            "path as key": put({**packet, "schema": "../../etc/passwd"}),
            "short key": put({**packet, "receipt": "sha256:00"}),
            "format": put({**packet, "format": "packet@2"}),
            "references": put({**packet, "references": "sha256:" + "0" * 64}),
            "document": put({**packet, "document": {**packet["document"], "text": None}}),
            "document id": put({**packet, "document": {**packet["document"], "id": "other"}}),
            "wrong kind": put({**packet, "schema": packet["candidates"]}),
            "spec": put({**packet, "spec": "9.9"}),
        }
        for name, bad in cases.items():
            with pytest.raises(StoreError):
                load_packet(store, bad)
            assert main(["verify", "--store", str(root), bad]) == 2, name
        with pytest.raises(ValueError, match="not a store key"):
            load_packet(store, "../objects")
        twice = jcs(packet).encode()[:-1] + b',"run":null}'  # a duplicate member
        dup = key("packet@1", twice)
        folder = root / "objects" / dup[7:9]
        folder.mkdir(mode=0o700, exist_ok=True)
        (folder / dup[9:]).write_bytes(twice)
        with pytest.raises(StoreError, match="not canonical JSON: a duplicate member"):
            load_packet(store, dup)
    capsys.readouterr()
    assert main(["verify", "--store", str(root), "../objects"]) == 2
    assert "is not a store key" in capsys.readouterr().err

    hexes = packet["schema"][7:]
    (root / "objects" / hexes[:2] / hexes[2:]).write_bytes(b'{"fields":{}}')
    assert main(["verify", "--store", str(root), k]) == 2
    assert "does not match its key" in capsys.readouterr().err
    assert main(["verify", "--store", str(tmp_path / "none"), k]) == 2
    assert "store folder is not there" in capsys.readouterr().err


def test_a_crafted_store_layout_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "s"
    with FolderStore(root) as store:
        layout = {"groundgate_layout": "0.1", "pages": [], "words": []}  # no document_sha256
        text = store.put("text@1", TEXT.encode())
        reading = {
            "format": "reading@1",
            "source": store.put("source@1", TEXT.encode()),
            "reader": {"name": "groundgate.read", "version": "0"},
            "options": {"pages": None},
            "text": text,
            "layout": store.put("layout@1", jcs(layout).encode()),
            "document": None,
        }
        reading_key = store.put("reading@1", jcs(reading).encode())
        k, _ = admit_packet(store, TEXT, SCHEMA, cands(), reading=reading_key)
    assert main(["report", "--store", str(root), k]) == 2
    err = capsys.readouterr().err
    assert err == "groundgate: malformed layout: 'document_sha256'\n"
    assert "Traceback" not in err


def test_a_reading_of_another_text_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "a.txt"
    source.write_text("Another text.", encoding="utf-8")
    with FolderStore(tmp_path / "s") as store:
        reading, doc = put_reading(store, source)
        assert doc.text == "Another text."
        with pytest.raises(PacketError, match="of another text"):
            admit_packet(store, TEXT, SCHEMA, cands(), reading=reading)
        with pytest.raises(PacketError, match="not a store key"):
            admit_packet(store, TEXT, SCHEMA, cands(), reading="a.txt")
        with pytest.raises(ValueError, match="not a regular file"):
            put_reading(store, tmp_path)
        layoutless = json.loads(store.get("reading@1", reading))
        assert layoutless["layout"] is None and layoutless["reader"]["name"] == "groundgate.read"
        assert store.get("source@1", layoutless["source"]) == b"Another text."


@pytest.mark.parametrize("name", ["a.txt", "a.pdf"])
def test_one_read_gives_the_source_and_the_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """The file changes after put_reading reads it. The text still comes from the source."""
    source = tmp_path / name
    if name.endswith(".pdf"):
        first, second = make_pdf([[(72, 700, "Fee: $500")]]), make_pdf([[(72, 700, "Fee: $9")]])
    else:
        first, second = b"Fee: $500", b"Fee: $9"
    source.write_bytes(first)
    import groundgate.read as reader

    real = reader.read

    def change_then_read(*args: Any, **kwargs: Any) -> Any:
        source.write_bytes(second)
        return real(*args, **kwargs)

    monkeypatch.setattr(reader, "read", change_then_read)
    with FolderStore(tmp_path / "s") as store:
        reading, doc = put_reading(store, source)
        obj = json.loads(store.get("reading@1", reading))
        assert store.get("source@1", obj["source"]) == first
        assert store.get("text@1", obj["text"]).decode() == doc.text
        assert doc.text.strip() == "Fee: $500"


FEE_PDF = make_pdf([[(72, 700, "Fee: $500")], []])


def _no_read(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("read ran on a cache hit")


def _count_reads(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    import groundgate.read as reader

    real, calls = reader.read, []

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(reader, "read", counted)
    return calls


def test_read_store_uses_the_reading_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(FEE_PDF)
    root = tmp_path / "s"
    argv = ["read", "--store", str(root), str(source), "--pages", "1-3"]
    assert main(argv) == 0
    first = capsys.readouterr()
    assert main(["store", "rebuild", "--store", str(root)]) == 0
    capsys.readouterr()
    import groundgate.read as reader

    monkeypatch.setattr(reader, "read", _no_read)
    assert main(argv) == 0
    again = capsys.readouterr()
    assert (again.out, again.err) == (first.out, first.err)
    assert "page 2 has no text layer" in again.err and "fewer pages" in again.err
    with FolderStore(root) as store:
        k = first.out.strip()
        hit, doc = put_reading(store, source, [1, 2, 3])
        assert hit == k and "Fee: $500" in doc.text
        stored = json.loads(store.get("reading@1", k))["layout"]
        assert doc.layout.to_dict() == json.loads(store.get("layout@1", stored))


def test_only_a_pdf_hits_the_reading_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A reading does not name the format of a file that is not a PDF. The same bytes as text
    and as HTML give other text, so the cache must not give the one for the other."""
    data = b"Fee must be less than <!-- $500 -->."
    (tmp_path / "a.txt").write_bytes(data)
    (tmp_path / "a.html").write_bytes(data)
    with FolderStore(tmp_path / "s") as store:
        k, _ = put_reading(store, tmp_path / "a.txt")
        rebuild(store)
        calls = _count_reads(monkeypatch)
        again, doc = put_reading(store, tmp_path / "a.txt")
        assert again == k and "$500" in doc.text and len(calls) == 1
        html, doc = put_reading(store, tmp_path / "a.html")
        assert html != k and "$500" not in doc.text and len(calls) == 2


def test_a_new_reader_version_misses_the_reading_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(FEE_PDF)
    with FolderStore(tmp_path / "s") as store:
        k, _ = put_reading(store, source)
        rebuild(store)
        calls = _count_reads(monkeypatch)
        assert put_reading(store, source)[0] == k and not calls
        assert put_reading(store, source, [1])[0] != k and len(calls) == 1
        monkeypatch.setattr(gg, "__version__", "99.0.0")
        newer, _ = put_reading(store, source)
        assert newer != k and len(calls) == 2
        assert json.loads(store.get("reading@1", newer))["reader"]["version"] == "99.0.0"


def test_read_store_writes_the_document_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``read --store --document`` writes ``document@1``, and the reading names it (#407)."""
    from groundgate.read.document import Document

    source = tmp_path / "a.pdf"
    source.write_bytes(FEE_PDF)
    root = tmp_path / "s"
    out = tmp_path / "doc.json"
    assert main(["read", "--store", str(root), str(source), "--document", str(out)]) == 0
    k = capsys.readouterr().out.strip()
    assert main(["read", str(source), "--document", str(tmp_path / "plain.json")]) == 0
    capsys.readouterr()
    assert out.read_bytes() == (tmp_path / "plain.json").read_bytes()
    with FolderStore(root) as store:
        reading = json.loads(store.get("reading@1", k))
        assert reading["document"] == key("document@1", out.read_bytes())
        text = store.get("text@1", reading["text"]).decode("utf-8")
        model = Document.from_dict(json.loads(store.get("document@1", reading["document"])), text)
        assert model.text == text and "Fee: $500" in text
        assert json.loads(out.read_bytes())["text"] == reading["text"]


def test_a_read_with_the_document_model_does_not_use_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(FEE_PDF)
    with FolderStore(tmp_path / "s") as store:
        plain, _ = put_reading(store, source)
        rebuild(store)
        import groundgate.read.document as model

        calls: list[object] = []
        real = model.read_document

        def counted(*args: Any, **kwargs: Any) -> Any:
            calls.append(args)
            return real(*args, **kwargs)

        monkeypatch.setattr(model, "read_document", counted)
        k, doc = put_reading(store, source, document=True)
        assert k != plain and len(calls) == 1 and "Fee: $500" in doc.text
        assert json.loads(store.get("reading@1", plain))["document"] is None
        assert put_reading(store, source, document=True)[0] == k and len(calls) == 2
        # Two readings of one source, reader and options: the cache gives no hit.
        rebuild(store)
        reads = _count_reads(monkeypatch)
        assert put_reading(store, source)[0] == plain and len(reads) == 1


def test_a_bad_reading_cache_is_a_miss(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(FEE_PDF)
    root = tmp_path / "s"
    with FolderStore(root) as store:
        k, _ = put_reading(store, source)
        rebuild(store)
        view = root / "views" / "readings.json"
        cache = json.loads(view.read_bytes())
        other = tmp_path / "b.pdf"
        other.write_bytes(make_pdf([[(72, 700, "Fee: $9")]]))
        wrong, _ = put_reading(store, other)
        calls = _count_reads(monkeypatch)
        two = json.loads(json.dumps(cache))
        two["readings"][0]["readings"] = sorted([k, wrong])
        swapped = json.loads(json.dumps(cache))
        swapped["readings"][0]["readings"] = [wrong]
        for bad in (b"not json", b"[]", jcs(two).encode(), jcs(swapped).encode()):
            view.write_bytes(bad)
            again, doc = put_reading(store, source)
            assert again == k and "Fee: $500" in doc.text
        assert len(calls) == 4
        deep = "[" * 1100 + "]" * 1100
        nested = jcs(cache).replace(json.dumps(cache["readings"][0]["source"]), deep, 1)
        for bad in (b"[" * 100000, nested.encode()):
            view.write_bytes(bad)
            again, doc = put_reading(store, source)
            assert again == k and "Fee: $500" in doc.text
        calls.clear()
        view.write_bytes(jcs(cache).encode())
        store.forget(json.loads(store.get("reading@1", k))["text"], "test")
        again, doc = put_reading(store, source)
        assert again == k and "Fee: $500" in doc.text and len(calls) == 1


def test_layout_needs_a_pdf_before_the_store_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = tmp_path / "a.html"
    page.write_text("<p>Fee: $500</p>", encoding="utf-8")
    store = tmp_path / "s"
    argv = ["read", "--store", str(store), str(page), "--layout", str(tmp_path / "l.json")]
    assert main(argv) == 2
    assert capsys.readouterr().err == "groundgate: --layout needs a PDF\n"
    assert not store.exists()
    missing = ["read", str(tmp_path / "none.html"), "--layout", str(tmp_path / "l.json")]
    assert main(missing) == 2  # without --store, the read error comes first, as before
    assert "--layout needs a PDF" not in capsys.readouterr().err


def test_store_options_need_their_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    given = files(tmp_path, schema=SCHEMA, cands=cands())
    doc = tmp_path / "doc.txt"
    doc.write_text(TEXT, encoding="utf-8")
    store = str(tmp_path / "s")
    bad = [
        ["verify", "--store", store, "sha256:x", str(doc)],
        ["verify", "--store", store, "sha256:x", "--policy", given["schema"]],
        ["report", "--store", store, "sha256:x", "--pack", given["schema"]],
        ["verify", "r.json", str(doc), given["schema"]],
        ["admit", str(doc), given["schema"], given["cands"], "--reading", "sha256:x"],
        ["admit", "--docs", ".", "--candidates", ".", "--schema", "s", "--out", "o",
         "--store", store, "--reading", "sha256:x"],
    ]  # fmt: skip
    for argv in bad:
        with pytest.raises(SystemExit) as stop:
            main(argv)
        assert stop.value.code == 2, argv
    err = capsys.readouterr().err
    assert "remove DOC SCHEMA CANDIDATES" in err and "remove --policy" in err
    assert "--reading needs --store" in err and "batch admit cannot use --reading" in err
