"""The seam between the review page and the UI kit (#647): the page of examples/review-page
loads in a browser with the kit at the pinned commit, and a press on a button of the kit sends
an answer through the review API. A second test does the same steps without the kit.

The seam test needs a browser with a remote debugging pipe, git and the network. On a developer
machine, it skips without one of them. In CI, it fails, so a run cannot pass without this test.
Set REVIEW_PAGE_BROWSER to the path of the browser, and REVIEW_PAGE_KIT to
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
  press('.choice[data-choice="2"] [data-tool]');
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


def not_available(why: str) -> None:
    """Skip the test on a developer machine. In CI, fail: a CI run must do each browser test."""
    if os.environ.get("CI") and sys.platform != "win32":
        pytest.fail(why)
    pytest.skip(why)


@pytest.fixture(scope="module")
def pinned_kit(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("git") is None:
        not_available("git is not installed")
    kept = os.environ.get("REVIEW_PAGE_KIT")
    folder = Path(kept) if kept else tmp_path_factory.mktemp("kit")
    try:
        return run.fetch_kit(folder)
    except RuntimeError as exc:
        not_available(f"the pinned kit is not available: {exc}")
        raise


@pytest.fixture
def browser(tmp_path: Path) -> Iterator[Browser]:
    binary = browser_path()
    if sys.platform == "win32" or binary is None:
        not_available("no browser with a remote debugging pipe is installed")
        raise AssertionError
    started = Browser(binary, tmp_path / "profile")
    try:
        yield started
    finally:
        started.close()


def drive(browser: Browser, root: Path, kit: Path | None, steps: str) -> dict[str, Any]:
    """Start the API and the page on the store in ``root``, load the page in the browser, and
    do ``steps`` on it. The result is the object that the steps give."""
    api_httpd, page_httpd, url = run.start(root, kit, "ana", TOKEN)
    try:
        target = browser.send("Target.createTarget", {"url": url})["targetId"]
        attached = browser.send("Target.attachToTarget", {"targetId": target, "flatten": True})
        session = attached["sessionId"]
        # The new target starts with an empty document. Wait for the document of the page.
        loaded = f"location.href.startsWith({json.dumps(url.split('#')[0])}) && !!document.body"
        end = time.monotonic() + SECONDS
        while True:
            params = {"expression": loaded, "returnByValue": True}
            if browser.send("Runtime.evaluate", params, session)["result"].get("value") is True:
                break
            assert time.monotonic() < end, "the browser did not load the page"
            time.sleep(0.05)
        params = {"expression": steps, "awaitPromise": True, "returnByValue": True}
        result = browser.send("Runtime.evaluate", params, session)
    finally:
        for httpd in (api_httpd, page_httpd):
            httpd.shutdown()
            httpd.server_close()
    assert "exceptionDetails" not in result, result["exceptionDetails"]
    out: dict[str, Any] = json.loads(result["result"]["value"])
    return out


def answer_two_tasks(browser: Browser, tmp_path: Path, kit: Path | None) -> dict[str, Any]:
    """Load the page, do the steps, and check what each mode of the page must do: the texts of
    the page, the blind audit task, and the two answers in the store."""
    root = tmp_path / "store"
    packets = run.fixture_store(root)
    out = drive(browser, root, kit, STEPS)
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
        written = [r for p in packets for r in store.read(("answers", p, reviewer_key("ana")))]
        keys, _ = store.object_keys()
        objects = [store.object_bytes(k) for k in keys]
    (review,) = [json.loads(b) for b in objects if b'"mode":"review"' in b.replace(b" ", b"")]
    chosen = next(c["decision"] for c in review["choices"] if c["value"] == "4200000")
    assert [(r["verdict"], r["decision"]) for r in written] == [
        ("choose", chosen),
        ("correct", None),
    ]
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


CLOSED_SET_STEPS = """
(async () => {
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  const until = async (test) => {
    for (let i = 0; i < 300 && !test(); i += 1) await wait(50);
  };
  await until(() => document.body.dataset.state === 'ready');
  const control = document.querySelector('li[data-field=status]').firstElementChild;
  (control.shadowRoot?.querySelector('button') ?? control).click();
  await until(() => document.querySelectorAll('.choice').length === 2);
  return JSON.stringify({
    kit: document.body.dataset.kit,
    options: [...document.querySelectorAll('#detail .options li')].map((item) => item.textContent),
  });
})()
"""


@pytest.mark.parametrize("with_kit", [False, True], ids=["without-kit", "with-kit"])
def test_the_page_shows_all_closed_set_options(
    tmp_path: Path, browser: Browser, request: pytest.FixtureRequest, with_kit: bool
) -> None:
    from groundgate.review.tasks import write_tasks
    from groundgate.store.packets import admit_packet

    long_option = "approved with conditions " + "A" * 12000 + "Z"
    options = ["approved\u0085in full", long_option, "rejected"]
    schema = {"fields": {"status": {"type": "string", "options": options}}}
    candidates = [
        {
            "id": "c1",
            "field": "status",
            "value": "approved in full",
            "evidence": [{"text": "approved in full"}],
        },
        {"id": "c2", "field": "status", "value": "rejected", "evidence": [{"text": "rejected"}]},
    ]
    document = "Status: approved in full. Previous status: rejected.\n"
    root = tmp_path / "store"
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, document, schema, candidates, None, "policy-0001")
        ((_, task),) = write_tasks(store, packet, run.REVIEW_POLICY).tasks
    assert task["item"] == "closed_set" and len(task["choices"]) == 2

    kit = request.getfixturevalue("pinned_kit") if with_kit else None
    out = drive(browser, root, kit, CLOSED_SET_STEPS)
    assert out["kit"] == ("true" if with_kit else "false")
    assert out["options"] == [
        "approved\u0085in full (proposed)",
        long_option,
        "rejected (proposed)",
    ]


# A review task with two values that cite a reference text of the packet, and one value that
# cites the document.
REFERENCE_STEPS = """
(async () => {
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  const until = async (test) => {
    for (let i = 0; i < 300 && !test(); i += 1) await wait(50);
  };
  await until(() => document.body.dataset.state === 'ready');
  document.querySelector('li[data-field=limit]').firstElementChild.click();
  await until(() => document.querySelectorAll('.choice').length === 3);
  const choices = [...document.querySelectorAll('.choice')];
  return JSON.stringify({
    state: document.body.dataset.state,
    choices: choices.map((choice) => ({
      text: choice.textContent,
      marks: [...choice.querySelectorAll('mark')].map((mark) => mark.textContent),
    })),
    document: document.getElementById('document').textContent,
  });
})()
"""


def test_the_page_shows_no_passage_for_evidence_in_a_reference(
    tmp_path: Path, browser: Browser
) -> None:
    """The span of a value that cites a reference is in the text of the reference. The API gives
    the text of the document only, so the same offsets there are other text. The page must not
    show that text as the evidence. One reference value has the offsets of the document value,
    so only the source of each choice tells them apart."""
    from groundgate.review.tasks import write_tasks
    from groundgate.store.packets import admit_packet

    text = "Limit: $9,000 in the unrelated main document.\n"
    reference = "Limit: $7,000 or $8,000."
    assert text.index("$9,000") == reference.index("$7,000")

    def cite(words: str) -> dict[str, Any]:
        start = reference.index(words)
        return {"source": "reference", "ref": "r", "start": start, "end": start + len(words),
                "text": words}  # fmt: skip

    candidates = [
        {
            "id": "c1",
            "field": "limit",
            "value": "7000",
            "unit": "USD",
            "evidence": [cite("$7,000")],
        },
        {
            "id": "c2",
            "field": "limit",
            "value": "8000",
            "unit": "USD",
            "evidence": [cite("$8,000")],
        },
        {
            "id": "c3",
            "field": "limit",
            "value": "9000",
            "unit": "USD",
            "evidence": [{"start": 7, "end": 13, "text": "$9,000"}],
        },
    ]
    schema = {"fields": {"limit": {"type": "number", "unit": "USD"}}}
    root = tmp_path / "store"
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, text, schema, candidates, None, "policy-0001",
                                 references=[{"id": "r", "text": reference}])  # fmt: skip
        tasks = [task for _, task in write_tasks(store, packet, run.REVIEW_POLICY).tasks]
    assert [(t["mode"], len(t["choices"])) for t in tasks] == [("review", 3)]
    spans = {c["value"]: c["evidence"] for c in tasks[0]["choices"]}
    assert spans["7000"] == spans["9000"] == {"start": 7, "end": 13}
    out = drive(browser, root, None, REFERENCE_STEPS)
    assert out["state"] == "ready" and out["document"] == text
    shown = {
        value: next(c for c in out["choices"] if words in c["text"])
        for value, words in (("7000", "7,000"), ("8000", "8,000"), ("9000", "9,000 USD"))
    }
    assert len({id(c) for c in shown.values()}) == 3
    # the document value has its passage
    assert shown["9000"]["marks"] == ["$9,000"]
    assert "cannot show the passage" not in shown["9000"]["text"]
    for value in ("7000", "8000"):
        choice = shown[value]
        assert choice["marks"] == [] and "cannot show the passage" in choice["text"]
        # a passage has the text around the span too: no part of the document text is there
        assert "unrelated" not in choice["text"] and "$9,000" not in choice["text"]


# A review task with two long values that differ only in their last character.
LONG_STEPS = """
(async () => {
  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  const until = async (test) => {
    for (let i = 0; i < 300 && !test(); i += 1) await wait(50);
  };
  const textOf = (node) => node.shadowRoot?.textContent ?? node.textContent;
  const press = (parent) => {
    const control = parent.firstElementChild;
    (control.shadowRoot?.querySelector('button') ?? control).click();
  };
  await until(() => document.body.dataset.state === 'ready');
  press(document.querySelector('li[data-field=name]'));
  await until(() => document.querySelectorAll('.choice').length === 2);
  const choices = [...document.querySelectorAll('.choice')];
  const labels = choices.map((choice) => textOf(choice.firstElementChild));
  const heading = document.querySelector('#detail h2').textContent;
  // choose the value that ends with Y
  press(choices[labels.findIndex((label) => label.includes('AY"'))].querySelector('[data-tool]'));
  await until(() => document.getElementById('who').textContent.includes('Open tasks: 0.'));
  return JSON.stringify({
    kit: document.body.dataset.kit,
    labels,
    heading,
    who: document.getElementById('who').textContent,
  });
})()
"""


def test_the_page_shows_a_long_value_in_full(
    tmp_path: Path, pinned_kit: Path, browser: Browser
) -> None:
    """The text element of the kit takes 10,000 characters. Two values of 12,001 characters
    differ only in their last character, and their evidence is in a reference, so the page
    shows no passage. The page must show each value in full: a clipped label gives the same
    text for the two choices."""
    from groundgate.review.tasks import write_tasks
    from groundgate.store.packets import admit_packet

    long = "A" * 12000
    reference = f"Name: {long}X. Name: {long}Y."

    def cite(words: str) -> dict[str, Any]:
        start = reference.index(words)
        return {"source": "reference", "ref": "r", "start": start, "end": start + len(words),
                "text": words}  # fmt: skip

    candidates = [
        {"id": "c1", "field": "name", "value": long + "X", "evidence": [cite(long + "X")]},
        {"id": "c2", "field": "name", "value": long + "Y", "evidence": [cite(long + "Y")]},
    ]
    document = "A document with a long key.\n"
    schema = {"fields": {"name": {"type": "string"}}}
    root = tmp_path / "store"
    with FolderStore(root) as store:
        packet, _ = admit_packet(store, document, schema, candidates, None, "policy-0001",
                                 references=[{"id": "r", "text": reference}])  # fmt: skip
        ((_, task),) = write_tasks(store, packet, run.REVIEW_POLICY).tasks
    shown = [choice["shown"] for choice in task["choices"]]
    assert all(len(text) > 20000 for text in shown) and shown[0][:10000] == shown[1][:10000]
    out = drive(browser, root, pinned_kit, LONG_STEPS)
    assert out["kit"] == "true" and "Open tasks: 0." in out["who"]
    assert out["labels"][0] != out["labels"][1]
    assert sorted(label.split(": ", 1)[1] for label in out["labels"]) == sorted(shown)
    assert out["heading"] == "Task 1: name in policy-0001"
    # the store has the choice of the value that ends with Y
    with FolderStore(root) as store:
        (written,) = store.read(("answers", packet, reviewer_key("ana")))
    chosen = next(c for c in task["choices"] if c["decision"] == written["decision"])
    assert written["verdict"] == "choose" and chosen["value"] == long + "Y"
