"""EPUB loading (one Page per spine chapter)."""

from __future__ import annotations

import base64
import posixpath
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

# Maps leaf HTML tag names to their semantic BlockType.
# Used in _collect_typed_paragraphs when a tag has no block-level children.
_LEAF_TAG_TO_BLOCK_TYPE: dict[str, BlockType] = {
    "h1": BlockType.DOCUMENT_TITLE,
    "h2": BlockType.PARAGRAPH_TITLE,
    "h3": BlockType.PARAGRAPH_TITLE,
    "h4": BlockType.PARAGRAPH_TITLE,
    "h5": BlockType.PARAGRAPH_TITLE,
    "h6": BlockType.PARAGRAPH_TITLE,
    "blockquote": BlockType.ASIDE_TEXT,
    "aside": BlockType.ASIDE_TEXT,
    "figcaption": BlockType.FIGURE_CAPTION,
    "pre": BlockType.ALGORITHM,
}

# Tags that are emitted as a single opaque block without recursing into children.
# All of these map to speak=False types in BLOCK_CONFIG (table, nav, header, footer).
_STOP_RECURSE_TAG_BLOCK_TYPES: dict[str, BlockType] = {
    "table": BlockType.TABLE,
    "nav": BlockType.TABLE_OF_CONTENTS,
    "header": BlockType.HEADER,
    "footer": BlockType.FOOTER,
}

# Subset of _STRIP_TAGS to remove from the display HTML before capturing inner.
# <img> is intentionally excluded so resolved data-URI images survive into the viewer.
_STRIP_FROM_DISPLAY: frozenset[str] = _STRIP_TAGS - {"img"}


def _strip_tags(soup: BeautifulSoup, names: frozenset[str]) -> None:
    for name in names:
        for tag in soup.find_all(name):
            tag.decompose()


def _strip_unwanted(soup: BeautifulSoup) -> None:
    _strip_tags(soup, _STRIP_TAGS)


def _strip_non_visual(soup: BeautifulSoup) -> None:
    """Strip script/style and non-renderable embeds but keep <img> (with resolved data URIs)."""
    _strip_tags(soup, _STRIP_FROM_DISPLAY)


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


def _collect_typed_paragraphs(el: Tag, out: list[tuple[str, BlockType]]) -> None:
    """Recursively collect (text, BlockType) pairs, one per leaf block element.

    Tags in _STOP_RECURSE_TAG_BLOCK_TYPES are emitted as a single unit without
    recursing into children (e.g. <table> becomes one TABLE block). For all other
    leaf blocks the tag name is looked up in _LEAF_TAG_TO_BLOCK_TYPE to preserve
    semantic distinctions (h1 → DOCUMENT_TITLE, h2-h6 → PARAGRAPH_TITLE, etc.).
    Inline children (<em>, <a>, <strong>, …) never fragment a sentence.
    """
    if el.name in _STOP_RECURSE_TAG_BLOCK_TYPES:
        raw = el.get_text()
        text = plain_text_like_qtextbrowser(raw)
        if text:
            out.append((text, _STOP_RECURSE_TAG_BLOCK_TYPES[el.name]))
        return

    has_block_child = any(
        isinstance(c, Tag) and c.name in _BLOCK_LEVEL_TAGS for c in el.children
    )
    if has_block_child:
        for child in el.children:
            if isinstance(child, Tag):
                _collect_typed_paragraphs(child, out)
    else:
        raw = el.get_text()
        text = plain_text_like_qtextbrowser(raw)
        if text:
            block_type = _LEAF_TAG_TO_BLOCK_TYPE.get(el.name, BlockType.TEXT)
            out.append((text, block_type))


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


