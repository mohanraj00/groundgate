// The decision page of bench/label/decide.py. All answer text goes in with textContent.
"use strict";

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined && text !== null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function show(answer) {
  if (!answer) return "(no answer)";
  if (answer.status === "absent") return "absent" + (answer.note ? "\nnote: " + answer.note : "");
  const v = typeof answer.value === "string" ? answer.value : JSON.stringify(answer.value, null, 1);
  let out = v;
  if (answer.unit) out += "\nunit: " + answer.unit;
  if (answer.quote) out += "\nquote: " + answer.quote;
  if (answer.note) out += "\nnote: " + answer.note;
  return out;
}

// The one place where two text answers differ, with 60 characters of context on each side.
function difference(a, b) {
  if (!a || !b || typeof a.value !== "string" || typeof b.value !== "string") return "";
  const x = a.value.split(/\s+/).join(" "), y = b.value.split(/\s+/).join(" ");
  if (x === y) return "";
  let p = 0;
  while (p < x.length && p < y.length && x[p] === y[p]) p++;
  let s = 0;
  while (s < x.length - p && s < y.length - p && x[x.length - 1 - s] === y[y.length - 1 - s]) s++;
  const pre = x.slice(Math.max(0, p - 60), p);
  return "Difference after …" + pre + "\n  pass a: " + (x.slice(p, x.length - s) || "(nothing)") +
    "\n  pass b: " + (y.slice(p, y.length - s) || "(nothing)");
}

async function decide(item, box, choice, value, unit, note) {
  const r = await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slot: item.slot, choice, value, unit, note }),
  });
  const got = await r.json();
  if (!r.ok) { alert(got.error); return; }
  box.classList.add("done");
  box.querySelector(".chosen").textContent = "Decided: " + choice;
  document.getElementById("status").textContent = got.decided + " decided, " + got.open + " open";
}

function render(item, decided) {
  const box = el("section", null, "item" + (decided ? " done" : ""));
  box.append(el("h3", item.slot + " · " + item.id + " · " + item.kind + " · " + item.split));
  box.append(el("p", item.request));
  box.append(el("p", "Field rule: " + item.rule, "muted"));
  const det = el("details");
  det.append(el("summary", "Reader text of the section"));
  det.append(el("pre", item.text));
  box.append(det);
  const cols = el("div", null, "cols");
  for (const [name, a] of [["Pass a", item.a], ["Pass b", item.b]]) {
    const c = el("div");
    c.append(el("strong", name));
    c.append(el("pre", show(a)));
    cols.append(c);
  }
  box.append(cols);
  const diff = difference(item.a, item.b);
  if (diff) box.append(el("pre", diff, "diff"));
  for (const c of item.checks) box.append(el("pre", "Absence check: " + show(c)));
  const note = el("textarea");
  note.placeholder = "note (optional)";
  const value = el("textarea");
  value.placeholder = "the right value, for \"Other\": text, a number, YYYY-MM-DD, or a JSON list of rows";
  const unit = el("input");
  unit.placeholder = "unit (numbers only)";
  for (const [label, choice] of [["Pass a is right", "a"], ["Pass b is right", "b"], ["Absent", "absent"], ["Other", "other"]]) {
    const b = el("button", label);
    b.addEventListener("click", () => {
      let v = null;
      if (choice === "other") {
        v = value.value;
        if (item.kind === "record") {
          try { v = JSON.parse(v); } catch (e) { alert("a record value must be a JSON list"); return; }
        }
      }
      decide(item, box, choice, v, choice === "other" ? unit.value || null : null, note.value);
    });
    box.append(b);
  }
  box.append(el("div", "Other value:", "muted"), value, unit, note);
  box.append(el("p", decided ? "Decided: " + decided.choice : "", "chosen"));
  return box;
}

(async function () {
  const r = await fetch("/api/items");
  const data = await r.json();
  const list = document.getElementById("list");
  for (const item of data.items) list.append(render(item, data.decisions[item.slot]));
  const n = Object.keys(data.decisions).length;
  document.getElementById("status").textContent = n + " decided, " + (data.items.length - n) + " open";
})();
