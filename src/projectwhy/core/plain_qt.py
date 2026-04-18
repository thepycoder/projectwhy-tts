"""Plain text normalization aligned with QTextBrowser / QTextDocument plain text.

EPUB block strings and GUI highlighting must agree on how HTML becomes a flat
string. This module is the single definition of those rules (Option A).
"""

from __future__ import annotations

import re


def plain_text_like_qtextbrowser(raw: str) -> str:
    """Collapse whitespace and drop spaces Qt strips after '(' / before ')' at inline tags."""
    text = re.sub(r"\s+", " ", raw).strip()
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    # QTextDocument drops a space immediately after opening typographic quotes in
    # toPlainText(), while BeautifulSoup get_text() often keeps “ word → “ word.
    text = re.sub(r"([\u2018\u201c\u00ab])\s+", r"\1", text)
    return text


def normalize_plain_with_position_map(plain: str) -> tuple[str, list[int]]:
    """Normalize *plain* like Qt's plain text for matching; keep a map back to *plain* indices.

    Returns ``(normalized, orig_pos_map)`` where ``orig_pos_map[i]`` is the index in *plain*
    corresponding to position *i* in *normalized*.
    """
    n1, m1 = _collapse_whitespace_with_map(plain)
    return _drop_inline_paren_gaps(n1, m1)


def _collapse_whitespace_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse runs of whitespace (incl. NBSP) to a single space; strip ends."""
    out: list[str] = []
    omap: list[int] = []
    prev_ws = False
    for i, ch in enumerate(text):
        if ch in (" ", "\t", "\n", "\r", "\xa0"):
            if not prev_ws and out:
                out.append(" ")
                omap.append(i)
            prev_ws = True
        else:
            out.append(ch)
            omap.append(i)
            prev_ws = False
    joined = "".join(out)
    s = joined.strip()
    left = len(joined) - len(joined.lstrip())
    return s, omap[left : left + len(s)]


def _drop_inline_paren_gaps(norm: str, pos_map: list[int]) -> tuple[str, list[int]]:
    """Remove spaces after '(' like QTextBrowser; keep index map aligned."""
    out: list[str] = []
    omap: list[int] = []
    i = 0
    n = len(norm)
    while i < n:
        if i + 1 < n and norm[i] == "(" and norm[i + 1] == " ":
            j = i + 1
            while j < n and norm[j] == " ":
                j += 1
            if j < n:
                out.append("(")
                omap.append(pos_map[i])
                i = j
                continue
        out.append(norm[i])
        omap.append(pos_map[i])
        i += 1
    return "".join(out), omap