def _html_to_blocks_for_root(root: Tag) -> list[Block]:
    """Build blocks from *root* (typically ``<body>``). Caller has already removed unwanted tags."""
    _sanitize_tree(root)

    # Replace <br> with newline text so get_text() produces whitespace matching
    # QTextBrowser's rendering (which converts <br> to a line break).
    for br in root.find_all("br"):
        br.replace_with("\n")

    paragraphs: list[tuple[str, BlockType]] = []
    _collect_typed_paragraphs(root, paragraphs)
    if not paragraphs:
        # Fallback for unusual documents with no recognisable block structure.
        text = plain_text_like_qtextbrowser(root.get_text())
        if text:
            paragraphs = [(text, BlockType.TEXT)]

    blocks: list[Block] = []
    y = 0.0
    for para_text, block_type in paragraphs:
        for chunk in _merge_to_target(_sentences(para_text)):
            h = 16.0
            blocks.append(
                Block(
                    block_type=block_type,
                    text=chunk,
                    bbox=BBox(0, y, 800, y + h),
                    words=[WordPosition(text=w, bbox=BBox(0, y, 800, y + h)) for w in chunk.split()],
                )
            )
            y += h + 4
    return blocks


def _html_to_blocks(html_fragment: str) -> list[Block]:
    soup = BeautifulSoup(html_fragment, "html.parser")
    _strip_unwanted(soup)
    root = soup.find("body") or soup
    if not isinstance(root, Tag):
        return []
    return _html_to_blocks_for_root(root)


def _resolve_item_by_href(
    book: epub.EpubBook, item_dir: str, href: str
):
    """Look up an EPUB item by href, trying exact path then basename fallback."""
    resolved = posixpath.normpath(posixpath.join(item_dir, href)).lstrip("/")
    item = book.get_item_with_href(resolved)
    if item is None:
        basename = posixpath.basename(href)
        for candidate in book.get_items():
            if posixpath.basename(candidate.file_name) == basename:
                return candidate
    return item


def _resolve_images(soup: BeautifulSoup, book: epub.EpubBook, item_file_name: str) -> None:
    """Replace image references with base64 data URIs from embedded EPUB resources.

    Handles two cases:
    - Standard <img src="..."> tags.
    - <svg><image xlink:href="..."/></svg> covers (common in EPUB3): the entire
      <svg> is replaced with a plain <img> so QTextBrowser can render it.

    Must be called before _strip_unwanted so that images survive into the display HTML.
    Unresolvable hrefs are left unchanged; QTextBrowser silently ignores broken src values.
    """
    item_dir = posixpath.dirname(item_file_name)

    # Handle SVG covers: <svg><image xlink:href="cover.jpg"/></svg>
    for svg in list(soup.find_all("svg")):
        for svg_img in svg.find_all("image"):
            href = svg_img.get("xlink:href") or svg_img.get("href", "")
            if not href or href.startswith("data:"):
                continue
            image_item = _resolve_item_by_href(book, item_dir, href)
            if image_item is None:
                continue
            media_type = getattr(image_item, "media_type", None) or "image/jpeg"
            data = base64.b64encode(image_item.get_content()).decode("ascii")
            new_img = soup.new_tag("img", src=f"data:{media_type};base64,{data}")
            svg.replace_with(new_img)
            break  # one replacement per SVG

    # Handle standard <img src="...">
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith("data:"):
            continue
        image_item = _resolve_item_by_href(book, item_dir, src)
        if image_item is None:
            continue
        media_type = getattr(image_item, "media_type", None) or "image/png"
        data = base64.b64encode(image_item.get_content()).decode("ascii")
        img["src"] = f"data:{media_type};base64,{data}"


def _extract_epub_css(soup: BeautifulSoup, book: epub.EpubBook, item_file_name: str) -> str:
    """Collect CSS from linked stylesheets and inline <style> blocks.

    Must be called before any stripping so all CSS sources are still present in the soup.
    """
    item_dir = posixpath.dirname(item_file_name)
    parts: list[str] = []

    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if not href or href.startswith("data:"):
            continue
        css_item = _resolve_item_by_href(book, item_dir, href)
        if css_item is not None:
            try:
                parts.append(css_item.get_content().decode("utf-8", errors="replace"))
            except Exception:  # noqa: BLE001
                pass

    for style_tag in soup.find_all("style"):
        parts.append(style_tag.get_text())

    return "\n".join(p for p in parts if p.strip())


