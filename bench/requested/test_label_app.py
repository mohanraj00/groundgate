"""Blind-label edits, seal validation and local HTTP trust boundaries."""

from __future__ import annotations

import copy
import hashlib
import http.client
import json
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from requested.label_app import MAX_BODY, LabelServer, LabelStore


@pytest.fixture
def store(tmp_path: Path) -> LabelStore:
    directory = tmp_path / "set"
    directory.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()
    original = b"%PDF original"
    digest = "sha256:" + hashlib.sha256(original).hexdigest()
    for ident in ("dev", "hold"):
        (sources / f"{ident}.pdf").write_bytes(original)
    manifest = {
        "status": "frozen",
        "schemas": {
            "kind": {
                "fields": {
                    "amount": {"type": "number", "unit": "USD", "keys": ["current", "prior"]},
                    "name": {"type": "string"},
                }
            }
        },
        "documents": [
            {
                "id": "dev",
                "kind": "kind",
                "split": "development",
                "source_sha256": digest,
                "source_pages": 4,
            },
            {
                "id": "hold",
                "kind": "kind",
                "split": "heldout",
                "source_sha256": digest,
                "source_pages": 4,
            },
        ],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return LabelStore(directory, sources)


def filled(store: LabelStore, ident: str) -> list[dict[str, Any]]:
    fields = store.blank_fields(ident)
    for slot in fields:
        slot.update(
            status="present",
            page=1,
            values=[
                {
                    "value": "ten" if slot["field"] == "name" else "10",
                    "unit": None if slot["field"] == "name" else "USD",
                }
            ],
        )
    return fields


def save_all(store: LabelStore) -> None:
    for ident in store.documents:
        store.save({"id": ident, "fields": filled(store, ident)})


def test_no_guessed_values_and_editable_drafts(store: LabelStore) -> None:
    labels = store.labels()
    assert all(
        slot["status"] == "unlabeled" and slot["values"] == []
        for doc in labels["documents"]
        for slot in doc["fields"]
    )
    assert not store.path.exists()
    store.save({"id": "dev", "fields": filled(store, "dev")})
    changed = filled(store, "dev")
    changed[0]["values"][0]["value"] = "20"
    store.save({"id": "dev", "fields": changed})
    assert store.labels()["documents"][0]["fields"][0]["values"][0]["value"] == "20"
    assert not list(store.work_directory.glob(".labels-*.tmp"))


def test_seal_requires_both_splits_and_locks_every_edit(store: LabelStore) -> None:
    store.save({"id": "dev", "fields": filled(store, "dev")})
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="every field/key"):
        store.seal()
    assert store.path.read_bytes() == before
    store.save({"id": "hold", "fields": filled(store, "hold")})
    store.seal()
    assert store.labels()["status"] == "sealed"
    sealed = store.path.read_bytes()
    with pytest.raises(ValueError, match="sealed"):
        store.save({"id": "dev", "fields": filled(store, "dev")})
    with pytest.raises(ValueError, match="sealed"):
        store.seal()
    assert store.path.read_bytes() == sealed


@pytest.mark.parametrize(
    "state,changes,error",
    [
        ("unclear", {}, "reason"),
        ("absent", {}, "second blind"),
        ("present", {"page": None}, "original PDF page"),
    ],
)
def test_seal_enforces_label_evidence(
    store: LabelStore, state: str, changes: dict[str, Any], error: str
) -> None:
    save_all(store)
    fields = filled(store, "dev")
    fields[0].update(status=state, **changes)
    if state != "present":
        fields[0]["values"] = []
    store.save({"id": "dev", "fields": fields})
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match=error):
        store.seal()
    assert store.path.read_bytes() == before


def test_absent_and_unclear_can_be_sealed_with_manual_checks(store: LabelStore) -> None:
    save_all(store)
    fields = filled(store, "dev")
    fields[0].update(status="absent", values=[], second_check=True, page=None)
    fields[1].update(status="unclear", values=[], reason="The condition has no unique value.")
    store.save({"id": "dev", "fields": fields})
    store.seal()
    assert store.labels()["status"] == "sealed"


