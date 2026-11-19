"""The seam between the review page and the UI kit (#647): the page of examples/review-page
loads in a browser with the kit at the pinned commit, and a press on a button of the kit sends
an answer through the review API. A second test does the same steps without the kit.

The seam test needs a browser with a remote debugging pipe, git and the network, and it skips
without one of them. Set REVIEW_PAGE_BROWSER to the path of the browser, and REVIEW_PAGE_KIT to
a folder that keeps the kit checkout between runs.
tests/test_review_page.py has the tests that need no browser."""

from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_review_page import TOKEN, run

from groundgate.store import FolderStore, reviewer_key

MAC_BROWSER = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SECONDS = 60


def browser_path() -> str | None:
    names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    found = [os.environ.get("REVIEW_PAGE_BROWSER"), *(shutil.which(n) for n in names), MAC_BROWSER]
    return next((p for p in found if p and Path(p).is_file()), None)


class Browser:
    """A headless browser with its remote debugging pipe: the browser reads a message on its
    file descriptor 3 and writes on 4. A message is JSON with a zero byte after it. A pipe needs
    no port and no WebSocket, so the standard library is enough."""

    def __init__(self, binary: str, profile: Path) -> None:
        import fcntl  # not on Windows: the fixture skips there

        to_read, self._to = os.pipe()
        self._from, from_write = os.pipe()
        # Move the two ends for the browser away from 3 and 4, then put them there in the child.
        ours = [fcntl.fcntl(fd, fcntl.F_DUPFD, 10) for fd in (to_read, from_write)]
        for fd in (to_read, from_write):
            os.close(fd)

        def wire() -> None:
            os.dup2(ours[0], 3)
            os.dup2(ours[1], 4)

        args = [binary, "--headless=new", "--remote-debugging-pipe", "--no-first-run",
                "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
                f"--user-data-dir={profile}", "about:blank"]  # fmt: skip
        if os.environ.get("CI") and sys.platform == "linux":
            args.insert(1, "--no-sandbox")  # a CI runner gives the browser no user namespace
        self._process = subprocess.Popen(
            args, preexec_fn=wire, pass_fds=(3, 4), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        for fd in ours:
            os.close(fd)
        self._buffer = b""
        self._id = 0

    def send(self, method: str, params: dict[str, Any], session: str | None = None) -> Any:
        """Send one command and wait for its result."""
        self._id += 1
        message = {"id": self._id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        os.write(self._to, json.dumps(message).encode("utf-8") + b"\0")
        end = time.monotonic() + SECONDS
        while True:
            while b"\0" not in self._buffer:
                ready, _, _ = select.select([self._from], [], [], max(0.0, end - time.monotonic()))
                data = os.read(self._from, 65536) if ready else b""
                if not data:
                    raise RuntimeError(f"the browser gave no answer to {method}")
                self._buffer += data
            raw, _, self._buffer = self._buffer.partition(b"\0")
            answer = json.loads(raw)
            if answer.get("id") == self._id:
                if "error" in answer:
                    raise RuntimeError(f"{method}: {answer['error']}")
                return answer["result"]

    def close(self) -> None:
        self._process.kill()
        self._process.wait(timeout=10)
        os.close(self._to)
        os.close(self._from)


# The steps of a person on the page. With the kit, each control is an element of the kit, and
# its button is in its shadow root. Without it, each control is a plain button.
STEPS = """
(async () => {
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  const $ = (id) => document.getElementById(id);
  const until = async (test, what) => {
    for (let i = 0; i < 300; i += 1) {
      if (test()) return;
      await wait(50);
    }
    throw new Error(`the page did not get to: ${what}, state ${document.body.dataset.state}, `
      + `${$('result').dataset.code ?? 'no error code'}, ${$('result').textContent}`);
  };
  const textOf = (node) => node.shadowRoot?.textContent ?? node.textContent;
  const press = (selector) => {
    const control = document.querySelector(selector).firstElementChild;
    (control.shadowRoot?.querySelector('button') ?? control).click();
  };
  const select = async (words) => {
    const node = $('document').firstChild;
    const range = document.createRange();
    range.setStart(node, node.data.indexOf(words));
    range.setEnd(node, node.data.indexOf(words) + words.length);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    await until(() => $('selection').textContent === `Selected: ${words}`, 'selection');
  };
  const who = () => $('who').textContent;
  const out = { defined: [] };

  await until(() => ['ready', 'error'].includes(document.body.dataset.state), 'loaded');
  await until(() => document.body.dataset.state === 'ready', 'ready');
  for (const name of ['mu-table', 'mu-button', 'mu-action-button', 'mu-status', 'mu-text']) {
    if (customElements.get(name)) out.defined.push(name);
  }
  out.kit = document.body.dataset.kit;
  out.note = $('kit').textContent;
  const controls = [...document.querySelectorAll('#queue li > *')].map((node) => node.localName);
  out.controls = [...new Set(controls)];
  out.start = who();
  out.table = textOf($('queue').firstElementChild);

  // an answer that is on its way keeps its task on the page: the page opens no other task
  // before the response, so the response and its "Keep the value" button belong to that task
  press('li[data-mode=audit]');
  await until(() => $('detail').dataset.mode === 'audit' && $('document'), 'audit task');
  await select('310');
  const real = window.fetch;
  let release;
  const held = new Promise((done) => { release = done; });
  window.fetch = async (...args) => {
    const response = await real(...args);
    if (String(args[0]).startsWith('/v1/answers')) await held;
    return response;
  };
  press('[data-tool="answer.correct"]');
  await wait(300);
  press('li[data-field=total]');
  await wait(300);
  out.held = [$('detail').dataset.mode, textOf($('result').firstElementChild)];
  window.fetch = real;
  release();
  await until(() => $('result').dataset.code === 'codes_not_kept', 'flagged after the wait');
  const keep = '[data-tool="answer.keep"]';
  out.after = [$('detail').dataset.mode, document.querySelectorAll(keep).length];

  // the review task: choose the second value
  press('li[data-field=total]');
  const choose = '[data-tool="answer.choose"]';
  await until(() => document.querySelectorAll(choose).length === 2, 'review task');
  out.marks = [...document.querySelectorAll('#detail mark')].map((mark) => mark.textContent);
  press('.choice[data-decision="2"] [data-tool]');
  await until(() => who().includes('Open tasks: 1.'), 'one open task');

  // the audit task: a correction that the gate flags, then the full value
  press('li[data-mode=audit]');
  await until(() => $('detail').dataset.mode === 'audit' && $('document'), 'audit task');
  const inside = (node) => node.shadowRoot?.textContent ?? '';
  const parts = [...document.querySelectorAll('#detail *')].map(inside);
  out.audit = $('detail').textContent + parts.join(' ');
  out.choices = document.querySelectorAll('.choice, #detail mark').length;
  await select('310');
  press('[data-tool="answer.correct"]');
  await until(() => $('result').dataset.code === 'codes_not_kept', 'flagged');
  out.flagged = textOf($('result').firstElementChild);
  out.keep = document.querySelectorAll('[data-tool="answer.keep"]').length;
  await select('310 thousand');
  press('[data-tool="answer.correct"]');
  await until(() => who().includes('Open tasks: 0.'), 'no open task');
  out.end = textOf($('result').firstElementChild);
  return JSON.stringify(out);
})()
"""


@pytest.fixture(scope="module")
def pinned_kit(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    kept = os.environ.get("REVIEW_PAGE_KIT")
    folder = Path(kept) if kept else tmp_path_factory.mktemp("kit")
    try:
        return run.fetch_kit(folder)
    except RuntimeError as exc:
        pytest.skip(f"the pinned kit is not available: {exc}")


@pytest.fixture
def browser(tmp_path: Path) -> Iterator[Browser]:
    binary = browser_path()
    if sys.platform == "win32" or binary is None:
        pytest.skip("no browser with a remote debugging pipe is installed")
    started = Browser(binary, tmp_path / "profile")
    try:
        yield started
    finally:
        started.close()


def answer_two_tasks(browser: Browser, tmp_path: Path, kit: Path | None) -> dict[str, Any]:
    """Load the page, do the steps, and check what each mode of the page must do: the texts of
    the page, the blind audit task, and the two answers in the store."""
    root = tmp_path / "store"
    packet = run.fixture_store(root)
    api_httpd, page_httpd, url = run.start(root, kit, "ana", TOKEN)
    try:
        target = browser.send("Target.createTarget", {"url": url})["targetId"]
        attached = browser.send("Target.attachToTarget", {"targetId": target, "flatten": True})
        params = {"expression": STEPS, "awaitPromise": True, "returnByValue": True}
        result = browser.send("Runtime.evaluate", params, attached["sessionId"])
    finally:
        for httpd in (api_httpd, page_httpd):
            httpd.shutdown()
            httpd.server_close()
    assert "exceptionDetails" not in result, result["exceptionDetails"]
    out: dict[str, Any] = json.loads(result["result"]["value"])
    assert out["start"] == "Reviewer: ana. Open tasks: 2."
    assert "invoice-0007" in out["table"] and "audit" in out["table"]
    # the page did not open the review task while the audit answer was on its way
    assert out["held"][0] == "audit" and "waits for the response" in out["held"][1]
    assert out["after"] == ["audit", 1]
    assert out["marks"] == ["4,200 thousand", "4,200 thousand"]
    # the audit task shows no proposed value: no choice, no passage, no value in a text
    assert out["choices"] == 0 and "does not show a proposed value" in out["audit"]
    for word in ("310,000", "310000", "Is tax"):
        assert word not in out["audit"], word
    assert "SCALE_WORD" in out["flagged"] and out["keep"] == 1
    assert "The answer is in the store." in out["end"]
    # the store has the two answers of the buttons
    with FolderStore(root) as store:
        written = store.read(("answers", packet, reviewer_key("ana")))
    assert [(r["verdict"], r["decision"]) for r in written] == [("choose", 2), ("correct", None)]
    assert written[1]["candidate"]["value"] == "310000"
    return out


def test_the_page_answers_a_task_with_the_pinned_kit(
    tmp_path: Path, pinned_kit: Path, browser: Browser
) -> None:
    """The seam test: the kit at the pin defines each element that the page mounts, and a press
    on a button of the kit sends the answer through the API."""
    assert run.kit_commit(pinned_kit) == run.KIT["commit"]
    out = answer_two_tasks(browser, tmp_path, pinned_kit)
    assert out["defined"] == ["mu-table", "mu-button", "mu-action-button", "mu-status", "mu-text"]
    assert out["kit"] == "true" and run.KIT["tag"] in out["note"]
    assert out["controls"] == ["mu-button"]


def test_the_page_answers_a_task_without_the_kit(tmp_path: Path, browser: Browser) -> None:
    out = answer_two_tasks(browser, tmp_path, None)
    assert out["defined"] == [] and out["kit"] == "false"
    assert out["controls"] == ["button"] and "plain controls" in out["note"]
