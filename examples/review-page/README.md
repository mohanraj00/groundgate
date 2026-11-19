# The review and audit page

A page for the review tasks and the audit tasks of a store. It reads and writes only through the
review API of `groundgate review api` ([SPEC §4.20](../../SPEC.md)). It imports nothing from
groundgate in the browser, and it reads no file of the store.

The page needs the API version `groundgate-review/1`. It refuses a response of another version.

## Run it

From a clean checkout:

```bash
uv run python examples/review-page/run.py
```

The command does four steps:

1. It gets the UI kit at the pinned commit into `examples/review-page/.kit/`. This step needs
   `git` and the network one time. If git cannot get the kit, the command says so, and the page
   draws plain controls.
2. It makes a store with one made-up invoice in a temporary folder. The invoice gives one review
   task and one audit task.
3. It starts the review API with a static token, and the page server. Each one binds to
   `127.0.0.1` only.
4. It prints the start URL. The URL has the token after `#`, so the browser does not send the
   token in a request line.

Open the URL in a browser. Press Ctrl-C in the terminal to stop the two servers.

The page does not need the kit. This command gets no kit and needs no network:

```bash
uv run python examples/review-page/run.py --no-kit
```

For your own store, make the tasks first, then give the store folder:

```bash
groundgate review tasks --store work/store sha256:3e0c27fa...
uv run python examples/review-page/run.py --store work/store --reviewer ana
```

## What the page does

- **The list.** A table of the open tasks of the reviewer, with one button for each task.
- **A review task.** The page shows the question, each value, and the passage of the document
  for each value whose evidence is in the document. Press the button of the right value. If no value is right, select the right
  text in the document and press "The selected text is the value".
- **An audit task.** An audit task is blind. The API gives no proposed value, so the page shows
  none. Find the value in the document, select it with its scale word, and press "The selected
  text is the value". If the document does not have the value, press "The value is not in the
  document".
- **A flagged correction.** The gate checks each correction. If it flags the value, the page
  shows the codes and a "Keep the value" button. Press it only if the value is right.
- **One answer at a time.** From the start of an answer to its response, the page opens no
  other task and sends no second answer. So a response always belongs to the task on the page.

An answer goes through `POST /v1/answers`, so the store gets the same record as from
`groundgate review serve`. After an answer, the page reads the list again.

## The UI kit

With the kit, the kit draws the table, the buttons, the texts and the states. Without it, the
page draws the same parts as plain HTML. In each mode, the page draws the document and the
evidence passages itself, as text, and it sends the same answers. A line at the end of the page
says which mode it is in.

The kit is not a part of groundgate, and the core does not import it. [kit.json](kit.json) pins
it by a released tag and by the commit of that tag:

- tag `v0.4.0`
- commit `715ce6b8db044d9acebc2a35f6a64e48582152ea`

`run.py` gets the kit with `git fetch` by the commit, not by the tag. Git names a commit by a
hash of its content, so a moved tag cannot change the files. To use a later release, change the
tag and the commit in `kit.json` together.

## The files

| File | What it is |
|---|---|
| `run.py` | The one command: the kit, the store, the API and the page server. |
| `kit.json` | The pin of the kit, and the folders of the kit that the page server gives. |
| `page/index.html`, `page/page.css` | The frame of the page. It has no inline script. |
| `page/page.js` | The page: the calls to the API, the actions of the buttons, and the two sets of controls. |

The page server gives the page, the two folders of the kit, and the API below `/v1/` on one
origin. It sends each `/v1/` request to the API as it is. The API does each check.

## The tests

- `tests/test_review_page.py` sends the calls of the page through the page server: one answer
  to a review task and one to an audit task. It needs no browser and no network.
- `tests/test_review_page_kit_seam.py` loads the page in a headless browser with the pinned
  kit, and answers the two tasks with the buttons of the kit. A second test does the same steps
  without the kit, and a third test checks a value that cites a reference text. A fourth test
  uses the kit and checks two long values that differ only in their last character: the page
  shows each one in full. On a developer machine, each test skips if no browser with a remote
  debugging pipe is installed, and a test with the kit skips if git cannot get the kit. In CI,
  each of these is a failure.

## Limits

- The page does not answer a model text task. Use `groundgate review serve` for it.
- The page shows the text of the document. It shows no PDF page and no crop of a scan.
- The page is for one person on one machine. The static token gives one reviewer name.
- A task ID is good only while the API runs. After a new start, load the page again.
- The page shows a passage only for evidence in the text of the document. A candidate can cite
  a reference text of the packet, and the API does not give that text (#702). Each choice of a
  task names its source. For a choice with a source that is not `document`, the page says that
  it cannot show the passage.
