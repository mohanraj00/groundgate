let S = null, at = 0, pick = new Set(), shown = null;
const $ = (id) => document.getElementById(id);
// the server prints the token after # in the start URL; a fragment never goes to a server, and
// every request to the API sends it in a header
const TOKEN = location.hash.slice(1);
const api = (path, init = {}) =>
  fetch(path, { ...init, headers: { ...(init.headers || {}), "X-Groundgate-Token": TOKEN } });
const isKey = () => S.question === "key";
const markOf = (id) => [...document.querySelectorAll("#text mark")]
  .find((m) => m.dataset.ids.split(" ").includes(id));

function tag(v) {
  if (v === null) return "not sure";
  if (v === true) return "yes";
  if (v === false) return "no";
  return v.length ? v.join(", ") : "none";
}

function button(label, onclick, cls = "") {
  const b = document.createElement("button");
  b.innerHTML = label; b.className = cls; b.onclick = onclick;
  return b;
}

async function load() {
  const r = await api("/state");
  if (!r.ok) {
    $("q").textContent = "Open the full URL that the terminal shows, with the part after #.";
    return;
  }
  S = await r.json();
  if (isKey()) {
    $("q").textContent = "Which of these does the yellow value belong to? Select every one.";
    $("answers").append(button("0 &nbsp;None of them", () => save([])),
      button("? &nbsp;Not sure", () => save(null)));
    $("save").hidden = false;
    $("keys").innerHTML = "<kbd>1</kbd>&ndash;<kbd>9</kbd> select or clear, <kbd>Enter</kbd> " +
      "save the selection<br><kbd>0</kbd> none and next, <kbd>?</kbd> not sure and next<br>";
  } else {
    $("answers").append(button("y &nbsp;Yes", () => save(true)), button("n &nbsp;No", () => save(false)));
    $("opts").append(button("? &nbsp;Not sure", () => save(null)));
    $("keys").innerHTML = "<kbd>y</kbd> yes, <kbd>n</kbd> no, <kbd>?</kbd> not sure<br>";
  }
  $("keys").innerHTML += "<kbd>&larr;</kbd> <kbd>&rarr;</kbd> back and forward, <kbd>u</kbd> " +
    "next unlabeled<br>Click a value in the text to go to it. A dashed box is not labeled yet.";
  const first = S.items.findIndex((it) => !(it.id in S.labels));
  await go(first < 0 ? 0 : first);
}

function paintMarks() {
  document.querySelectorAll("#text mark").forEach((m) => {
    const ids = m.dataset.ids.split(" ");
    const all = ids.every((id) => id in S.labels);
    m.classList.toggle("done", all && ids.some((id) => S.labels[id] !== null));
    m.classList.toggle("unsure", all && ids.every((id) => S.labels[id] === null));
    m.classList.toggle("now", ids.includes(S.items[at].id));
  });
}

async function go(j) {
  at = Math.max(0, Math.min(S.items.length - 1, j));
  const it = S.items[at];
  const fresh = shown !== it.doc;
  if (fresh) {
    $("docname").textContent = it.doc;
    $("text").innerHTML = await (await api("/doc/" + encodeURIComponent(it.doc))).text();
    document.querySelectorAll("#text mark").forEach((m) => {
      m.onclick = () => go(S.items.findIndex((x) => x.id === m.dataset.ids.split(" ")[0]));
    });
    shown = it.doc;
  }
  const v = S.labels[it.id];
  pick = new Set(Array.isArray(v) ? v : []);
  paintMarks();
  const m = markOf(it.id);
  m.scrollIntoView({ block: "center", behavior: fresh ? "instant" : "smooth" });
  const done = S.items.filter((x) => x.id in S.labels).length;
  $("progress").textContent = `${done} of ${S.items.length} labeled. This is item ${at + 1}.`;
  $("bar").style.width = `${(100 * done) / S.items.length}%`;
  $("item").innerHTML = `<b></b> &nbsp;in ${it.doc}`;
  $("item").querySelector("b").textContent = m.textContent;
  if (isKey()) {
    $("desc").textContent = `Field: ${it.field}. ${it.description}`;
    $("opts").replaceChildren(...it.keys.map((k, i) => {
      const b = button(`<span class="k">${i + 1}</span><span></span>`, () => toggle(k), "opt");
      b.lastChild.textContent = k; b.dataset.key = k;
      return b;
    }));
  } else {
    $("q").textContent = `Does the text state the yellow value as ${it.field}?`;
    $("desc").textContent = it.description;
  }
  const url = (S.links || {})[it.doc];
  $("link").hidden = !url;
  if (url) $("link").href = url;
  $("saved").textContent = it.id in S.labels ? `Saved now: ${tag(v)}` : "Not labeled yet.";
  paintOpts();
}

function paintOpts() {
  document.querySelectorAll(".opt").forEach((b) => b.classList.toggle("on", pick.has(b.dataset.key)));
}

function toggle(k) {
  pick.has(k) ? pick.delete(k) : pick.add(k);
  paintOpts();
}

async function save(value) {
  const r = await api("/label", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: S.items[at].id, value }) });
  if (!r.ok) { $("saved").textContent = "Not saved. Look at the terminal."; return; }
  S.labels = (await r.json()).labels;
  await go(at + 1);
}

$("save").onclick = () => pick.size ? save([...pick]) : ($("saved").textContent =
  "Select a key, or press 0 for none.");
$("prev").onclick = () => go(at - 1);
$("todo").onclick = () => {
  const n = S.items.findIndex((x, i) => i > at && !(x.id in S.labels));
  const any = S.items.findIndex((x) => !(x.id in S.labels));
  go(n >= 0 ? n : any >= 0 ? any : at);
};
// a button clicked with the pointer keeps no focus, so a later Space never clicks it again;
// a click from the keyboard (detail 0) keeps it, so keyboard users stay on their control
document.addEventListener("click", (e) => { if (e.detail > 0) e.target.closest("button")?.blur(); });
document.addEventListener("keydown", (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const n = Number(e.key);
  if (isKey() && n >= 1 && n <= S.items[at].keys.length) toggle(S.items[at].keys[n - 1]);
  else if (isKey() && e.key === "0") save([]);
  else if (isKey() && e.key === "Enter") { e.preventDefault(); $("save").click(); }
  else if (!isKey() && e.key === "y") save(true);
  else if (!isKey() && e.key === "n") save(false);
  else if (e.key === "?") save(null);
  else if (e.key === "ArrowLeft") go(at - 1);
  else if (e.key === "ArrowRight") go(at + 1);
  else if (e.key === "u") $("todo").click();
});
load();
