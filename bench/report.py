"""Render bench/results.json as bench/RESULTS.md and two SVG charts. Called by bench/score.py."""

from __future__ import annotations

from html import escape
from typing import Any

SERIES = {
    "lx_all": ("LangExtract, every extraction", "#b8b8b8"),
    "lx_aligned": ("LangExtract, aligned", "#8c8c8c"),
    "lx_exact": ("LangExtract, MATCH_EXACT only", "#5b6b7f"),
    "groundgate": ("groundgate, admitted", "#1f7a4d"),
}
ERRORS = (
    "value_x10",
    "text_and_value_x10",
    "near_miss_digit",
    "unit_swap",
    "null_literal",
    "adjacent_value",
)
ERROR_NAMES = {
    "value_x10": "value attribute x10, text right",
    "text_and_value_x10": "value and text x10",
    "near_miss_digit": "one digit changed",
    "unit_swap": "wrong unit",
    "null_literal": '"null" as the value',
    "adjacent_value": "a nearby number with the same unit",
    "clean": "correct value, verbatim text",
    "paraphrase": "correct value, paraphrased text",
}


def pct(r: dict[str, Any] | None, ci: bool = False) -> str:
    if not r or r["rate"] is None:
        return "n/a"
    s = f"{100 * r['rate']:.1f}% ({r['k']}/{r['n']})"
    if ci:
        s += f" [{100 * r['ci95'][0]:.0f}, {100 * r['ci95'][1]:.0f}]"
    return s


