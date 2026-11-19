"""The review and audit page of examples/review-page (#647): its server, its pin of the UI kit,
and one answer and one audit answer through the origin of the page.

These tests use no browser and no network. tests/test_review_page_kit_seam.py loads the page in
a browser with the pinned kit."""

from __future__ import annotations

import http.client
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from groundgate.review import api
from groundgate.store import FolderStore, reviewer_key

EXAMPLE = Path(__file__).parent.parent / "examples" / "review-page"
TOKEN = "page-test-token-0123456789-abcdefghijklmnopqrstuvwxyz"


def load_run() -> Any:
    """The module examples/review-page/run.py. It is not in a package, so the tests load it by
    its path."""
    spec = importlib.util.spec_from_file_location("review_page_run", EXAMPLE / "run.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


run = load_run()
Response = tuple[int, dict[str, str], bytes]


def get(
    port: int, path: str, body: Any = None, token: str | None = TOKEN, host: str = ""
) -> Response:
    """One request to the page server. A dict body goes as JSON in a POST."""
    headers = {"Host": host or f"127.0.0.1:{port}"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    raw = None
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        headers |= {"Content-Type": "application/json", "Content-Length": str(len(raw))}
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("GET" if raw is None else "POST", path, skip_host=True)
        for name, value in headers.items():
            conn.putheader(name, value)
        conn.endheaders(raw)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


@pytest.fixture
def kit(tmp_path: Path) -> Path:
    """A folder with the layout of a kit checkout. The files are not the kit."""
    folder = tmp_path / "kit"
    (folder / "src" / "components").mkdir(parents=True)
    (folder / "catalog").mkdir()
    (folder / "tests").mkdir()
    (folder / "src" / "kit.js").write_text("export const kit = 1;\n", "utf-8")
    (folder / "src" / "components" / "index.js").write_text("export {};\n", "utf-8")
    (folder / "src" / "notes.md").write_text("notes\n", "utf-8")
    (folder / "catalog" / "text.json").write_text("{}\n", "utf-8")
    (folder / "tests" / "a.js").write_text("export {};\n", "utf-8")
    (folder / "secret.js").write_text("export {};\n", "utf-8")
    return folder


@pytest.fixture
def page(tmp_path: Path, kit: Path) -> Iterator[tuple[Path, str, int]]:
    """The page and the API on the store of the made-up invoice: the store, the packet key and
    the port of the page."""
    root = tmp_path / "store"
    packet = run.fixture_store(root)
    api_httpd, page_httpd, url = run.start(root, kit, "ana", TOKEN)
    try:
        assert url == f"http://127.0.0.1:{page_httpd.server_port}/#{TOKEN}"
        yield root, packet, page_httpd.server_port
    finally:
        for httpd in (api_httpd, page_httpd):
            httpd.shutdown()
            httpd.server_close()


def records(root: Path, packet: str) -> list[dict[str, Any]]:
    with FolderStore(root) as store:
        return store.read(("answers", packet, reviewer_key("ana")))


def test_an_answer_and_an_audit_answer_through_the_page(page: tuple[Path, str, int]) -> None:
    """The calls that page.js makes, through the origin of the page: the list, a task with its
    document, and an answer. The store gets one answer to the review task and one to the audit
    task, and no response for the audit task shows the proposed value."""
    root, packet, port = page
    status, _, body = get(port, "/v1/tasks?limit=200")
    listed = json.loads(body)
    assert status == 200 and listed["api"] == run.API == api.API and listed["actor"] == "ana"
    by_field = {t["field"]: t for t in listed["tasks"]}
    assert {f: t["mode"] for f, t in by_field.items()} == {"tax": "audit", "total": "review"}

    total = by_field["total"]["task"]
    task = json.loads(get(port, f"/v1/tasks/{total}")[2])
    document = json.loads(get(port, f"/v1/tasks/{total}/document")[2])["text"]
    assert document == run.TEXT
    choice = next(c for c in task["body"]["choices"] if c["value"] == "4200000")
    sent = {"task": total, "verdict": "choose", "choice": choice["choice"]}
    status, _, body = get(port, "/v1/answers", sent)
    assert status == 201 and json.loads(body)["record"]["verdict"] == "choose"

    tax = by_field["tax"]["task"]
    with FolderStore(root) as store:
        keys, _ = store.object_keys()
        hidden = [k for k in keys if b'"mode":"audit"' in store.object_bytes(k).replace(b" ", b"")]
    assert len(hidden) == 1 and re.fullmatch(r"task:[0-9a-f]{64}", tax)
    assert re.fullmatch(r"task:[0-9a-f]{64}", total) and total != tax
    start = run.TEXT.encode("utf-8").index(b"310 thousand")
    correct = {"task": tax, "verdict": "correct"}
    seen = [
        body,
        get(port, f"/v1/tasks/{tax}")[2],
        get(port, "/v1/answers", {**correct, "span": {"start": start, "end": start + 3}})[2],
        get(port, "/v1/answers", {**correct, "span": {"start": start, "end": start + 12}})[2],
        get(port, "/v1/tasks")[2],
    ]
    assert json.loads(seen[1])["body"] is None
    assert json.loads(seen[2])["error"]["code"] == "codes_not_kept"
    assert json.loads(seen[3])["record"] is None and json.loads(seen[4])["tasks"] == []
    for text in seen[1:]:
        for word in (b"310000", b"310,000", b"310 thousand", b"choices", b"evidence", b"question"):
            assert word not in text, (word, text)
    # no response gives a key of the store: a key is a hash over the proposed value
    for text in seen:
        assert hidden[0][7:].encode("ascii") not in text and packet[7:].encode("ascii") not in text
        assert b"sha256" not in text
    written = records(root, packet)
    assert [r["verdict"] for r in written] == ["choose", "correct"]
    assert written[1]["candidate"]["value"] == "310000"


def test_the_page_server_gives_the_page_and_only_the_served_folders_of_the_kit(
    page: tuple[Path, str, int],
) -> None:
    _, _, port = page
    served = {
        "/": "text/html",
        "/page.js": "text/javascript",
        "/page.css": "text/css",
        "/kit/src/kit.js": "text/javascript",
        "/kit/src/components/index.js": "text/javascript",
        "/kit/catalog/text.json": "application/json",
    }
    for path, kind in served.items():
        status, headers, body = get(port, path, token=None)
        assert (status, headers["Content-Type"]) == (200, f"{kind}; charset=utf-8"), path
        assert headers["Content-Security-Policy"] == run.CSP and body
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store"
    assert "script-src 'self'" in run.CSP and "unsafe" not in run.CSP
    # no file outside the served folders, no other type, no folder, no path with dots
    for path in ("/kit/secret.js", "/kit/tests/a.js", "/kit/src/notes.md", "/kit/src/components",
                 "/kit/src/../secret.js", "/kit/src/%2e%2e/secret.js", "/kit/src//kit.js", "/kit/",
                 "/kit", "/run.py", "/kit.jsonx", "/page.js?x=1", "/index.html"):  # fmt: skip
        assert get(port, path, token=None)[0] == 404, path
    status, headers, body = get(port, "/kit.json", token=None)
    assert status == 200 and headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body) == {
        "available": True,
        "tag": run.KIT["tag"],
        "commit": run.KIT["commit"],
    }
    assert get(port, "/", token=None, host="localhost")[0] == 421
    assert get(port, "/v1/tasks", host="example.test")[0] == 421
    assert get(port, "/page.js", body={})[0] == 404


def test_the_page_does_not_need_the_kit(tmp_path: Path) -> None:
    """Without a kit folder, the server says so and gives no kit file. The page then draws
    plain controls, and the API is the same."""
    root = tmp_path / "store"
    run.fixture_store(root)
    api_httpd, page_httpd, _ = run.start(root, None, "ana", TOKEN)
    port = page_httpd.server_port
    try:
        assert json.loads(get(port, "/kit.json", token=None)[2])["available"] is False
        assert get(port, "/kit/src/kit.js", token=None)[0] == 404
        assert get(port, "/page.js", token=None)[0] == 200
        assert len(json.loads(get(port, "/v1/tasks")[2])["tasks"]) == 2
    finally:
        for httpd in (api_httpd, page_httpd):
            httpd.shutdown()
            httpd.server_close()


def test_the_page_server_sends_each_api_request_as_it_is(page: tuple[Path, str, int]) -> None:
    """The API does each check. The page server adds no claim and changes no answer."""
    _, _, port = page
    status, headers, body = get(port, "/v1/tasks", token=None)
    assert status == 401 and json.loads(body)["error"]["code"] == "no_claim"
    assert headers["WWW-Authenticate"] == "Bearer"
    status, _, body = get(port, "/v1/tasks", token="x" * 40)
    assert status == 401 and json.loads(body)["error"]["code"] == "bad_claim"
    assert json.loads(get(port, "/v1/nothing")[2])["error"]["code"] == "not_found"
    assert json.loads(get(port, "/v1/tasks", body={})[2])["error"]["code"] == "method_not_allowed"
    assert (
        json.loads(get(port, "/v1/answers", body={"task": 1})[2])["error"]["code"] == "bad_request"
    )


def test_the_page_names_the_api_version_and_the_pinned_kit() -> None:
    kit = json.loads((EXAMPLE / "kit.json").read_text("utf-8"))
    assert set(kit) == {"repository", "tag", "commit", "serve"}
    assert re.fullmatch(r"v\d+\.\d+\.\d+", kit["tag"]) and re.fullmatch(
        r"[0-9a-f]{40}", kit["commit"]
    )
    assert kit["repository"].startswith("https://") and kit["serve"] == ["src", "catalog"]
    readme = (EXAMPLE / "README.md").read_text("utf-8")
    script = (EXAMPLE / "page" / "page.js").read_text("utf-8")
    assert f"`{api.API}`" in readme and f"const API = '{api.API}';" in script
    assert kit["tag"] in readme and kit["commit"] in readme
    assert "uv run python examples/review-page/run.py" in readme
    # the page loads no script and no style from another origin, and it has no inline script
    html = (EXAMPLE / "page" / "index.html").read_text("utf-8")
    assert re.findall(r'(?:src|href)="([^"]*)"', html) == ["/page.css", "/page.js"]
    # the page loads the kit only from the page server
    assert set(re.findall(r"'(/kit/[^']*)'", script)) == {
        "/kit/src/tokens/tokens.css",
        "/kit/src/styles/page.css",
        "/kit/src/components/index.js",
        "/kit/src/kit.js",
    }
    assert "http" not in script.replace("groundgate", "") and "innerHTML" not in script
    assert not (EXAMPLE / ".kit").exists() or ".kit/" in (EXAMPLE / ".gitignore").read_text("utf-8")
    # the kit is not a part of the core
    src = Path(__file__).parent.parent / "src"
    assert not any(kit["commit"] in p.read_text("utf-8") for p in src.rglob("*.py"))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_fetch_kit_gets_the_pinned_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A local repository stands in for the kit, so the test needs no network."""
    origin = tmp_path / "origin"
    (origin / "src").mkdir(parents=True)

    def git(*args: str) -> str:
        done = subprocess.run(
            ["git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@example.test",
             "-c", "commit.gpgsign=false", *args],
            capture_output=True, text=True, timeout=60, check=True,
        )  # fmt: skip
        return done.stdout.strip()

    git("init", "--quiet")
    commits = []
    for text in ("one", "two"):
        (origin / "src" / "kit.js").write_text(text, "utf-8")
        git("add", "-A")
        git("commit", "--quiet", "--no-verify", "-m", text)
        commits.append(git("rev-parse", "HEAD"))
    pin = {**run.KIT, "repository": str(origin), "commit": commits[0]}
    monkeypatch.setattr(run, "KIT", pin)
    folder = tmp_path / "kit"
    assert run.kit_commit(folder) is None
    assert run.fetch_kit(folder) == folder and run.kit_commit(folder) == commits[0]
    assert (folder / "src" / "kit.js").read_text("utf-8") == "one"
    # a changed file of the kit is not the pin: fetch_kit puts the pinned file back
    (folder / "src" / "kit.js").write_text("changed", "utf-8")
    assert run.kit_commit(folder) is None
    run.fetch_kit(folder)
    assert (folder / "src" / "kit.js").read_text("utf-8") == "one"
    # a commit that the repository does not have
    monkeypatch.setattr(run, "KIT", {**pin, "commit": "0" * 40})
    with pytest.raises(RuntimeError, match="git fetch failed"):
        run.fetch_kit(tmp_path / "other")
    # without the kit, the page draws plain controls: find_kit gives None and says why
    assert run.find_kit(tmp_path / "third") is None and run.find_kit(None) is None
    assert "The UI kit is not available: git fetch failed" in capsys.readouterr().err


def test_main_refuses_a_store_folder_that_is_not_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run.main(["--no-kit", "--store", str(tmp_path / "none")]) == 2
    assert "the store folder is not there" in capsys.readouterr().err
