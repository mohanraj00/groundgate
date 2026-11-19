// The review and audit page. It reads and writes only through the review API groundgate-review/1
// (SPEC §4.20). With the UI kit, the kit draws the table, the buttons, the texts and the states.
// Without it, the page draws plain HTML controls. The page draws the document and each evidence
// passage itself, as text.
const API = 'groundgate-review/1';
const MAX_ROWS = 500; // the largest table of the kit
const CONTEXT = 80; // the bytes of the document on each side of an evidence passage
const KIT_STYLES = ['/kit/src/tokens/tokens.css', '/kit/src/styles/page.css'];
const STATES = { pending: 'Pending', passed: 'Passed', failed: 'Failed', unknown: 'Unknown' };
const token = location.hash.slice(1);
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const $ = (id) => document.getElementById(id);

// The open task: its ID, the bytes of its document, the selected span, and an answer that the
// API refused and that the person can send again.
let current = null;
// True from the start of an answer request to its response. In that time, the page opens no
// task and sends no second answer, so a response always belongs to the task on the page.
let busy = false;
const WAIT = 'The page waits for the response to your answer.';
const NO_PASSAGE = 'The page cannot show the passage of this value. Its evidence is not in the text of the '
  + 'document. It can be in a reference text, and the API gives the text of the document only.';

// The page clips a message and a cell of the list. It never clips a text that tells one value
// or one task from another: a choice, a question, a definition, and the heading of a task.
const clip = (text, max) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
// The text element of the kit takes this many characters at most.
const KIT_TEXT = 10000;

function add(parent, tag, text = '', attributes = {}) {
  const node = document.createElement(tag);
  node.textContent = text;
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
  parent.append(node);
  return node;
}

// The parts of the page without the kit: plain HTML. An action button shows its receipt as text.
const plain = {
  text: (parent, text, variant = 'body') => add(parent, 'p', text, { class: variant }),
  status: (parent, state, text) => add(parent, 'p', `${STATES[state]}: ${text}`, { class: 'status', role: 'status' }),
  table(parent, label, columns, rows) {
    const table = add(parent, 'table');
    add(table, 'caption', label);
    const head = add(add(table, 'thead'), 'tr');
    for (const column of [...columns, 'Status']) add(head, 'th', column, { scope: 'col' });
    const body = add(table, 'tbody');
    for (const row of rows) {
      const line = add(body, 'tr');
      for (const cell of [...row.cells, row.status ?? '']) add(line, 'td', cell);
    }
  },
  button: (parent, label, press) => add(parent, 'button', label, { type: 'button' }).addEventListener('click', press),
  action(parent, tool, label, args) {
    const button = add(parent, 'button', label, { type: 'button' });
    const note = add(parent, 'span', '', { role: 'status' });
    button.addEventListener('click', async () => {
      button.disabled = true;
      const receipt = await Promise.resolve().then(() => answer(tool, args))
        .catch(() => ({ ok: false, message: 'The request failed.' }));
      button.disabled = false;
      note.textContent = `${receipt.ok ? 'Done' : 'Not done'}: ${receipt.message}`;
    });
  },
};

// The same parts with the kit: each one is an element of the kit.
function kitParts(kit) {
  return {
    // A longer text goes into a plain element, in full. Two values can differ only after the
    // limit, and a clipped text shows them as the same value.
    text: (parent, text, variant = 'body') => (text.length > KIT_TEXT
      ? plain.text(parent, text, variant)
      : kit.mount('text', { text, variant }, { parent })),
    status: (parent, state, text) => kit.mount('status', { state, text: clip(text, 200) }, { parent }),
    table: (parent, label, columns, rows) => kit.mount('table', {
      label,
      columns,
      rows: rows.map(({ cells, status }) => kit.fill('table-row', {
        cells: cells.map((cell) => clip(cell, 500)),
        ...(status ? { status } : {}),
      })),
      status_values: ['review', 'audit'],
    }, { parent }),
    button: (parent, label, press) => kit.mount('button', { label, emphasis: 'secondary' }, { parent })
      .addEventListener('mu-press', press),
    action: (parent, tool, label, args) => kit.mount('action-button', { label },
      { parent, action: { tool, label, arguments: args } }),
  };
}

let parts = plain;

async function call(path, body) {
  const headers = { Authorization: `Bearer ${token}` };
  const init = { headers, cache: 'no-store' };
  if (body !== undefined) {
    headers['Content-Type'] = 'application/json';
    Object.assign(init, { method: 'POST', body: JSON.stringify(body) });
  }
  const response = await fetch(path, init);
  const data = await response.json().catch(() => null);
  if (data === null || data.api !== API) throw new Error(`The server does not speak ${API}.`);
  return { status: response.status, data };
}

async function read(path) {
  const { status, data } = await call(path);
  if (status !== 200) throw new Error(data.error.message);
  return data;
}

