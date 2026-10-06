"""The two questions: the key clear and the field doubt. For each one: which decisions of spec 0.3
become items, what a label is, the prompt for a judge, and how answers are scored."""

from __future__ import annotations

import itertools
from typing import Any

import groundgate as gg
from groundgate.text import parse_value, tokens

from .stats import CEILINGS, pick, upper_95

NONE = "none"
BEFORE, AFTER = 400, 150  # code points of text around the marked value in a prompt
BINS = (0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.01)


def char_offset(text: str, byte: int) -> int:
    return len(text.encode()[:byte].decode())


def mark(text: str, start: int, end: int, value: object) -> tuple[int, int]:
    """The value in code points: the first number token of the evidence that equals it, or the
    whole evidence when there is none (a string field, for example)."""
    a, b = char_offset(text, start), char_offset(text, end)
    want = parse_value(str(value)) if value is not None else None
    for tok in tokens(text, a, b):
        if want is not None and parse_value(text[tok.start : tok.end]) == want:
            return tok.start, tok.end
    return a, b


def state(text: str, item: dict[str, Any]) -> str:
    """The text around the value, with the value in brackets."""
    a, b = item["mark"]
    return text[max(0, a - BEFORE) : a] + f"[{text[a:b]}]" + text[b : b + AFTER]