def _wrap_reader_html(inner: str, epub_css: str = "") -> str:
    """Wrap fragment so QTextBrowser always has a block root.

    EPUB CSS (if any) is embedded as a <style> block in the fragment; TextDocView hoists
    publisher styles into <head> first, then applies app CSS last so reader font size,
    line height, and theme colors win.
    """
    inner = inner.strip() or "<p></p>"
    css_block = f'<style>{epub_css}</style>\n' if epub_css.strip() else ""
    return f'{css_block}<div class="eread-root">{inner}</div>'


def _epub_author(book: epub.EpubBook) -> str | None:
    creators = book.get_metadata("DC", "creator")
    if not creators:
        return None
    val, _meta = creators[0]
    s = str(val).strip()
    return s or None


def _epub_cover_bytes(book: epub.EpubBook) -> tuple[bytes | None, str | None]:
    """Return (bytes, mime) for the best-effort cover image, or (None, None)."""
    for item in book.get_items():
        if isinstance(item, epub.EpubCover):
            data = item.get_content()
            if data:
                mt = getattr(item, "media_type", None) or "image/jpeg"
                return bytes(data), str(mt).lower()
    for item in book.get_items():
        props = getattr(item, "properties", None) or []
        if isinstance(props, str):
            props = props.split()
        if "cover-image" in props:
            mt = (getattr(item, "media_type", None) or "").lower()
            if mt.startswith("image/"):
                data = item.get_content()
                if data:
                    return bytes(data), mt
    try:
        opf_meta = book.get_metadata("OPF", "meta")
    except KeyError:
        opf_meta = []
    for _val, attrs in opf_meta:
        if not attrs or attrs.get("name") != "cover":
            continue
        cid = attrs.get("content")
        if not cid:
            continue
        citem = book.get_item_with_id(str(cid))
        if citem is None:
            continue
        data = citem.get_content()
        if data:
            mt = getattr(citem, "media_type", None) or "image/jpeg"
            return bytes(data), str(mt).lower()
    return None, None


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
    author = _epub_author(book)
    cover_bytes, cover_mime = _epub_cover_bytes(book)

    # Collect all CSS from the manifest once.  Many EPUBs (including this one)
    # declare a shared stylesheet in the OPF manifest but never reference it
    # via <link> tags in individual HTML files.  We use this as a fallback when
    # per-page extraction finds nothing.
    manifest_css_parts: list[str] = []
    for css_item in book.get_items():
        mt = (getattr(css_item, "media_type", "") or "").lower()
        if "css" in mt or css_item.file_name.endswith(".css"):
            try:
                chunk = css_item.get_content().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if chunk.strip():
                manifest_css_parts.append(chunk)
    manifest_css = "\n".join(manifest_css_parts)

    pages: list[Page] = []
    idx = 0
    for item in _spine_document_items(book):
        raw = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")
        body = soup.find("body")
        root_sanitize: Tag = body if isinstance(body, Tag) else soup
        _sanitize_tree(root_sanitize)
        # Per spine item: extract CSS (while <link>/<style> exist) → resolve images to
        # data URIs → strip script/style/svg/etc. but keep <img> for display → serialize
        # body for Page.html → strip <img> etc. for TTS and build blocks.
        epub_css = _extract_epub_css(soup, book, item.file_name) or manifest_css
        _resolve_images(soup, book, item.file_name)
        _strip_non_visual(soup)

        inner = _body_inner_html(soup)
        inner = inner.strip()
        if not inner or not re.search(r"\S", inner):
            continue

        _strip_unwanted(soup)
        root_for_blocks = soup.find("body") or soup
        blocks = (
            _html_to_blocks_for_root(root_for_blocks)
            if isinstance(root_for_blocks, Tag)
            else []
        )
        joined = "\n\n".join(b.text for b in blocks)
        pages.append(
            Page(
                index=idx,
                blocks=blocks,
                image=None,
                raw_text=joined,
                html=_wrap_reader_html(inner, epub_css),
                spine_href=item.file_name,
            ),
        )
        idx += 1
    if not pages:
        pages.append(Page(index=0, blocks=[], image=None, raw_text="", html=None, spine_href=None))
    meta = {
        "title": name,
        "author": author,
        "cover_bytes": cover_bytes,
        "cover_mime": cover_mime,
    }
    return Document(path=path, doc_type="epub", pages=pages, metadata=meta)
