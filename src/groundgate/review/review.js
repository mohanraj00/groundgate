"use strict";
// The review page (docs/design/review.md section 8). Document text goes into the page only with
// textContent (section 9, rule 5). The token is in the start URL after #: a fragment never goes
// to a server, and each API request sends it in a header.
const TOKEN = location.hash.slice(1);
const $ = (id) => document.getElementById(id);
const PX = 1.4; // screen pixels for one PDF point
const KEYS = /^([1-9yxunsrkw]|Enter|Escape|ArrowLeft|ArrowRight)$/;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined && text !== null) e.textContent = String(text);
  return e;
}

async function api(path, body) {
  const init = { headers: { "X-Groundgate-Token": TOKEN } };
  if (body !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const r = await fetch(path, init);
  let data = {};
  try { data = await r.json(); } catch (e) { data = {}; }
  if (!r.ok) throw new Error(data.error || "the server answered " + r.status);
  return data;
}

let queue = [];
const history = [];
let at = -1;
let task = null;
let st = null; // the state of the open task
let busy = false; // a task loads or an answer goes to the server: keys wait

function fresh() {
  return { keys: 0, start: performance.now(), reasonSeen: false, mode: null, sel: null,
    parts: [], need: null, check: null, picked: [] };
}

function status(text) { $("status").textContent = text || ""; }

async function load() {
  if (!TOKEN) {
    status("Open the full URL that the terminal shows, with the part after #.");
    return;
  }
  try {
    queue = (await api("/api/queue")).tasks;
  } catch (e) {
    status(e.message);
    return;
  }
  next();
}

function next() {
  const k = queue.length ? queue[0].task : null;
  if (k === null) {
    task = null;
    $("source").replaceChildren(el("p", "note", "No task is left in the queue."));
    for (const id of ["question", "definition", "parts", "choices", "doc", "answered"]) $(id).replaceChildren();
    $("correct").hidden = true;
    $("reason").hidden = true;
    progress();
    return;
  }
  history.splice(at + 1);
  history.push(k);
  at = history.length - 1;
  open(k);
}

function progress() {
  const n = queue.length;
  $("progress").textContent = n === 1 ? "1 task is left." : n + " tasks are left.";
}

async function open(k) {
  busy = true;
  try {
    task = await api("/api/task/" + k);
  } catch (e) {
    status(e.message);
    return;
  } finally {
    busy = false;
  }
  st = fresh();
  status("");
  progress();
  $("doc").textContent = "Document: " + (task.document || "(no id)");
  $("question").textContent = task.question;
  $("definition").textContent = task.definition ? "The field: " + task.definition : "";
  $("parts").textContent = "Check each part: " + task.parts.join(", ") + ".";
  $("answered").textContent = task.answered ? "You answered " + task.answered +
    ". A new answer replaces it." : "";
  const list = $("choices");
  list.replaceChildren();
  for (const c of task.choices) {
    const li = el("li");
    li.append(el("span", "", c.shown));
    if (c.quote !== null) li.append(el("span", "quote", "In the text: " + c.quote));
    list.append(li);
  }
  if (task.label) drawLabel();
  $("correct").hidden = true;
  $("reason").hidden = true;
  $("reason").replaceChildren();
  $("typed").value = "";
  $("selected").textContent = "";
  $("outcome").replaceChildren();
  draw(task.view);
}

// A calibrate label (review.md section 11): a blind question with no correction

function drawLabel() {
  const help = task.label.question === "field"
    ? "Press y if it is, w if it is not, u if you are not sure."
    : "Press a number to mark each key that the value gives, then Enter. " +
      "Enter with no key marked says that it gives none. Press u if you are not sure.";
  $("parts").textContent += " " + help;
  if (task.label.question !== "key") return;
  const list = $("choices");
  task.label.keys.forEach((k, i) => {
    const li = el("li", st.picked.includes(k) ? "picked" : "", k);
    li.prepend(el("kbd", "", String(i + 1)));
    list.append(li);
  });
}

function labelKey(k) {
  const keys = task.label.keys;
  if (k === "u") save("unsure", {});
  else if (task.label.question === "field") {
    if (k === "y") save("confirm", {});
    else if (k === "w") save("wrong", {});
  } else if (/^[1-9]$/.test(k) && Number(k) <= keys.length) {
    const key = keys[Number(k) - 1];
    st.picked = st.picked.includes(key) ? st.picked.filter((x) => x !== key) : [...st.picked, key];
    $("choices").replaceChildren();
    $("parts").textContent = "Check each part: " + task.parts.join(", ") + ".";
    drawLabel();
  } else if (k === "Enter") {
    save("confirm", { field_keys: keys.filter((x) => st.picked.includes(x)) });
  }
}

// The source

function draw(view) {
  const box = $("source");
  box.replaceChildren();
  if (view.kind === "pdf") {
    for (const p of view.pages) drawPage(box, p);
    return;
  }
  if (view.frame) {
    const f = el("iframe", "original");
    f.setAttribute("sandbox", "");
    f.setAttribute("referrerpolicy", "no-referrer");
    f.title = "The original page";
    f.src = view.frame;
    box.append(f);
  }
  if (view.note) box.append(el("div", "note", view.note));
  const text = el("div", "text");
  let end = null;
  for (const b of view.blocks) {
    if (end !== null && b.start > end) text.append(el("div", "gap", "…"));
    end = b.start + b.text.length;
    if (b.closed) {
      const d = el("details", "block");
      d.append(el("summary", "", "The middle of the span: " + b.text.length + " characters"));
      d.append(segments(b));
      text.append(d);
    } else {
      const d = el("div", "block");
      d.append(segments(b));
      text.append(d);
    }
  }
  box.append(text);
  const first = box.querySelector("mark.value") || box.querySelector("mark");
  if (first) first.scrollIntoView({ block: "center" });
}

// One block as text nodes. Each element holds one text node and its offset in data-c, so a
// selection gives offsets in the document text.
function segments(b) {
  const frag = document.createDocumentFragment();
  const cuts = new Set([0, b.text.length]);
  for (const m of b.marks) { cuts.add(m[0] - b.start); cuts.add(m[1] - b.start); }
  const order = [...cuts].sort((x, y) => x - y);
  for (let i = 0; i + 1 < order.length; i++) {
    const s = order[i], e = order[i + 1];
    if (e <= s) continue;
    const covering = b.marks.filter((m) => m[0] - b.start <= s && m[1] - b.start >= e);
    let node;
    if (covering.length) {
      const kind = covering.some((m) => m[2] === "value") ? "value" : "part";
      node = el("mark", kind, b.text.slice(s, e));
      node.dataset.n = covering.flatMap((m) => m[3]).join(" ");
    } else {
      node = el("span", "", b.text.slice(s, e));
    }
    node.dataset.c = String(b.start + s);
    frag.append(node);
  }
  return frag;
}

function drawPage(box, p) {
  box.append(el("div", "pageno", "Page " + p.page));
  const page = el("div", "page");
  page.style.width = p.width * PX + "px";
  page.style.height = p.height * PX + "px";
  for (const w of p.words) {
    const s = el("span", "w", w[1]);
    s.dataset.c = String(w[0]);
    s.style.left = w[2] * PX + "px";
    s.style.top = w[3] * PX + "px";
    s.style.fontSize = Math.max((w[5] - w[3]) * PX * 0.9, 6) + "px";
    page.append(s, document.createTextNode(" "));
  }
  for (const m of p.marks) {
    const b = el("div", "box " + m[4]);
    b.style.left = m[0] * PX - 3 + "px";
    b.style.top = m[1] * PX - 3 + "px";
    b.style.width = (m[2] - m[0]) * PX + 6 + "px";
    b.style.height = (m[3] - m[1]) * PX + 6 + "px";
    page.append(b);
  }
  box.append(page);
  const first = page.querySelector(".box.value") || page.querySelector(".box");
  if (first) first.scrollIntoView({ block: "center" });
}

// The selection

function offsetOf(node, off) {
  let e = node;
  let add = 0;
  if (node.nodeType === Node.TEXT_NODE) {
    e = node.parentElement;
    add = off;
  } else if (off > 0 && node.childNodes[off - 1]) {
    // a point after a child: the end of that child
    const prev = node.childNodes[off - 1];
    const owner = prev.nodeType === Node.TEXT_NODE ? prev.parentElement : prev;
    if (owner && owner.dataset && owner.dataset.c !== undefined) {
      return Number(owner.dataset.c) + owner.textContent.length;
    }
  }
  while (e && !(e.dataset && e.dataset.c !== undefined)) e = e.parentElement;
  if (!e || !$("source").contains(e)) return null;
  return Number(e.dataset.c) + add;
}

function selection() {
  const s = window.getSelection();
  if (!s || s.isCollapsed || !s.rangeCount) return null;
  const a = offsetOf(s.anchorNode, s.anchorOffset);
  const b = offsetOf(s.focusNode, s.focusOffset);
  if (a === null || b === null || a === b) return null;
  return { start: Math.min(a, b), end: Math.max(a, b), text: s.toString() };
}

function startCorrection(mode) {
  st.mode = mode;
  st.sel = null;
  st.parts = [];
  st.need = null;
  st.check = null;
  $("correct").hidden = false;
  $("outcome").replaceChildren();
  $("selected").textContent = "";
  const help = mode === "correct"
    ? ["Select the right value in the text, then press Enter.",
      "If the same right value is at more than one place, select one of them. " +
      "Each place gives the same answer."]
    : ["Select the span of the value again, then press Enter."];
  if (mode === "correct" && task.item === "number") {
    help.push("A selection is always necessary. A typed value only replaces the number " +
      "that the page reads from the selection.");
    help.push("The gate needs the value in full. If the selection holds a scale word, " +
      "the page multiplies the number by it. If the scale is in another place, for example " +
      "\"in millions\" in a heading, type the value in full: for 9,776 in millions, " +
      "type 9776000000.");
  } else if (mode === "correct") {
    help.push("A selection is always necessary. A typed value only replaces the text " +
      "that the page reads from the selection.");
  }
  $("correct-help").replaceChildren(...help.map((t) => el("p", "", t)));
}

// The help text when the gate asks for a part of the value
const PART_HELP = {
  sign: "Select the word or the mark that makes the value negative, for example \"loss\".",
  scale: "Select all of the scale words, for example \"in millions\" or \"$m\". " +
    "One letter, such as the \"m\" of \"$m\", is not a scale.",
  unit: "Select the unit as the text writes it, for example \"EUR\" or \"$\".",
  key: "Select the words that give the key, for example the year.",
};

async function onEnter() {
  const s = selection();
  if (st.need && s) {
    st.parts.push({ role: st.need, start: s.start, end: s.end });
    st.need = null;
    window.getSelection().removeAllRanges();
    return check();
  }
  if (s && (!st.sel || s.start !== st.sel.start || s.end !== st.sel.end)) {
    st.sel = s;
    st.parts = [];
    $("selected").textContent = "Selected: " + s.text;
    return check();
  }
  if (!st.sel) {
    status("Select the value in the text first.");
    return;
  }
  if (st.check && st.check.outcome === "admitted") return save(st.mode, {});
  return check();
}

async function check() {
  status("");
  const body = { task: task.task, verdict: st.mode, start: st.sel.start, end: st.sel.end,
    value: $("typed").value || null, parts: st.parts };
  let r;
  try {
    r = await api("/api/check", body);
  } catch (e) {
    st.check = null;
    $("outcome").replaceChildren(el("div", "bad", e.message));
    return;
  }
  st.check = r;
  const out = $("outcome");
  out.replaceChildren();
  const words = { admitted: "The gate admits ", needs_verification: "The gate flags ",
    rejected: "The gate rejects " };
  out.append(el("div", r.outcome === "admitted" ? "good" : "bad",
    (words[r.outcome] || r.outcome + ": ") + (r.shown === null ? "the value" : r.shown) + "."));
  for (const c of r.codes) out.append(el("div", "", c.code + ": " + c.text));
  if (r.outcome === "rejected") {
    out.append(el("div", "", "Select the value again."));
    st.sel = null;
  } else if (r.missing.length) {
    st.need = r.missing[0];
    out.append(el("div", "", "Select the " + st.need + " in the text, then press Enter. " +
      (PART_HELP[st.need] || "")));
    out.append(el("div", "", "If the text does not give it, press k to keep the codes " +
      "and save the correction."));
  } else if (r.outcome === "admitted") {
    out.append(el("div", "", "Press Enter to save the correction."));
  } else {
    if (r.codes.some((c) => c.code === "SCALE_WORD")) {
      out.append(el("div", "", "The value is not in full. Select the number with its scale " +
        "word, or type the value in full, then press Enter."));
    }
    out.append(el("div", "", "Press k to keep these codes and save the correction."));
  }
}

// The answers

async function save(verdict, more) {
  if (!task) return;
  const body = Object.assign({ task: task.task, verdict: verdict, decision: null,
    reason_seen: st.reasonSeen, keys: st.keys, ms: Math.round(performance.now() - st.start),
    codes_kept: [] }, more);
  if (verdict === "correct" || verdict === "adjust_span") {
    Object.assign(body, { start: st.sel.start, end: st.sel.end,
      value: $("typed").value || null, parts: st.parts });
  }
  busy = true;
  try {
    queue = (await api("/api/answer", body)).tasks;
  } catch (e) {
    status(e.message);
    return;
  } finally {
    busy = false;
  }
  window.getSelection().removeAllRanges();
  if (at < history.length - 1) {
    at += 1;
    open(history[at]);
  } else {
    next();
  }
}

async function showReason() {
  let r;
  try {
    r = await api("/api/reason/" + task.task);
  } catch (e) {
    status(e.message);
    return;
  }
  st.reasonSeen = true;
  const box = $("reason");
  box.replaceChildren(el("div", "", "The reason"));
  if (!r.codes.length) box.append(el("div", "", "The task has no code."));
  for (const c of r.codes) box.append(el("div", "", c.code + ": " + c.text));
  for (const c of r.choices) {
    box.append(el("div", "", "Value " + c.n + ": " + c.outcome +
      (c.codes.length ? " (" + c.codes.join(", ") + ")" : "")));
  }
  box.hidden = false;
}

document.addEventListener("keydown", (ev) => {
  if (!task || !st || busy) return;
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  if (ev.target && ev.target.tagName === "INPUT") {
    if (ev.key === "Enter") { ev.preventDefault(); st.keys += 1; onEnter(); }
    if (ev.key === "Escape") ev.target.blur();
    return;
  }
  const n = task.choices.length;
  const k = ev.key;
  if (!KEYS.test(k)) return;
  ev.preventDefault();
  st.keys += 1; // before the answer, so that the answer counts its own key
  if (task.label && !/^(r|ArrowLeft|ArrowRight)$/.test(k)) labelKey(k);
  else if (k === "y" && n === 1) save("confirm", {});
  else if (/^[1-9]$/.test(k) && Number(k) <= n) {
    const c = task.choices[Number(k) - 1];
    if (n === 1) save("confirm", {});
    else save("choose", { decision: c.decision });
  } else if (k === "x") save("not_in_document", {});
  else if (k === "u") save("unsure", {});
  else if (k === "n") startCorrection("correct");
  else if (k === "s" && n > 0) startCorrection("adjust_span");
  else if (k === "r") showReason();
  else if (k === "k" && st.check && st.check.outcome === "needs_verification") {
    save(st.mode, { codes_kept: st.check.keep });
  } else if (k === "Enter" && st.mode) onEnter();
  else if (k === "Escape" && st.mode) {
    st.mode = null;
    $("correct").hidden = true;
  } else if (k === "ArrowLeft" && at > 0) {
    at -= 1;
    open(history[at]);
  } else if (k === "ArrowRight") {
    if (at < history.length - 1) {
      at += 1;
      open(history[at]);
    } else {
      const later = queue.find((q) => q.task !== task.task);
      if (later) {
        history.push(later.task);
        at = history.length - 1;
        open(later.task);
      }
    }
  }
});

load();
