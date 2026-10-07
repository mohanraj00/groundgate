"""A self-contained HTML review page for a receipt.

The page shows the document with every evidence span highlighted by outcome, and one card per
decision saying what was decided and why. It has no scripts and loads nothing: a
Content-Security-Policy forbids both, so a hostile document cannot run code in the reviewer's
browser even if it slipped past escaping.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from itertools import pairwise
from typing import Any

from .admit import verify
from .canonical import Offsets, digest
from .codes import DESCRIPTIONS
from .extract.layout import Layout
from .model import Policy, Schema

OUTCOMES = ("needs_verification", "rejected", "admitted")
LABELS = {
    "needs_verification": "Needs verification",
    "rejected": "Rejected",
    "admitted": "Admitted",
}
_SURROGATE = re.compile("[\ud800-\udfff]")
SEVERITY = {"admitted": 0, "needs_verification": 1, "rejected": 2}


ROLES = ("sign", "scale", "unit", "field", "key")  # SPEC §2.5 role items
NOT_IN_DOCUMENT = ("reference", "external", "knowledge")  # sources whose spans are elsewhere


@dataclass
class _Part:
    j: int
    role: str
    passed: bool
    found: bool  # the receipt gives the part a span
    span: tuple[int, int] | None  # code points in the decision's text
    cited: str | None  # the text at the span, when the report has that text


@dataclass
class _Item:
    n: int
    decision: Mapping[str, Any]
    candidate: Any
    span: tuple[int, int] | None  # code points in the decision's text
    in_document: bool = True  # the spans are in the document text
    cited: str | None = None  # the text at the value span, when the report has that text
    parts: list[_Part] = field(default_factory=list)


def _e(s: object) -> str:
    # A lone surrogate (half an emoji from a model) cannot be written as UTF-8: show U+FFFD.
    return escape(_SURROGATE.sub("\ufffd", str(s)), quote=True)


def _wrap(name: object) -> str:
    """Escaped identifier that may line-break after underscores."""
    return _e(name).replace("_", "_<wbr>")


def _short(sha: object) -> str:
    s = str(sha)
    return s[:19] + "…" if len(s) > 20 else s


def render(
    receipt: Mapping[str, Any],
    text: str,
    candidates: Sequence[object],
    *,
    schema: Schema | Mapping[str, Any] | None = None,
    policy: Policy | Mapping[str, Any] | None = None,
    layout: Layout | None = None,
    title: str | None = None,
    judgments: Sequence[object] | None = None,
    references: Sequence[object] | None = None,
    document_source: str | None = None,
) -> str:
    """Render ``receipt`` over ``text``. ``candidates`` supply the quotes shown on each card.

    With ``schema`` (and ``policy``, ``judgments``, ``references`` and ``document_source`` if they
    were used), the receipt is re-derived first and the page says whether it matched. Without them
    the page says it is unverified. The page shows the cited text of a reference decision only
    when ``references`` holds that reference.
    """
    verified = (
        None
        if schema is None
        else verify(
            receipt,
            text,
            schema,
            candidates,
            policy,
            judgments,
            references=references,
            document_source=document_source,
        ).ok
    )
    texts: dict[str, tuple[str, Offsets]] = {}
    for r in references or ():
        if (
            isinstance(r, Mapping)
            and isinstance(r.get("id"), str)
            and isinstance(r.get("text"), str)
        ):
            texts.setdefault(r["id"], (r["text"], Offsets(r["text"])))
    document = (text, Offsets(text))
    by_sha = {digest("candidate", c): c for c in candidates}
    items = []
    for n, d in enumerate(receipt.get("decisions", [])):
        # The spans of a decision are in the text of its value item: the document, or a
        # reference. External and knowledge decisions have no spans.
        source, ref = d.get("source"), d.get("ref")
        in_document = source not in NOT_IN_DOCUMENT
        own: tuple[str, Offsets] | None = None
        if in_document:
            own = document
        elif source == "reference" and isinstance(ref, str):
            own = texts.get(ref)
        span = _span(own, d.get("evidence"))
        item = _Item(n, d, by_sha.get(d.get("candidate_sha256")), span, in_document)
        item.cited = _cited(own, span)
        raw = d.get("parts")
        for j, p in enumerate(raw if isinstance(raw, list) else []):
            if not isinstance(p, Mapping):
                continue
            role = str(p.get("role")) if p.get("role") in ROLES else "other"
            found = p.get("start") is not None or p.get("end") is not None
            pspan = _span(own, p)
            part = _Part(j, role, p.get("passed") is True, found, pspan, _cited(own, pspan))
            item.parts.append(part)
        items.append(item)

    doc = receipt.get("document", {})
    heading = title or doc.get("id") or "Admission report"
    summary = receipt.get("summary", {})
    parts = [_HEAD.format(title=_e(heading))]
    parts.append('<header class="top"><div class="brand">groundgate report</div>')
    parts.append(f"<h1>{_e(heading)}</h1>")
    parts.append('<div class="stats">')
    for o in ("admitted", "needs_verification", "rejected"):
        parts.append(
            f'<span class="stat {o}"><b>{int(summary.get(o, 0))}</b> {LABELS[o].lower()}</span>'
        )
    parts.append("</div>")
    if verified is True:
        status = '<span class="ok">✓ receipt verified</span>: re-derived from its inputs'
    elif verified is False:
        status = '<span class="bad">✗ receipt does not match its inputs</span>'
    else:
        status = "receipt not verified"
    parts.append(
        f'<p class="meta">{status} · spec {_e(receipt.get("groundgate"))} · '
        f'<span title="{_e(receipt.get("receipt_sha256"))}">receipt '
        f"{_e(_short(receipt.get('receipt_sha256')))}</span> · "
        f'<span title="{_e(doc.get("sha256"))}">document {_e(_short(doc.get("sha256")))}</span>'
        "</p>"
    )
    coverage = receipt.get("coverage", [])
    if coverage:
        parts.append('<ul class="coverage">')
        for c in coverage:
            parts.append(
                f"<li><b>{_e(c.get('field'))}</b> <code>{_e(c.get('code'))}</code> "
                f"{_e(DESCRIPTIONS.get(str(c.get('code')), ''))}</li>"
            )
        parts.append("</ul>")
    parts.append("</header>")

    parts.append('<main><aside class="decisions">')
    parts.append('<div class="filters">Show')
    for o in OUTCOMES:
        parts.append(
            f'<label class="{o}"><input type="checkbox" id="show-{o}" checked> {LABELS[o]}</label>'
        )
    parts.append("</div>")
    for o in (*OUTCOMES, "other"):
        group = sorted(
            (i for i in items if _outcome(i) == o),
            key=lambda i: (i.span is None, i.span or (0, 0), i.n),
        )
        if not group:
            continue
        label = LABELS.get(o, "Unrecognised outcome")
        parts.append(f'<section class="group {o}"><h2>{label} <span>{len(group)}</span></h2>')
        parts.extend(_card(i, layout) for i in group)
        parts.append("</section>")
    parts.append('</aside><article class="doc">')
    parts.append(_document(text, items, layout))
    parts.append("</article></main></body></html>\n")
    return "".join(parts)


def _span(own: tuple[str, Offsets] | None, obj: object) -> tuple[int, int] | None:
    """The code-point span of ``obj`` in its text, or None when it has no valid span there."""
    if own is None or not isinstance(obj, Mapping):
        return None
    s, e = obj.get("start"), obj.get("end")
    if type(s) is not int or type(e) is not int:
        return None
    a, b = own[1].to_char(s), own[1].to_char(e)
    return None if a is None or b is None or a > b else (a, b)


def _cited(own: tuple[str, Offsets] | None, span: tuple[int, int] | None) -> str | None:
    return None if own is None or span is None else own[0][span[0] : span[1]]


def _evidence(c: object) -> list[Mapping[str, Any]]:
    """The candidate's evidence items. One item object counts as a list that holds it."""
    ev = c.get("evidence") if isinstance(c, Mapping) else None
    if isinstance(ev, Mapping):
        return [ev]
    return [i for i in ev if isinstance(i, Mapping)] if isinstance(ev, list) else []