def sample(
    question: str, doc: str, text: str, schema: dict[str, Any], cands: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The items of one document: each candidate flagged KEY_NOT_AT_VALUE for the key question,
    and each admitted candidate for the field question."""
    receipt = gg.admit(text, schema, cands)
    by_sha = {d.candidate_sha256: d for d in receipt.decisions}
    out = []
    for n, c in enumerate(cands):
        d = by_sha[gg.digest("candidate", c)]
        if d.evidence is None:
            continue
        if question == "key" and "KEY_NOT_AT_VALUE" not in d.codes:
            continue
        if question == "field" and d.outcome != "admitted":
            continue
        it = {
            "id": f"{doc}:{n}",
            "doc": doc,
            "field": d.field,
            "value": d.value,
            "mark": list(mark(text, *d.evidence, d.value)),
        }
        if question == "key":
            it["key"] = c["key"]
            it["keys"] = list(schema["fields"][d.field]["keys"])
        out.append(it)
    return out


def valid_label(question: str, item: dict[str, Any], label: object) -> bool:
    """A key label is a list of the field's keys (empty for none), a field label is true or
    false, and None is not sure."""
    if label is None:
        return True
    if question == "key":
        return isinstance(label, list) and all(k in item["keys"] for k in label)
    return isinstance(label, bool)


def prompt(
    question: str, text: str, item: dict[str, Any], context: str, descriptions: dict[str, str]
) -> tuple[str, dict[str, Any]]:
    """The state and the question for a judge. The wording is fixed before any run."""
    head = (context + " " if context else "") + "The text marks one value in brackets. "
    if question == "key":
        criteria = {f"k{n}": k for n, k in enumerate(item["keys"], 1)}
        criteria[NONE] = "none of these: the value belongs to something else, or to nothing"
        q = {"type": "choice", "instructions": head + "Which of these does it belong to?"}
        return state(text, item), {"key": {**q, "criteria": criteria}}
    desc = descriptions.get(item["field"], item["field"])
    q = {"type": "noul", "instructions": head + f"Does the text state it as this value? {desc}"}
    return state(text, item), {"field": q}


def keep(question: str, answers: dict[str, Any]) -> dict[str, Any]:
    """What a run records of one answer."""
    (a,) = answers.values()
    if question == "key":
        return {"choice": a["choice"], "confidence": round(float(a["confidence"]), 4)}
    return {"p": round(float(a["noul"]), 4)}


def chosen(item: dict[str, Any], choice: str) -> str | None:
    """The key that a choice names, or None for "none" or an unknown name."""
    n = choice[1:]
    if choice.startswith("k") and n.isdigit() and 1 <= int(n) <= len(item["keys"]):
        return str(item["keys"][int(n) - 1])
    return None


# ---------------------------------------------------------------------------------- scoring

KEY_THRESHOLDS = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99)
FIELD_THRESHOLDS = (0.01, 0.05, 0.1, 0.2, 0.3, 0.5)


def score_key(rows: list[tuple[dict[str, Any], list[str], dict[str, Any]]]) -> dict[str, Any]:
    """A judge clears a flag when it chooses the candidate's key with confidence of t or more.
    The clear is right when the label holds that key, and an escape when it does not."""
    by_t = {}
    for t in KEY_THRESHOLDS:
        right = escapes = 0
        for it, label, a in rows:
            if chosen(it, a["choice"]) == it["key"] and a["confidence"] >= t:
                right += it["key"] in label
                escapes += it["key"] not in label
        by_t[str(t)] = {
            "clears_right": right,
            "escapes": escapes,
            "escape_rate_upper_95": upper_95(escapes, right + escapes),
        }
    bins = []
    for lo, hi in itertools.pairwise(BINS):
        inside = [(it, lab, a) for it, lab, a in rows if lo <= a["confidence"] < hi]
        good = sum(_correct(it, lab, a) for it, lab, a in inside)
        bins.append({"from": lo, "to": min(hi, 1), "items": len(inside), "correct": good})
    return {
        "items": len(rows),
        "right_flags": sum(it["key"] in lab for it, lab, _ in rows),
        "by_threshold": by_t,
        "bins": bins,
    }


def _correct(it: dict[str, Any], label: list[str], a: dict[str, Any]) -> bool:
    k = chosen(it, a["choice"])
    return k in label if k is not None else not label


def score_field(rows: list[tuple[dict[str, Any], bool, dict[str, Any]]]) -> dict[str, Any]:
    """A judge doubts an admitted value when its probability that the text states the field is
    below t. A doubt catches a wrong value, and it sends a right one to review."""
    right = sum(lab for _, lab, _ in rows)
    by_t = {}
    for t in FIELD_THRESHOLDS:
        caught = sum(not lab and a["p"] < t for _, lab, a in rows)
        doubted = sum(lab and a["p"] < t for _, lab, a in rows)
        by_t[str(t)] = {
            "wrong_caught": caught,
            "right_doubted": doubted,
            "right_doubted_upper_95": upper_95(doubted, right),
        }
    bins = []
    for lo, hi in itertools.pairwise(BINS):
        inside = [lab for _, lab, a in rows if lo <= a["p"] < hi]
        bins.append({"from": lo, "to": min(hi, 1), "items": len(inside), "right": sum(inside)})
    return {
        "items": len(rows),
        "right": right,
        "wrong": len(rows) - right,
        "by_threshold": by_t,
        "bins": bins,
    }


def score(
    question: str,
    items: list[dict[str, Any]],
    labels: dict[str, Any],
    parts: dict[str, str],
    answers: dict[str, Any],
) -> dict[str, Any]:
    """Each part's scores, and for each ceiling the §9 threshold on the calibration part with
    the test part at it. Items labeled not sure are left out."""
    out: dict[str, Any] = {}
    for p in ("calibration", "test"):
        rows = [
            (it, labels[it["id"]], answers[it["id"]])
            for it in items
            if parts[it["id"]] == p and labels.get(it["id"]) is not None
        ]
        out[p] = score_key(rows) if question == "key" else score_field(rows)
    cal = out["calibration"]["by_threshold"]
    out["by_ceiling"] = {}
    for c in CEILINGS:
        if question == "key":
            t = pick(KEY_THRESHOLDS, lambda t: cal[str(t)]["escape_rate_upper_95"], c, "lowest")
        else:
            t = pick(
                FIELD_THRESHOLDS, lambda t: cal[str(t)]["right_doubted_upper_95"], c, "highest"
            )
        out["by_ceiling"][str(c)] = {
            "threshold": t,
            "test": out["test"]["by_threshold"][str(t)] if t is not None else None,
        }
    return out