function show(state, text, parent = $('result')) {
  parent.replaceChildren();
  parent.dataset.state = state;
  delete parent.dataset.code; // the error code of the last answer, for a test
  parts.status(parent, state, text);
}

function action(parent, tool, label, more = {}) {
  const item = add(parent, 'li', '', { 'data-tool': tool });
  parts.action(item, tool, label, { task: current.id, ...more });
}

// The list of the open tasks: a table, and one button for each task.
async function loadQueue() {
  const tasks = [];
  let actor = '';
  let cursor = null;
  do {
    const page = await read(`/v1/tasks?limit=200${cursor ? `&cursor=${cursor}` : ''}`);
    tasks.push(...page.tasks);
    ({ actor, next: cursor } = page);
  } while (cursor && tasks.length < MAX_ROWS);
  const shown = tasks.slice(0, MAX_ROWS);
  const more = cursor || tasks.length > MAX_ROWS ? ` The page shows the first ${MAX_ROWS}.` : '';
  $('who').textContent = `Reviewer: ${actor}. Open tasks: ${shown.length}.${more}`;
  const queue = $('queue');
  queue.replaceChildren();
  if (shown.length === 0) {
    show('passed', 'No task is open.', queue);
    return;
  }
  const rows = shown.map((task, index) => ({
    cells: [String(index + 1), task.document, task.field, task.key ?? ''],
    status: ['review', 'audit'].includes(task.mode) ? task.mode : null,
  }));
  parts.table(queue, 'Open tasks', ['Task', 'Document', 'Field', 'Key'], rows);
  const picks = add(queue, 'ul', '', { class: 'picks' });
  shown.forEach((task, index) => {
    const item = add(picks, 'li', '', { 'data-field': task.field, 'data-mode': task.mode });
    parts.button(item, `Open task ${index + 1}`, () => open(task, index + 1).catch(fail));
  });
}

// The passage of a span of the document, with some text on each side. A span is in UTF-8 bytes.
function passage(parent, data, { start, end }) {
  let from = Math.max(0, start - CONTEXT);
  let to = Math.min(data.length, end + CONTEXT);
  while (from < start && (data[from] & 0xc0) === 0x80) from += 1; // not in the middle of a character
  while (to > end && to < data.length && (data[to] & 0xc0) === 0x80) to -= 1;
  const quote = add(parent, 'blockquote');
  quote.append(decoder.decode(data.subarray(from, start)));
  add(quote, 'mark', decoder.decode(data.subarray(start, end)));
  quote.append(decoder.decode(data.subarray(end, to)));
}

async function open(entry, number) {
  if (busy) {
    show('pending', WAIT);
    return;
  }
  const [task, source] = await Promise.all([read(`/v1/tasks/${entry.task}`), read(`/v1/tasks/${entry.task}/document`)]);
  if (busy) return; // an answer started while the page read the task: keep the task on the page
  const data = encoder.encode(source.text);
  current = { id: entry.task, data, span: null, again: null };
  $('result').replaceChildren();
  const detail = $('detail');
  detail.replaceChildren();
  detail.dataset.mode = task.mode;
  const key = task.key === null ? '' : ` (${task.key})`;
  add(detail, 'h2', `Task ${number}: ${task.field}${key} in ${task.document}`);
  if (task.definition) parts.text(detail, task.definition, 'caption');
  if (task.answered) parts.text(detail, `Your last answer: ${task.answered}.`, 'caption');
  if (task.statements !== null) {
    show('unknown', 'This page does not answer a model text task. Use groundgate review serve for it.', detail);
    current = null;
    return;
  }
  if (task.body === null) {
    // An audit task is blind: the API gives no value, and the page asks for one.
    parts.text(detail, `Audit: find the value of ${clip(task.field, 200)} in the document. The page does not `
      + 'show a proposed value. Select the value in the document, with its scale word.', 'strong');
  } else {
    parts.text(detail, task.body.question, 'strong');
    const choices = task.body.choices;
    // The evidence of a choice can be a span of a reference text, and the API gives the text of
    // the document only. Each choice names its source. So the page shows a passage only for the
    // source `document`: the same offsets in the document are other text for another source.
    choices.forEach((choice, index) => {
      const block = add(detail, 'div', '', { class: 'choice', 'data-choice': String(choice.choice) });
      parts.text(block, `Value ${index + 1}: ${choice.shown}`);
      if (choice.evidence && choice.source === 'document') passage(block, data, choice.evidence);
      else if (choice.evidence) parts.text(block, NO_PASSAGE, 'caption');
      const list = add(block, 'ul', '', { class: 'actions' });
      if (choices.length === 1) action(list, 'answer.confirm', 'Confirm this value');
      else action(list, 'answer.choose', `Choose value ${index + 1}`, { choice: choice.choice });
    });
  }
  add(detail, 'h3', 'Document');
  add(detail, 'pre', source.text, { id: 'document', tabindex: '0', 'aria-label': 'The text of the document' });
  add(detail, 'p', 'No text is selected.', { id: 'selection' });
  const answers = add(detail, 'ul', '', { class: 'actions' });
  action(answers, 'answer.correct', 'The selected text is the value');
  action(answers, 'answer.not_in_document', 'The value is not in the document');
  action(answers, 'answer.unsure', 'Unsure');
}