def _item_text(c: object, role: str) -> str | None:
    """The quoted text of the candidate's document or reference item with this role."""
    for i in _evidence(c):
        source, r = i.get("source", "document"), i.get("role", "value")
        if source in ("document", "reference") and r == role and isinstance(i.get("text"), str):
            return str(i["text"])
    return None


def _outcome(item: _Item) -> str:
    o = item.decision.get("outcome")
    return o if isinstance(o, str) and o in LABELS else "other"


def _card(item: _Item, layout: Layout | None) -> str:
    d, c = item.decision, item.candidate
    outcome = _outcome(item)
    value = d.get("value")
    raw_value = c.get("value") if isinstance(c, Mapping) else None
    shown = value if value is not None else raw_value
    unit = d.get("unit") or (c.get("unit") if isinstance(c, Mapping) else None)
    cid = c.get("id") if isinstance(c, Mapping) else None
    tip = f' title="candidate {_e(cid)}"' if cid is not None else ""
    out = [f'<div class="card {outcome}"{tip}>']
    out.append(
        f'<div class="row"><code class="field">{_wrap(d.get("field") or "(no field)")}</code>'
        f'<span class="pill {outcome}">{_e(LABELS.get(outcome, d.get("outcome")))}</span></div>'
    )
    val = "(no value)" if shown is None else f"{shown}"
    key = d.get("key")
    out.append(
        f'<div class="value">{_e(val)}'
        + (f' <span class="unit">{_e(unit)}</span>' if unit else "")
        + (f' <span class="unit">for {_e(key)}</span>' if key else "")
        + "</div>"
    )
    codes = d.get("codes", [])
    if codes:
        out.append('<ul class="codes">')
        for code in codes:
            out.append(f"<li><code>{_e(code)}</code> {_e(DESCRIPTIONS.get(str(code), ''))}</li>")
        out.append("</ul>")
    source = d.get("source")
    if source == "reference":
        out.append(f'<p class="where">from reference <code>{_e(d.get("ref"))}</code></p>')
    elif source == "external":
        out.append(f'<p class="where">from an external page <code>{_e(d.get("url"))}</code></p>')
    elif source == "knowledge":
        out.append('<p class="where">from the extractor\'s knowledge</p>')
    quote = _item_text(c, "value")
    where = []
    if item.cited is not None:
        line = f"cited “{_e(_clip(item.cited))}”"
        if quote is not None and quote != item.cited:
            line += f", quoted “{_e(_clip(quote))}”"
        out.append(f'<p class="quote">{line}</p>')
    elif quote is not None:
        out.append(f'<p class="quote">quoted “{_e(_clip(quote))}”</p>')
    if source in ("external", "knowledge"):
        for i in _evidence(c):
            if i.get("source") == "external" and isinstance(i.get("text"), str):
                out.append(
                    f'<p class="quote">quoted “{_e(_clip(i["text"]))}” from '
                    f"<code>{_e(i.get('url'))}</code></p>"
                )
            elif i.get("source") == "knowledge" and isinstance(i.get("text"), str):
                out.append(f'<p class="quote">stated “{_e(_clip(i["text"]))}”</p>')
    if item.parts:
        out.append('<ul class="parts">')
        for p in item.parts:
            state = (
                '<span class="ok">passed</span>' if p.passed else '<span class="bad">failed</span>'
            )
            line = f"<b>{_e(p.role)}</b> {state}"
            pquote = _item_text(c, p.role)
            if p.cited is not None:
                line += f", cited “{_e(_clip(p.cited))}”"
                if pquote is not None and pquote != p.cited:
                    line += f", quoted “{_e(_clip(pquote))}”"
            elif pquote is not None:
                line += f", quoted “{_e(_clip(pquote))}”"
            if not p.found:
                line += ", not found"
            if item.in_document and p.span is not None:
                line += f' · <a href="#p{item.n}-{p.j}">show</a>'
            out.append(f"<li>{line}</li>")
        out.append("</ul>")
    missing = d.get("missing")
    if isinstance(missing, list) and missing:
        out.append(f'<p class="missing">missing: {_e(", ".join(map(str, missing)))}</p>')
    if item.in_document and item.span is not None:
        if layout is not None and isinstance(d.get("evidence"), Mapping):
            page = layout.page_at(d["evidence"]["start"])
            if page is not None:
                where.append(f"page {page}")
        where.append(f'<a href="#d{item.n}">show in document</a>')
    else:
        where.append("no location in the document")
    out.append(f'<p class="where">{" · ".join(where)}</p>')
    proposer = []
    if isinstance(c, Mapping):
        if isinstance(c.get("proposer"), str):
            proposer.append(_e(c["proposer"]))
        if isinstance(c.get("alignment_status"), str):
            proposer.append(f"LangExtract alignment {_e(c['alignment_status'])}")
    if proposer:
        out.append(f'<p class="where">{" · ".join(proposer)}</p>')
    out.append("</div>")
    return "".join(out)