def share(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%" if n else "n/a"


# ------------------------------------------------------------------------------ charts


def bars(
    title: str,
    groups: list[tuple[str, list[tuple[str, float, tuple[float, float] | None]]]],
    note: str,
) -> str:
    """A horizontal grouped bar chart, 0 to 100%. groups: (label, [(series, rate, ci)])."""
    left, width, bar, gap = 250, 400, 14, 14
    rows = sum(len(b) for _, b in groups)
    used = sorted({s for _, b in groups for s, _, _ in b}, key=list(SERIES).index)
    height = 70 + rows * (bar + 3) + len(groups) * gap + 22 * ((len(used) + 1) // 2) + 30
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {left + width + 60} {height}" '
        f'font-family="-apple-system, Segoe UI, Helvetica, Arial, sans-serif" font-size="12">',
        '<rect width="100%" height="100%" rx="8" fill="#ffffff" stroke="#dddddd"/>',
        f'<text x="16" y="26" font-size="14" font-weight="600" fill="#111">{escape(title)}</text>',
    ]
    y = 46
    for tick in (0, 25, 50, 75, 100):
        x = left + width * tick / 100
        out.append(
            f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y + rows * (bar + 3) + len(groups) * gap}"'
            f' stroke="#eeeeee"/>'
        )
        out.append(f'<text x="{x}" y="{y - 4}" text-anchor="middle" fill="#777">{tick}%</text>')
    y += 6
    for label, series in groups:
        mid = y + len(series) * (bar + 3) / 2
        out.append(
            f'<text x="{left - 10}" y="{mid + 4}" text-anchor="end" fill="#222">'
            f"{escape(label)}</text>"
        )
        for s, value, ci in series:
            w = max(width * value, 1.5)
            out.append(
                f'<rect x="{left}" y="{y}" width="{w:.1f}" height="{bar}" fill="{SERIES[s][1]}"/>'
            )
            if ci:
                x0, x1, cy = left + width * ci[0], left + width * ci[1], y + bar / 2
                out.append(
                    f'<line x1="{x0:.1f}" y1="{cy}" x2="{x1:.1f}" y2="{cy}" '
                    f'stroke="#222" stroke-width="1"/>'
                )
            end = max(w, width * ci[1]) if ci else w
            out.append(
                f'<text x="{left + end + 5:.1f}" y="{y + bar - 3}" fill="#333" '
                f'font-size="11">{100 * value:.0f}%</text>'
            )
            y += bar + 3
        y += gap
    y += 8
    for i, s in enumerate(used):
        x, ly = 16 + (i % 2) * 330, y + (i // 2) * 22
        out.append(f'<rect x="{x}" y="{ly}" width="12" height="12" fill="{SERIES[s][1]}"/>')
        out.append(f'<text x="{x + 18}" y="{ly + 10}" fill="#222">{escape(SERIES[s][0])}</text>')
    y += 22 * ((len(used) + 1) // 2) + 6
    out.append(f'<text x="16" y="{y}" fill="#666" font-size="11">{escape(note)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def chart_a(a: dict[str, Any]) -> str:
    groups = []
    for cls in ERRORS:
        if cls not in a:
            continue
        n = a[cls]["n"]
        groups.append(
            (
                ERROR_NAMES[cls],
                [(c, a[cls].get(f"{c}:accept", 0) / n, None) for c in ("lx_exact", "groundgate")],
            )
        )
    return bars(
        "Planted errors let through without review",
        groups,
        "Track A. One error planted per gold fact, aligned by LangExtract's own Resolver.",
    )


def chart_b(b: dict[str, Any]) -> str:
    groups = []
    for run, per in b["runs"].items():
        series = []
        for c in ("lx_all", "lx_exact", "groundgate"):
            r = per[c]["escape"]
            if r["rate"] is not None:
                series.append((c, r["rate"], tuple(r["ci95"])))
        if series:
            groups.append((run.replace(" @ ", ", buffer "), series))
    return bars(
        "Wrong model extractions accepted without review",
        groups,
        "Track B. Lines are 95% Wilson intervals.",
    )


# ---------------------------------------------------------------------------- markdown


def render(res: dict[str, Any]) -> dict[str, str]:
    """File name (relative to bench/) -> content."""
    a, b, gold = res["track_a"], res["track_b"], res["gold"]
    md = ["# Benchmark results", ""]
    if gold["status"].startswith("draft"):
        md += [
            "> **Draft gold.** These numbers score against model-written labels that no person",
            "> has checked yet. They are for development only.",
            "",
        ]
    md += [
        "Generated by `bench/score.py` from the cached runs in `bench/runs`. "
        "[bench/README.md](README.md) explains the method.",
        "",
        f"Gold: {gold['documents']} documents, {gold['facts']} facts, "
        f"{gold['absent_fields']} fields confirmed absent ({gold['status']}).",
        "",
        "## Track A: planted errors",
        "",
        "![Planted errors let through](charts/track_a.svg)",
        "",
        "| Planted | n | LangExtract, all | aligned | MATCH_EXACT | groundgate admitted | "
        "review | rejected |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cls in ("clean", "paraphrase", *ERRORS):
        if cls not in a:
            continue
        r, n = a[cls], a[cls]["n"]
        cells = [share(r.get(f"{c}:accept", 0), n) for c in ("lx_all", "lx_aligned", "lx_exact")]
        cells += [share(r.get(f"groundgate:{v}", 0), n) for v in ("accept", "review", "reject")]
        md.append(f"| {ERROR_NAMES[cls]} | {n} | " + " | ".join(cells) + " |")
    md += [
        "",
        "Percentages are the share accepted without review. For the first two rows higher is",
        "better; for the rest lower is better.",
        "",
        "## Track B: real model runs",
        "",
        "![Wrong extractions accepted](charts/track_b.svg)",
        "",
        "| Run | docs | candidates | wrong | escaped, LangExtract all | escaped, MATCH_EXACT | "
        "escaped, groundgate | wrong sent to review | false rejects | review load | "
        "recall, admitted | recall, admitted or review |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for run, per in b["runs"].items():
        g = per["groundgate"]
        md.append(
            f"| {run} | {per['documents']} | {g['candidates']} | {g['wrong']} | "
            f"{pct(per['lx_all']['escape'])} | {pct(per['lx_exact']['escape'])} | "
            f"{pct(g['escape'], ci=True)} | {pct(g['wrong_sent_to_review'])} | "
            f"{pct(g['false_reject'])} | {pct(g['review_load'])} | "
            f"{pct(g['recall']['accepted'])} | {pct(g['recall']['accepted_or_review'])} |"
        )
    md += [
        "",
        "### By source",
        "",
        "| Run | source | wrong | escaped, MATCH_EXACT | escaped, groundgate |",
        "|---|---|---:|---:|---:|",
    ]
    for run, per in b["runs"].items():
        for kind, k in per["by_kind"].items():
            if k["groundgate"]["wrong"]:
                md.append(
                    f"| {run} | {kind} | {k['groundgate']['wrong']} | "
                    f"{pct(k['lx_exact']['escape'])} | {pct(k['groundgate']['escape'])} |"
                )
    md += [
        "",
        "### What the wrong extractions were",
        "",
        "| Run | wrong value | field absent from the document | wrong unit | not a number |",
        "|---|---:|---:|---:|---:|",
    ]
    for run, per in b["runs"].items():
        w = per["groundgate"]["wrong_by_class"]
        md.append(
            f"| {run} | {w.get('wrong_value', 0)} | {w.get('absent_field', 0)} | "
            f"{w.get('wrong_unit', 0)} | {w.get('unparsable', 0)} |"
        )
    if b["pairs"]:
        md += [
            "",
            "### Two models through one gate",
            "",
            "Both models' candidates go into one `admit` call, so a disagreement on a "
            "single-valued field is flagged `CONFLICTING_CANDIDATES`.",
            "",
            "| Models | docs | wrong | escaped | review load | recall, admitted |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for pair, p in b["pairs"].items():
            md.append(
                f"| {pair} | {p['documents']} | {p['wrong']} | {pct(p['escape'], ci=True)}"
                f" | {pct(p['review_load'])} | {pct(p['recall']['accepted'])} |"
            )
    md += [
        "",
        "## Appendix: wrong and admitted",
        "",
        "Every wrong candidate groundgate admitted without review.",
        "",
    ]
    if b["escapes"]:
        md += [
            "| Run | doc | field | value | gold | why wrong | text around the evidence |",
            "|---|---|---|---:|---|---|---|",
        ]
        for e in b["escapes"]:
            ctx = (e["context"] or "").replace("|", "\\|")
            md.append(
                f"| {e['model']}, {e['buffer']} | {e['doc']} | {e['field']} | {e['value']} "
                f"| {', '.join(e['gold']) or 'absent'} | {e['label']} | {ctx} |"
            )
    else:
        md.append("None.")
    return {
        "RESULTS.md": "\n".join(md) + "\n",
        "charts/track_a.svg": chart_a(a),
        "charts/track_b.svg": chart_b(b),
    }