def test_run_presence_blocks_without_reading_model_output(store: LabelStore) -> None:
    (store.directory / "runs").mkdir()
    (store.directory / "runs/cached.json").write_text("not even valid JSON")
    assert "cached run" in str(store.state()["blocked"])
    with pytest.raises(ValueError, match="cached run"):
        store.save({"id": "dev", "fields": filled(store, "dev")})
    with pytest.raises(ValueError, match="cached run"):
        store.seal()
    assert not store.path.exists()


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unit", "number", "unknown"])
def test_malformed_field_slots_never_replace_draft(store: LabelStore, mutation: str) -> None:
    store.save({"id": "dev", "fields": filled(store, "dev")})
    before = store.path.read_bytes()
    fields = filled(store, "dev")
    if mutation == "missing":
        fields.pop()
    elif mutation == "duplicate":
        fields[1] = copy.deepcopy(fields[0])
    elif mutation == "unit":
        fields[0]["values"][0]["unit"] = "EUR"
    elif mutation == "number":
        fields[0]["values"][0]["value"] = "guess"
    else:
        fields[0]["field"] = "unrequested"
    with pytest.raises(ValueError):
        store.save({"id": "dev", "fields": fields})
    assert store.path.read_bytes() == before


def test_unknown_ids_and_source_symlinks_cannot_escape(store: LabelStore, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown document"):
        store.save({"id": "../../other", "fields": []})
    with pytest.raises(ValueError, match="unknown source"):
        store.source("../manifest", "pdf")
    outside = tmp_path / "private.pdf"
    outside.write_bytes(b"private")
    (store.sources / "dev.pdf").unlink()
    (store.sources / "dev.pdf").symlink_to(outside)
    with pytest.raises(ValueError, match="not found"):
        store.source("dev", "pdf")
    assert not store.path.exists()


@pytest.fixture
def server(store: LabelStore) -> Any:
    server = LabelServer(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(
    server: LabelServer,
    method: str,
    path: str,
    body: bytes = b"",
    *,
    authorized: bool = True,
    include_headers: bool = False,
    **headers: str,
) -> Any:
    if authorized:
        path = server.base_path + path.lstrip("/")
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    data = response.read()
    status = response.status
    response_headers = dict(response.getheaders())
    connection.close()
    return (status, data, response_headers) if include_headers else (status, data)


def test_http_requires_token_origin_and_safe_host(server: LabelServer) -> None:
    assert server.server_address[0] == "127.0.0.1"
    status, data = request(server, "GET", "/api/state")
    assert status == 200
    assert json.loads(data)["token"] == server.token
    assert (
        request(server, "POST", "/api/seal", b"{}", **{"Content-Type": "application/json"})[0]
        == 403
    )
    auth = {"Content-Type": "application/json", "X-Label-Token": server.token}
    assert (
        request(server, "POST", "/api/seal", b"{}", Origin="https://other.example", **auth)[0]
        == 403
    )
    assert request(server, "GET", "/api/state", Host="other.example")[0] == 403


def test_http_body_limits_unknown_ids_and_no_arbitrary_files(server: LabelServer) -> None:
    auth = {"Content-Type": "application/json", "X-Label-Token": server.token}
    body = json.dumps({"id": "../../escape", "fields": []}).encode()
    assert request(server, "POST", "/api/save", body, **auth)[0] == 400
    # Reject the declared size before upload, without racing a large send against server close.
    oversized = auth | {"Content-Length": str(MAX_BODY + 1)}
    assert request(server, "POST", "/api/save", **oversized)[0] == 413
    assert request(server, "POST", "/api/save", b'{"id":NaN}', **auth)[0] == 400
    assert request(server, "GET", "/pdf/../manifest")[0] == 404
    assert request(server, "GET", "/labels.json")[0] == 404
    assert request(server, "GET", "/runs/cached.json")[0] == 404
    assert request(server, "GET", "/api/state?callback=other")[0] == 404


def test_http_serves_only_allowlisted_original_sources(server: LabelServer) -> None:
    (server.store.sources / "dev.pdf").write_bytes(b"%PDF original")
    (server.store.sources / "dev.txt").write_text("original text")
    assert request(server, "GET", "/pdf/dev") == (200, b"%PDF original")
    assert request(server, "GET", "/text/dev") == (200, b"original text")
    assert request(server, "GET", "/pdf/unknown")[0] == 400


def test_draft_manifest_saves_but_cannot_seal(store: LabelStore) -> None:
    store.manifest["status"] = "draft"
    (store.directory / "manifest.json").write_text(json.dumps(store.manifest))
    save_all(store)
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="manifest must be frozen"):
        store.seal()
    assert store.path.read_bytes() == before


def test_changed_manifest_cannot_seal_stale_labels(store: LabelStore) -> None:
    save_all(store)
    changed = copy.deepcopy(store.manifest)
    changed["documents"][0]["source_url"] = "https://other.example/source.pdf"
    (store.directory / "manifest.json").write_text(json.dumps(changed))
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="manifest changed"):
        store.seal()
    assert store.path.read_bytes() == before