def _clip(s: str, n: int = 120) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _document(text: str, items: list[_Item], layout: Layout | None) -> str:
    spans = [i for i in items if i.in_document and i.span is not None]
    parts = [(i, p) for i in items if i.in_document for p in i.parts if p.span is not None]
    bounds = sorted(
        {0, len(text)}
        | {x for i in spans for x in i.span or ()}
        | {x for _, p in parts for x in p.span or ()}
    )
    starts: dict[int, list[str]] = {}
    for i in spans:
        assert i.span is not None
        starts.setdefault(i.span[0], []).append(f"d{i.n}")
    for i, p in parts:
        assert p.span is not None
        starts.setdefault(p.span[0], []).append(f"p{i.n}-{p.j}")
    page_numbers = [p.number for p in layout.pages] if layout else []  # none: unnumbered
    breaks = 0

    def body(chunk: str) -> str:
        nonlocal breaks
        pieces = chunk.split("\f")
        html = _e(pieces[0])
        for piece in pieces[1:]:
            breaks += 1
            label = f"page {page_numbers[breaks]}" if breaks < len(page_numbers) else ""
            html += f'<span class="page" data-page="{_e(label)}"></span>{_e(piece)}'
        return html

    out = []
    first = page_numbers[0] if page_numbers else None
    if first is not None:
        out.append(f'<span class="page first" data-page="page {_e(first)}"></span>')
    for a, b in pairwise(bounds):
        if here := starts.get(a):
            ids = "".join(f'<span class="anchor" id="{n}"></span>' for n in here)
            out.append(f'<span class="anchors">{ids}</span>')
        covering = [i for i in spans if i.span and i.span[0] <= a and b <= i.span[1]]
        naming = [(i, p) for i, p in parts if p.span and p.span[0] <= a and b <= p.span[1]]
        if not covering and not naming:
            out.append(body(text[a:b]))
            continue
        classes = []
        if covering:
            classes.append(_outcome(max(covering, key=lambda i: SEVERITY.get(_outcome(i), 0))))
        if naming:
            extra = {f"part-{p.role}" for _, p in naming} | {
                f"part-{_outcome(i)}" for i, _ in naming
            }
            if any(not p.passed for _, p in naming):
                extra.add("part-failed")
            classes += ["part", *sorted(extra)]
        tip = "\n".join(
            [_tooltip(i.decision) for i in covering]
            + [
                f"{p.role} of {_tooltip(i.decision)}" + ("" if p.passed else " (failed)")
                for i, p in naming
            ]
        )
        out.append(f'<mark class="{" ".join(classes)}" title="{_e(tip)}">{body(text[a:b])}</mark>')
    return "".join(out)


