"""Turn the cached LangExtract runs into candidates, a receipt and the review page.

    python build.py

Reads runs/*.json (written by propose.py) and writes candidates.json, receipt.json and
report.html. No model is called. With more than one run, every model's extractions go through
the same gate, so two models that disagree on a field are flagged CONFLICTING_CANDIDATES.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import groundgate as gg
from groundgate.adapters.langextract import to_candidates
from groundgate.extract import Layout
from groundgate.report import render

HERE = Path(__file__).parent
DOCUMENT_ID = "irs-p590a-2025-pages-1-2"


def candidates() -> list[dict[str, Any]]:
    text = (HERE / "document.txt").read_text(encoding="utf-8")
    out = []
    for path in sorted((HERE / "runs").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["document"]["text"] != text:
            raise SystemExit(f"{path.name} was run on a different document.txt")
        for c in to_candidates(record["document"]):
            c["id"] = f"{path.stem}/{c['id']}"
            c["proposer"] = f"{record['model']} via LangExtract {record['langextract']}"
            out.append(c)
    return out


def main() -> None:
    text = (HERE / "document.txt").read_text(encoding="utf-8")
    schema = json.loads((HERE / "schema.json").read_text(encoding="utf-8"))
    layout = Layout.from_dict(json.loads((HERE / "layout.json").read_text(encoding="utf-8")))
    cands = candidates()
    receipt = gg.admit(text, schema, cands, document_id=DOCUMENT_ID).to_dict()
    assert gg.verify(receipt, text, schema, cands).ok

    def dump(name: str, obj: Any) -> None:
        body = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
        (HERE / name).write_text(body, encoding="utf-8")

    dump("candidates.json", cands)
    dump("receipt.json", receipt)
    title = "IRS Publication 590-A, pages 1-2"
    page = render(receipt, text, cands, schema=schema, layout=layout, title=title)
    (HERE / "report.html").write_text(page, encoding="utf-8")
    print(json.dumps(receipt["summary"]), f"{len(receipt['coverage'])} required fields missing")


if __name__ == "__main__":
    main()