// The selection in the document, as a span in UTF-8 bytes. The page keeps the last selection,
// because a press on a button can move the selection.
document.addEventListener('selectionchange', () => {
  const pre = $('document');
  const selection = getSelection();
  if (!current || !pre || selection.rangeCount === 0 || selection.isCollapsed) return;
  const range = selection.getRangeAt(0);
  if (!pre.contains(range.startContainer) || !pre.contains(range.endContainer)) return;
  const before = document.createRange();
  before.selectNodeContents(pre);
  before.setEnd(range.startContainer, range.startOffset);
  const start = encoder.encode(before.toString()).length;
  const end = start + encoder.encode(range.toString()).length;
  if (end === start) return;
  current.span = { start, end };
  $('selection').textContent = `Selected: ${clip(decoder.decode(current.data.subarray(start, end)), 200)}`;
});

// Send one answer of the open task. The receipt of the button comes from the response of the
// API. ``own`` is the task that the answer belongs to: the response changes only that task, and
// only if it is the task on the page.
async function send(body) {
  const own = current;
  busy = true;
  let response;
  try {
    response = await call('/v1/answers', body);
  } finally {
    busy = false;
  }
  const { status, data } = response;
  if (status === 201) {
    if (current === own) current = null;
    // The receipt goes to the button first. Then the page reads the list again.
    setTimeout(() => {
      if (current === null) $('detail').replaceChildren();
      show('passed', 'The answer is in the store.');
      loadQueue().catch(fail);
    }, 0);
    return { ok: true, message: 'The answer is in the store.' };
  }
  const { code, message, codes } = data.error;
  if (current !== own) return { ok: false, message: clip(message, 200) };
  const result = $('result');
  if (code === 'codes_not_kept' || code === 'parts_disagree') {
    // The person saw the reason. A second press sends the same answer with the reason kept.
    own.again = code === 'codes_not_kept' ? { ...body, codes_kept: codes } : { ...body, parts_seen: true };
    const why = code === 'codes_not_kept' ? `The gate flags the value: ${codes.join(', ')}.` : message;
    show('failed', `${why} If the value is right, keep it. If not, select another text.`);
    action(add(result, 'ul', '', { class: 'actions' }), 'answer.keep', 'Keep the value');
  } else {
    own.again = null;
    show('failed', message);
  }
  result.dataset.code = code;
  return { ok: false, message: clip(message, 200) };
}

function answer(tool, args) {
  if (busy) return { ok: false, message: WAIT };
  if (!current || args.task !== current.id) return { ok: false, message: 'The task is not open now.' };
  const task = current.id;
  if (tool === 'answer.choose') return send({ task, verdict: 'choose', choice: args.choice });
  if (tool === 'answer.confirm') return send({ task, verdict: 'confirm' });
  if (tool === 'answer.not_in_document') return send({ task, verdict: 'not_in_document' });
  if (tool === 'answer.unsure') return send({ task, verdict: 'unsure' });
  if (tool === 'answer.keep' && current.again) return send(current.again);
  if (tool === 'answer.correct') {
    if (!current.span) return { ok: false, message: 'Select the value in the document first.' };
    return send({ task, verdict: 'correct', span: current.span });
  }
  return { ok: false, message: 'The page does not have this action.' };
}

function fail(error) {
  document.body.dataset.state = 'error';
  show('failed', error instanceof Error ? error.message : 'The request failed.');
}

// The page server says if it has the kit. With the kit, the page loads its styles and its
// elements from the page server, and the kit sends each action of a button to answer().
async function start() {
  const pin = await fetch('/kit.json', { cache: 'no-store' }).then((response) => response.json());
  if (pin.available) {
    for (const href of KIT_STYLES) {
      const link = document.createElement('link');
      Object.assign(link, { rel: 'stylesheet', href });
      document.head.insertBefore(link, document.head.querySelector('link'));
    }
    const [{ define }, { createKit, onAction }] = await Promise.all([
      import('/kit/src/components/index.js'), import('/kit/src/kit.js')]);
    define();
    parts = kitParts(createKit({ actor: { type: 'system', id: 'groundgate-review-page', name: 'The review page' } }));
    onAction(document.body, answer);
  }
  document.body.dataset.kit = String(pin.available);
  $('kit').textContent = pin.available
    ? `The UI kit ${pin.tag} draws the controls.`
    : 'The UI kit is not available. The page draws plain controls.';
  if (!token) throw new Error('The URL has no token. Open the URL that run.py prints.');
  await loadQueue();
  document.body.dataset.state = 'ready';
}

start().catch(fail);
