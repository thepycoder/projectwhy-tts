"""EPUB loading (one Page per spine chapter)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import spacy
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString, Tag

from projectwhy.core.models import Block, BlockType, BBox, Document, Page, WordPosition
from projectwhy.core.plain_qt import plain_text_like_qtextbrowser

if TYPE_CHECKING:
    from spacy.language import Language

# Target size range for a TTS block (characters).
# Sentences are merged up to _MIN_BLOCK_CHARS, then hard-capped at _MAX_BLOCK_CHARS.
_MIN_BLOCK_CHARS = 200
_MAX_BLOCK_CHARS = 500

_nlp: Language | None = None

# HTML tags that represent block-level boundaries in a document.
# When walking the tree we recurse into these rather than collect their full text,
# so that inline children (<em>, <a>, <strong>, …) never fragment a sentence.
_BLOCK_LEVEL_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "dd", "details",
    "div", "dt", "figcaption", "figure", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "li",
    "main", "nav", "ol", "p", "pre", "section", "summary",
    "table", "td", "th", "ul",
})

_STRIP_TAGS = frozenset(
    {
        "script",
        "style",
        "svg",
        "img",
        "iframe",
        "object",
        "embed",
        "video",
        "audio",
        "canvas",
    }
)


def _strip_unwanted(soup: BeautifulSoup) -> None:
    for name in _STRIP_TAGS:
        for tag in soup.find_all(name):
            tag.decompose()


def _sanitize_tree(root: Tag) -> None:
    """Strip event handlers and javascript: URLs from tags under *root*."""
    for el in list(root.descendants):
        if not isinstance(el, Tag):
            continue
        attrs = dict(el.attrs) if el.attrs else {}
        for attr in list(attrs):
            al = attr.lower()
            if al.startswith("on"):
                del el.attrs[attr]
            elif al in ("href", "src", "xlink:href", "formaction"):
                v = el.attrs.get(attr)
                if isinstance(v, str) and v.strip().lower().startswith("javascript:"):
                    del el.attrs[attr]


def _body_inner_html(soup: BeautifulSoup) -> str:
    body = soup.find("body")
    if body and isinstance(body, Tag):
        parts: list[str] = []
        for child in body.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
            elif isinstance(child, Tag):
                parts.append(str(child))
        inner = "".join(parts).strip()
        if inner:
            return inner
    # No body or empty: serialize non-head content
    for bad in soup(["head", "script", "style"]):
        if isinstance(bad, Tag):
            bad.decompose()
    return str(soup).strip()


def _get_nlp() -> Language:
    global _nlp
    if _nlp is None:
        _nlp = spacy.blank("en")
        _nlp.add_pipe("sentencizer")
    return _nlp


def _collect_paragraphs(el: Tag, out: list[str]) -> None:
    """Recursively collect one text string per leaf block element.

    Recurses into container elements (div, section, …) but extracts text with
    no separator from leaf blocks (p, h1-h6, li, …) so inline tags like
    <em> and <strong> never fragment a sentence.  We then collapse whitespace
    the same way HTML rendering does, so the string matches QTextBrowser.toPlainText().
    """
    has_block_child = any(
        isinstance(c, Tag) and c.name in _BLOCK_LEVEL_TAGS for c in el.children
    )
    if has_block_child:
        for child in el.children:
            if isinstance(child, Tag):
                _collect_paragraphs(child, out)
    else:
        raw = el.get_text()
        text = plain_text_like_qtextbrowser(raw)
        if text:
            out.append(text)


def _split_long(text: str) -> list[str]:
    """Recursively split *text* at clause boundaries, falling back to word-boundary hard split."""
    if len(text) <= _MAX_BLOCK_CHARS:
        return [text]
    for sep in (";", ","):
        idx = text.find(sep, _MAX_BLOCK_CHARS // 2)
        if 0 < idx < len(text) - 1:
            left = text[: idx + 1].strip()
            right = text[idx + 1 :].strip()
            if left and right:
                return _split_long(left) + _split_long(right)
    # Hard split at the last word boundary before the limit.
    words = text.split()
    chunks: list[str] = []
    current: list[str] = []
    cur_len = 0
    for w in words:
        extra = len(w) + (1 if current else 0)
        if cur_len + extra > _MAX_BLOCK_CHARS and current:
            chunks.append(" ".join(current))
            current, cur_len = [w], len(w)
        else:
            current.append(w)
            cur_len += extra
    if current:
        chunks.append(" ".join(current))
    return chunks


def _sentences(text: str) -> list[str]:
    """Split *text* into sentences via spaCy sentencizer, cap each at _MAX_BLOCK_CHARS."""
    doc = _get_nlp()(text)
    result: list[str] = []
    for sent in doc.sents:
        s = sent.text.strip()
        if not s:
            continue
        result.extend(_split_long(s) if len(s) > _MAX_BLOCK_CHARS else [s])
    return result


def _merge_to_target(chunks: list[str]) -> list[str]:
    """Merge adjacent sentence chunks until each block reaches _MIN_BLOCK_CHARS (max _MAX_BLOCK_CHARS)."""
    result: list[str] = []
    acc = ""
    for chunk in chunks:
        if not acc:
            acc = chunk
        elif len(acc) + 1 + len(chunk) > _MAX_BLOCK_CHARS:
            result.append(acc)
            acc = chunk
        else:
            acc += " " + chunk
        if len(acc) >= _MIN_BLOCK_CHARS:
            result.append(acc)
            acc = ""
    if acc:
        result.append(acc)
    return result


def _html_to_blocks(html_fragment: str) -> list[Block]:
    soup = BeautifulSoup(html_fragment, "html.parser")
    _strip_unwanted(soup)
    root = soup.find("body") or soup
    if isinstance(root, Tag):
        _sanitize_tree(root)

    # Replace <br> with newline text so get_text() produces whitespace matching
    # QTextBrowser's rendering (which converts <br> to a line break).
    for br in root.find_all("br"):
        br.replace_with("\n")

    paragraphs: list[str] = []
    _collect_paragraphs(root, paragraphs)
    if not paragraphs:
        # Fallback for unusual documents with no recognisable block structure.
        text = plain_text_like_qtextbrowser(root.get_text())
        if text:
            paragraphs = [text]

    blocks: list[Block] = []
    y = 0.0
    for para in paragraphs:
        for chunk in _merge_to_target(_sentences(para)):
            h = 16.0
            blocks.append(
                Block(
                    block_type=BlockType.TEXT,
                    text=chunk,
                    bbox=BBox(0, y, 800, y + h),
                    words=[WordPosition(text=w, bbox=BBox(0, y, 800, y + h)) for w in chunk.split()],
                )
            )
            y += h + 4
    return blocks


def _wrap_reader_html(inner: str) -> str:
    """Wrap fragment so QTextBrowser always has a block root."""
    inner = inner.strip()
    if not inner:
        return "<p></p>"
    return f'<div class="eread-root">{inner}</div>'


def _spine_document_items(book: epub.EpubBook):
    """Yield (EpubItem) in spine order; skip non-linear and non-(X)HTML."""
    for spine_entry in book.spine:
        if isinstance(spine_entry, tuple):
            item_id = spine_entry[0]
            linear = spine_entry[1] if len(spine_entry) > 1 else True
        else:
            item_id, linear = spine_entry, True
        if linear in (False, "no"):
            continue
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        mt = (getattr(item, "media_type", None) or "").lower()
        if "html" not in mt and "xml" not in mt:
            continue
        yield item


def load_epub_document(path: str) -> Document:
    book = epub.read_epub(path)
    title = book.get_metadata("DC", "title")
    name = title[0][0] if title else path
    pages: list[Page] = []
    idx = 0
    for item in _spine_document_items(book):
        raw = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")
        _strip_unwanted(soup)
        body = soup.find("body")
        root_sanitize: Tag = body if isinstance(body, Tag) else soup
        _sanitize_tree(root_sanitize)

        inner = _body_inner_html(soup)
        inner = inner.strip()
        if not inner or not re.search(r"\S", inner):
            continue

        blocks = _html_to_blocks(str(soup))
        if not blocks:
            continue
        joined = "\n\n".join(b.text for b in blocks)
        safe_inner = _wrap_reader_html(inner)
        page_html = safe_inner
        pages.append(
            Page(index=idx, blocks=blocks, image=None, raw_text=joined, html=page_html),
        )
        idx += 1
    if not pages:
        pages.append(Page(index=0, blocks=[], image=None, raw_text="", html=None))
    return Document(path=path, doc_type="epub", pages=pages, metadata={"title": name})
