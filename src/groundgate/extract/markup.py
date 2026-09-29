"""HTML and XML to text with the standard library. Block elements become line breaks.

HTML goes through ``html.parser``; XML (including HL7 SPL, the format of FDA drug labels on
DailyMed) goes through ``xml.etree``, so CDATA, namespaces and markup inside ``<title>`` behave
the same on every Python version.

- Superscripts and subscripts are marked ``^`` and ``_``: ``10<sup>9</sup>`` reads ``10^9``,
  never ``109``.
- HTML elements hidden with the ``hidden`` attribute or an inline ``display:none`` or
  ``visibility:hidden`` style are dropped: text a reader cannot see is not evidence. Stylesheets
  are not evaluated.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "template"}
HEAD = {"head", "title", "meta", "link", "style", "script", "base", "noscript", "template"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
        "track", "wbr"}  # fmt: skip
PARAGRAPH = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "dl", "blockquote", "pre",
    "section", "article", "header", "footer", "nav", "aside", "main", "figure", "hr",
    "title", "paragraph", "caption", "list",
}  # fmt: skip
LINE = {"div", "li", "tr", "dt", "dd", "br", "figcaption", "address", "item", "thead", "tbody"}
CELL = {"td", "th"}
SCRIPTS = {"sup": "^", "sub": "_"}
_WS = re.compile(r"\s+")
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


class _Writer:
    """Collects text runs and block breaks, collapsing whitespace as a browser does."""

    def __init__(self) -> None:
        self.out: list[str] = []
        self.pending = 0  # newlines owed before the next text
        self.cell_gap = False
        self.after_script = False

    def start(self, tag: str) -> None:
        if tag in PARAGRAPH:
            self.block(2)
        elif tag in LINE:
            self.block(1)
        elif tag in CELL and self.cell_gap:
            self.out.append("\t")
            self.cell_gap = False
        elif tag in SCRIPTS:
            self.text(SCRIPTS[tag], raw=True)

    def end(self, tag: str) -> None:
        if tag in PARAGRAPH:
            self.block(2)
        elif tag in LINE:
            self.block(1)
        elif tag in CELL:
            self.cell_gap = True
        elif tag in SCRIPTS:
            self.after_script = True

    def block(self, newlines: int) -> None:
        if self.out:
            self.pending = max(self.pending, newlines)
        self.cell_gap = False

    def text(self, data: str, pre: bool = False, raw: bool = False) -> None:
        if self.cell_gap and not data.strip():
            return
        if not (pre or raw):
            data = _WS.sub(" ", data)
            at_line_start = not self.out or self.pending or self.out[-1].endswith(("\n", "\t"))
            if at_line_start or self.out[-1].endswith(" "):
                data = data.lstrip(" ")
        if not data:
            return
        if self.after_script and data[0].isdigit():
            data = " " + data  # "10<sup>9</sup>5" must not read as "10^95"
        self.after_script = False
        if self.pending:
            self.out.append("\n" * self.pending)
            self.pending = 0
        self.out.append(data)

    def result(self) -> str:
        lines = "".join(self.out).split("\n")
        return "\n".join(line.rstrip(" \t") for line in lines).strip("\n")


def _hidden(attrs: list[tuple[str, str | None]]) -> bool:
    for name, value in attrs:
        if name == "hidden" or (name == "style" and value and _HIDDEN_STYLE.search(value)):
            return True
    return False


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.w = _Writer()
        self.skip = 0
        self.pre = 0
        self.in_head = False
        self.hide: list[str] = []  # open elements from the outermost hidden one inward

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self.in_head = True
            return
        if self.in_head and tag not in HEAD:
            self.in_head = False  # </head> is optional in HTML
        if self.hide or (_hidden(attrs) and tag not in VOID):
            if tag not in VOID:
                self.hide.append(tag)
            return
        if tag in SKIP:
            self.skip += 1
        elif tag == "pre":
            self.pre += 1
        if not self.in_head:
            self.w.start(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not (self.hide or self.in_head or _hidden(attrs)) and tag in PARAGRAPH | LINE:
            self.w.start(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False
            return
        if self.hide:
            if tag in self.hide:
                del self.hide[len(self.hide) - 1 - self.hide[::-1].index(tag) :]
            return
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "pre":
            self.pre = max(0, self.pre - 1)
        if not self.in_head:
            self.w.end(tag)

    def handle_data(self, data: str) -> None:
        if not (self.skip or self.in_head or self.hide):
            self.w.text(data, pre=bool(self.pre))


def html_text(source: str) -> str:
    p = _HTML()
    p.feed(source)
    p.close()
    return p.w.result()


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def xml_text(data: bytes) -> str:
    """Text of an XML document. Raises ``xml.etree.ElementTree.ParseError``."""
    w = _Writer()

    def walk(e: ET.Element) -> None:
        tag = _local(e.tag)
        if tag in SKIP:
            return
        w.start(tag)
        if e.text:
            w.text(e.text)
        for child in e:
            walk(child)
            if child.tail:
                w.text(child.tail)
        w.end(tag)

    walk(ET.fromstring(data))
    return w.result()