def test_failed_metrics_validation_preserves_exact_draft(
    store: LabelStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_all(store)
    before = store.path.read_bytes()

    def refuse(*args: Any) -> None:
        raise ValueError("metric validation refused")

    monkeypatch.setattr("requested.label_app.measure", refuse)
    with pytest.raises(ValueError, match="metric validation refused"):
        store.seal()
    assert store.path.read_bytes() == before


def test_labels_symlink_is_never_read_or_overwritten(store: LabelStore, tmp_path: Path) -> None:
    outside = tmp_path / "other-labels.json"
    outside.write_text('{"status":"draft","documents":[]}')
    store.path.symlink_to(outside)
    before = outside.read_bytes()
    with pytest.raises(ValueError, match="symlink"):
        store.save({"id": "dev", "fields": filled(store, "dev")})
    assert outside.read_bytes() == before


def test_http_rejects_duplicate_json_members(server: LabelServer) -> None:
    auth = {"Content-Type": "application/json", "X-Label-Token": server.token}
    body = b'{"id":"dev","id":"hold","fields":[]}'
    assert request(server, "POST", "/api/save", body, **auth)[0] == 400


def test_atomic_replace_failure_preserves_draft_and_cleans_temp(
    store: LabelStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_all(store)
    before = store.path.read_bytes()

    def refuse(source: str, target: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("requested.label_app.os.replace", refuse)
    with pytest.raises(OSError, match="replace failed"):
        store.save({"id": "dev", "fields": filled(store, "dev")})
    assert store.path.read_bytes() == before
    assert not list(store.work_directory.glob(".labels-*.tmp"))


def test_http_writes_only_after_explicit_authenticated_post(server: LabelServer) -> None:
    assert request(server, "GET", "/")[0] == 200
    assert request(server, "GET", "/api/state")[0] == 200
    assert not server.store.path.exists()
    auth = {"Content-Type": "application/json", "X-Label-Token": server.token}
    for ident in server.store.documents:
        payload = {"id": ident, "fields": filled(server.store, ident)}
        assert request(server, "POST", "/api/save", json.dumps(payload).encode(), **auth)[0] == 200
    assert server.store.labels()["status"] == "draft"
    assert request(server, "POST", "/api/seal", b"{}", **auth)[0] == 200
    assert server.store.labels()["status"] == "sealed"


def test_swapped_original_pdf_is_not_served_or_sealed(server: LabelServer) -> None:
    save_all(server.store)
    before = server.store.path.read_bytes()
    (server.store.sources / "dev.pdf").write_bytes(b"%PDF swapped source")
    status, data = request(server, "GET", "/pdf/dev")
    assert status == 400
    assert b"hash does not match" in data
    assert b"swapped source" not in data
    with pytest.raises(ValueError, match="hash does not match"):
        server.store.seal()
    assert server.store.path.read_bytes() == before


def test_missing_source_prevents_seal(store: LabelStore) -> None:
    save_all(store)
    before = store.path.read_bytes()
    (store.sources / "hold.pdf").unlink()
    with pytest.raises(ValueError, match="not found"):
        store.seal()
    assert store.path.read_bytes() == before


def test_missing_hash_prevents_serving_and_seal(store: LabelStore) -> None:
    store.documents["dev"].pop("source_sha256")
    with pytest.raises(ValueError, match="pinned source_sha256"):
        store.verified_pdf("dev")


def test_evidence_page_cannot_exceed_original_page_count(store: LabelStore) -> None:
    fields = filled(store, "dev")
    fields[0]["page"] = 5
    with pytest.raises(ValueError, match="page count"):
        store.save({"id": "dev", "fields": fields})
    fields[0]["page"] = 4
    store.save({"id": "dev", "fields": fields})


def test_write_temporary_files_stay_in_external_work_directory(store: LabelStore) -> None:
    assert not store.work_directory.is_relative_to(store.directory)
    save_all(store)
    assert store.work_directory.is_dir()
    assert not list(store.work_directory.iterdir())
    assert not list(store.directory.glob(".labels-*.tmp"))


@pytest.fixture
def renderer(store: LabelStore, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    store.renderer = "/test-tools/pdftoppm"

    def render(command: list[str], **kwargs: Any) -> None:
        calls.append(command)
        assert kwargs["input"] == b"%PDF original"
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 30
        assert "shell" not in kwargs
        assert command[command.index("-f") + 1] == command[command.index("-l") + 1]
        prefix = Path(command[-1])
        assert prefix.is_relative_to(store.work_directory)
        prefix.with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic page pixels")

    monkeypatch.setattr("requested.label_app.subprocess.run", render)
    return calls


def test_preview_renders_only_one_page_and_reuses_hash_cache(
    store: LabelStore, renderer: list[list[str]]
) -> None:
    expected = b"\x89PNG\r\n\x1a\nsynthetic page pixels"
    assert store.preview("dev", 3) == expected
    assert store.preview("dev", 3) == expected
    assert len(renderer) == 1
    assert renderer[0][renderer[0].index("-f") + 1] == "3"
    assert renderer[0][-2] == "-"  # renderer reads the already verified snapshot from stdin
    assert (store.sources / "dev.pdf").read_bytes() == b"%PDF original"
    cached = list((store.work_directory / "previews").rglob("*.png"))
    assert len(cached) == 1
    assert cached[0].parent.name == hashlib.sha256(b"%PDF original").hexdigest()
    assert not list(store.work_directory.glob("page-*"))


def test_preview_reverifies_source_even_when_image_is_cached(
    store: LabelStore, renderer: list[list[str]]
) -> None:
    store.preview("dev", 1)
    (store.sources / "dev.pdf").write_bytes(b"%PDF replacement")
    with pytest.raises(ValueError, match="hash does not match"):
        store.preview("dev", 1)
    assert len(renderer) == 1


def test_page_routes_reject_unsafe_ids_and_bounds(
    server: LabelServer, renderer: list[list[str]]
) -> None:
    for route in (
        "/page/dev/0",
        "/page/dev/-1",
        "/page/dev/5",
        "/page/dev/1.5",
        "/page/unknown/1",
        "/page/../../private/1",
        "/page/dev%2fother/1",
    ):
        assert request(server, "GET", route)[0] in {400, 404}
    assert renderer == []
    assert request(server, "GET", "/page/dev/1") == (200, b"\x89PNG\r\n\x1a\nsynthetic page pixels")


def test_preview_unavailable_exposes_browser_fallback(server: LabelServer) -> None:
    server.store.renderer = None
    _, data = request(server, "GET", "/api/state")
    assert json.loads(data)["preview_available"] is False
    assert request(server, "GET", "/page/dev/1")[0] == 400
    assert request(server, "GET", "/pdf/dev") == (200, b"%PDF original")


def test_renderer_failure_cleans_external_temporary_files(
    store: LabelStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.renderer = "/test-tools/pdftoppm"

    def refuse(command: list[str], **kwargs: Any) -> None:
        raise OSError("unavailable")

    monkeypatch.setattr("requested.label_app.subprocess.run", refuse)
    with pytest.raises(ValueError, match="preview failed"):
        store.preview("dev", 1)
    assert not list(store.work_directory.glob("page-*"))
    assert not list(store.work_directory.rglob("*.png"))


def test_preview_cache_symlink_does_not_read_an_external_image(
    store: LabelStore, tmp_path: Path, renderer: list[list[str]]
) -> None:
    store.preview("dev", 1)
    cached = next(store.work_directory.rglob("*.png"))
    cached.unlink()
    outside = tmp_path / "unrelated.png"
    outside.write_bytes(b"private unrelated bytes")
    cached.symlink_to(outside)
    with pytest.raises(ValueError, match="unsafe preview cache"):
        store.preview("dev", 1)
    assert len(renderer) == 1


def test_non_ascii_csrf_token_is_rejected_without_server_failure(server: LabelServer) -> None:
    assert (
        request(
            server,
            "POST",
            "/api/seal",
            b"{}",
            **{"Content-Type": "application/json", "X-Label-Token": "\u00e9"},
        )[0]
        == 403
    )


def test_state_reports_optional_text_only_for_confined_existing_sources(
    store: LabelStore, tmp_path: Path
) -> None:
    def availability() -> dict[str, bool]:
        return {doc["id"]: doc["source_text_available"] for doc in store.state()["documents"]}

    assert availability() == {"dev": False, "hold": False}
    (store.sources / "dev.txt").write_text("Original source text.")
    outside = tmp_path / "unrelated.txt"
    outside.write_text("Private unrelated text.")
    (store.sources / "hold.txt").symlink_to(outside)
    assert availability() == {"dev": True, "hold": False}
    with pytest.raises(ValueError, match="not found"):
        store.source("hold", "txt")
    (store.sources / "dev.txt").unlink()
    assert availability() == {"dev": False, "hold": False}


@pytest.mark.parametrize("mode", ["argument", "environment", "argument_overrides_environment"])
def test_cli_accepts_explicit_local_root(
    store: LabelStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from requested import label_app

    command = ["label_app.py", "--set", str(store.directory), "--source-dir", str(store.sources)]
    monkeypatch.delenv("GROUNDGATE_LOCAL_WORK", raising=False)
    if mode == "environment":
        monkeypatch.setenv("GROUNDGATE_LOCAL_WORK", str(tmp_path))
    else:
        command += ["--local-root", str(tmp_path)]
        if mode == "argument_overrides_environment":
            monkeypatch.setenv("GROUNDGATE_LOCAL_WORK", str(tmp_path / "wrong-root"))
    closed = []

    class StubServer:
        def __init__(self, selected_store: LabelStore, port: int) -> None:
            assert selected_store.sources.is_relative_to(tmp_path)
            assert selected_store.work_directory.is_relative_to(tmp_path)
            self.server_port = port
            self.url = f"http://127.0.0.1:{port}/session/synthetic-startup-capability/"

        def serve_forever(self) -> None:
            raise KeyboardInterrupt

        def server_close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(label_app, "LabelServer", StubServer)
    monkeypatch.setattr(sys, "argv", command)
    label_app.main()
    assert closed == [True]
    assert "http://127.0.0.1:8784/session/synthetic-startup-capability/" in capsys.readouterr().out
    assert all("synthetic-startup-capability" not in argument for argument in command)


def test_cli_requires_local_root_instead_of_assuming_a_home_path(
    store: LabelStore, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from requested import label_app

    monkeypatch.delenv("GROUNDGATE_LOCAL_WORK", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        ["label_app.py", "--set", str(store.directory), "--source-dir", str(store.sources)],
    )
    with pytest.raises(SystemExit) as error:
        label_app.main()
    assert error.value.code == 2
    assert "--local-root or GROUNDGATE_LOCAL_WORK is required" in capsys.readouterr().err


@pytest.mark.parametrize("outside", ["source", "work", "source_symlink"])
def test_cli_refuses_paths_outside_the_selected_root(
    store: LabelStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outside: str,
) -> None:
    from requested import label_app

    root = tmp_path / "allowed" if outside != "work" else tmp_path
    root.mkdir(exist_ok=True)
    source = store.sources
    extra = []
    if outside == "source_symlink":
        source = root / "source-link"
        source.symlink_to(store.sources, target_is_directory=True)
    if outside == "work":
        extra = ["--work-dir", str(tmp_path.parent / "outside-scratch")]
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "label_app.py",
            "--set",
            str(store.directory),
            "--source-dir",
            str(source),
            "--local-root",
            str(root),
            *extra,
        ],
    )
    with pytest.raises(SystemExit) as error:
        label_app.main()
    assert error.value.code == 2
    assert "must be inside the local work directory" in capsys.readouterr().err


def test_optional_local_text_is_explicitly_unpinned_until_digest_supplied(
    server: LabelServer,
) -> None:
    raw = b"Local source text."
    path = server.store.sources / "dev.txt"
    path.write_bytes(raw)
    state = server.store.state()
    assert state["documents"][0]["source_text_available"] is True
    assert state["documents"][0]["source_text_hash_pinned"] is False
    assert request(server, "GET", "/text/dev") == (200, raw)
    server.store.documents["dev"]["text_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    assert server.store.state()["documents"][0]["source_text_hash_pinned"] is True
    assert request(server, "GET", "/text/dev") == (200, raw)
    path.write_bytes(b"Swapped local text.")
    status, error = request(server, "GET", "/text/dev")
    assert status == 400
    assert b"hash does not match" in error
    assert b"Swapped local text" not in error


def test_unauthenticated_state_cannot_bootstrap_write_access(server: LabelServer) -> None:
    # A local caller knows the port but has not received the startup capability.
    assert request(server, "GET", "/api/state", authorized=False)[0] == 403
    payload = {"id": "dev", "fields": filled(server.store, "dev")}
    headers = {"Content-Type": "application/json", "X-Label-Token": server.token}
    assert (
        request(
            server, "POST", "/api/save", json.dumps(payload).encode(), authorized=False, **headers
        )[0]
        == 403
    )
    assert request(server, "POST", "/api/seal", b"{}", authorized=False, **headers)[0] == 403
    assert not server.store.path.exists()


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/api/state",
        "/pdf/dev",
        "/text/dev",
        "/page/dev/1",
        "/api/save",
        "/api/seal",
        "/session/wrong/api/state",
    ],
)
def test_every_public_route_denies_without_startup_capability(
    server: LabelServer, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any) -> None:
        pytest.fail("unauthenticated request reached label/source storage")

    for member in ("state", "verified_pdf", "read_source_text", "preview", "save", "seal"):
        monkeypatch.setattr(server.store, member, forbidden)
    for method in ("GET", "POST", "HEAD", "OPTIONS", "PUT", "DELETE"):
        status, body, headers = request(
            server,
            method,
            path,
            b"{}",
            authorized=False,
            include_headers=True,
            **{"Content-Type": "application/json"},
        )
        assert status == 403
        assert server.token.encode() not in body and server.capability.encode() not in body
        assert "Location" not in headers
        assert headers["Referrer-Policy"] == "no-referrer"
    assert not server.store.path.exists()


@pytest.mark.parametrize(
    "target",
    [
        "{base}../api/state",
        "{base}./api/state",
        "{base}api//state",
        "{base}api%2fstate",
        "{base}api/%2e%2e/state",
        "{base}api\\state",
        "{base}api/state?callback=x",
        "{base}api/state#fragment",
        "{base_no_slash}",
        "/{base}api/state",
        "/session/%{first_hex}{rest}/api/state",
        "http://127.0.0.1:{port}{base}api/state",
        "/session/wrong/../{cap}/api/state",
        "/session/{cap}%2fapi/state",
    ],
)
def test_raw_target_never_normalizes_into_a_capability_route(
    server: LabelServer, target: str
) -> None:
    path = target.format(
        base=server.base_path,
        base_no_slash=server.base_path[:-1],
        first_hex=f"{ord(server.capability[0]):02x}",
        rest=server.capability[1:],
        port=server.server_port,
        cap=server.capability,
    )
    status, body, headers = request(server, "GET", path, authorized=False, include_headers=True)
    assert status in {403, 404}
    assert server.token.encode() not in body and server.capability.encode() not in body
    assert "Location" not in headers


def test_authenticated_routes_keep_browser_urls_private_and_relative(server: LabelServer) -> None:
    status, html, headers = request(server, "GET", "/", include_headers=True)
    assert status == 200 and headers["Referrer-Policy"] == "no-referrer"
    assert server.capability.encode() not in html
    for route in ("api/state", "api/save", "api/seal", "pdf/", "text/", "page/"):
        assert route.encode() in html
        assert ("/" + route).encode() not in html
        joined = urlsplit(urljoin(server.url, route))
        assert joined.path.startswith(server.base_path)
    status, body, headers = request(server, "GET", "/api/state", include_headers=True)
    assert status == 200 and json.loads(body)["token"] == server.token
    assert server.capability.encode() not in body
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    status, body, headers = request(server, "OPTIONS", "/", include_headers=True)
    assert status == 501 and headers["Referrer-Policy"] == "no-referrer"
    assert server.token.encode() not in body and server.capability.encode() not in body


def test_startup_capability_is_regenerated_and_old_session_cannot_read(server: LabelServer) -> None:
    other = LabelServer(server.store, 0)
    thread = threading.Thread(target=other.serve_forever, daemon=True)
    thread.start()
    try:
        assert other.capability != server.capability and other.token != server.token
        assert request(other, "GET", server.base_path + "api/state", authorized=False)[0] == 403
        assert request(other, "GET", "/api/state")[0] == 200
    finally:
        other.shutdown()
        other.server_close()
        thread.join(timeout=2)