def _tooltip(d: Mapping[str, Any]) -> str:
    unit = f" {d['unit']}" if d.get("unit") else ""
    key = f" for {d['key']}" if d.get("key") else ""
    codes = f" ({', '.join(d['codes'])})" if d.get("codes") else ""
    outcome = LABELS.get(str(d.get("outcome")), "")
    return f"{d.get('field')} = {d.get('value')}{unit}{key}: {outcome}{codes}"


_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy"
  content="default-src 'none'; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'">
<title>{title}</title>
<style>
:root {{
  --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --line: #d1d9e0; --panel: #f6f8fa;
  --ok: #1a7f37; --ok-bg: #dafbe1; --warn: #9a6700; --warn-bg: #fff1b8;
  --bad: #cf222e; --bad-bg: #ffe2e0; --focus: #0969da;
  color-scheme: light dark;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --line: #30363d; --panel: #151b23;
    --ok: #3fb950; --ok-bg: #12361f; --warn: #d29922; --warn-bg: #3b2e0a;
    --bad: #f85149; --bad-bg: #4a1519; --focus: #4493f8;
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--fg); height: 100vh; display: flex;
  flex-direction: column; overflow-wrap: anywhere;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }}
code {{ font: 12.5px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
.top {{ padding: 20px 24px 16px; border-bottom: 1px solid var(--line); }}
.brand {{ color: var(--muted); font-size: 12px; letter-spacing: .06em; text-transform: uppercase; }}
h1 {{ margin: 4px 0 10px; font-size: 22px; font-weight: 600; overflow-wrap: anywhere; }}
.stats {{ display: flex; flex-wrap: wrap; gap: 8px; }}
.stat {{ padding: 3px 10px; border-radius: 999px; font-size: 13px; }}
.stat b {{ font-size: 15px; }}
.stat.admitted, .pill.admitted {{ background: var(--ok-bg); color: var(--ok); }}
.stat.needs_verification, .pill.needs_verification {{ background: var(--warn-bg);
  color: var(--warn); }}
.stat.rejected, .pill.rejected {{ background: var(--bad-bg); color: var(--bad); }}
.meta {{ margin: 10px 0 0; color: var(--muted); font-size: 12.5px; }}
.ok {{ color: var(--ok); font-weight: 600; }} .bad {{ color: var(--bad); font-weight: 600; }}
.coverage {{ margin: 12px 0 0; padding: 8px 12px 8px 28px; border-radius: 6px;
  background: var(--bad-bg); color: var(--fg); }}
main {{ flex: 1; min-height: 0; display: grid;
  grid-template-columns: minmax(300px, 400px) minmax(0, 1fr); }}
.decisions {{ border-right: 1px solid var(--line); background: var(--panel); padding: 12px;
  overflow: auto; }}
.doc {{ padding: 20px 28px 60vh; white-space: pre-wrap; overflow-wrap: anywhere; overflow: auto;
  font: 14px/1.6 Charter, "Iowan Old Style", Georgia, serif; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; color: var(--muted);
  font-size: 12.5px; margin-bottom: 8px; }}
.filters label {{ color: var(--fg); cursor: pointer; }}
.group h2 {{ font-size: 13px; margin: 14px 2px 6px; color: var(--muted); font-weight: 600; }}
.card {{ background: var(--bg); border: 1px solid var(--line); border-left: 4px solid;
  border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }}
.card.admitted {{ border-left-color: var(--ok); }}
.card.needs_verification {{ border-left-color: var(--warn); }}
.card.rejected {{ border-left-color: var(--bad); }}
.row {{ display: flex; justify-content: space-between; gap: 8px; align-items: center; }}
.field {{ overflow-wrap: normal; min-width: 0; }}
.pill {{ flex-shrink: 0; font-size: 11.5px; padding: 1px 8px; border-radius: 999px;
  white-space: nowrap; }}
.value {{ font-size: 18px; font-weight: 600; margin: 4px 0; overflow-wrap: anywhere; }}
.unit {{ color: var(--muted); font-weight: 400; font-size: 14px; }}
.codes {{ list-style: none; margin: 6px 0; padding: 0; font-size: 12.5px; }}
.codes li {{ margin: 3px 0; }}
.codes code {{ font-size: 11.5px; padding: 0 4px; border-radius: 4px; background: var(--panel);
  border: 1px solid var(--line); }}
.quote {{ margin: 6px 0; font-size: 12.5px; color: var(--muted); overflow-wrap: anywhere; }}
.where {{ margin: 4px 0 0; font-size: 12px; color: var(--muted); }}
.parts {{ margin: 6px 0; padding-left: 18px; font-size: 12.5px; color: var(--muted); }}
.parts b {{ color: var(--fg); font-weight: 600; }}
.missing {{ margin: 6px 0; font-size: 12.5px; color: var(--warn); }}
a {{ color: var(--focus); }}
mark {{ color: inherit; border-radius: 2px; padding: 1px 0; }}
mark.admitted {{ background: var(--ok-bg); box-shadow: inset 0 -2px var(--ok); }}
mark.needs_verification {{ background: var(--warn-bg); box-shadow: inset 0 -2px var(--warn); }}
mark.rejected {{ background: var(--bad-bg); box-shadow: inset 0 -2px var(--bad); }}
mark.part {{ text-underline-offset: 3px; text-decoration-thickness: 2px;
  text-decoration-color: var(--focus); text-decoration-style: solid; }}
mark.part-failed {{ text-decoration-color: var(--bad); text-decoration-style: wavy; }}
mark.part:not(.admitted):not(.needs_verification):not(.rejected) {{ background: none; }}
.anchor {{ scroll-margin-top: 40vh; }}
.anchors:has(.anchor:target) + mark {{ outline: 2px solid var(--focus); outline-offset: 2px; }}
.page {{ display: block; border-top: 1px dashed var(--line); margin: 18px 0 8px; }}
.page::after {{ content: attr(data-page); display: block; color: var(--muted);
  font: 11px ui-monospace, Menlo, monospace; margin-top: 2px; }}
.page.first {{ border-top: 0; margin-top: 0; }}
body:has(#show-admitted:not(:checked)) .group.admitted,
body:has(#show-needs_verification:not(:checked)) .group.needs_verification,
body:has(#show-rejected:not(:checked)) .group.rejected {{ display: none; }}
body:has(#show-admitted:not(:checked)) mark.admitted,
body:has(#show-needs_verification:not(:checked)) mark.needs_verification,
body:has(#show-rejected:not(:checked)) mark.rejected {{ background: none; box-shadow: none; }}
mark.part-other,
body:has(#show-admitted:checked) mark.part-admitted,
body:has(#show-needs_verification:checked) mark.part-needs_verification,
body:has(#show-rejected:checked) mark.part-rejected {{ text-decoration-line: underline; }}
@media (max-width: 800px) {{
  body {{ height: auto; display: block; }}
  main {{ grid-template-columns: minmax(0, 1fr); }}
  .decisions, .doc {{ overflow: visible; border-right: 0; }}
  .top, .doc {{ padding-left: 16px; padding-right: 16px; }}
}}
</style></head><body>
"""
