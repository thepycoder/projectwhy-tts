"""EPUB loading (one Page per spine chapter)."""

from __future__ import annotations

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

from projectwhy.core.models import Block, BlockType, BBox, Document, Page, WordPosition


def _html_to_blocks(html: str) -> list[Block]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    blocks: list[Block] = []
    y = 0.0
    for ln in lines:
        h = 16.0
        blocks.append(
            Block(
                block_type=BlockType.TEXT,
                text=ln,
                bbox=BBox(0, y, 800, y + h),
                words=[WordPosition(text=w, bbox=BBox(0, y, 800, y + h)) for w in ln.split()],
            )
        )
        y += h + 4
    return blocks


def load_epub_document(path: str) -> Document:
    book = epub.read_epub(path)
    title = book.get_metadata("DC", "title")
    name = title[0][0] if title else path
    pages: list[Page] = []
    idx = 0
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        content = item.get_content().decode("utf-8", errors="replace")
        soup = BeautifulSoup(content, "html.parser")
        blocks = _html_to_blocks(str(soup))
        if not blocks:
            continue
        joined = "\n\n".join(b.text for b in blocks)
        pages.append(Page(index=idx, blocks=blocks, image=None, raw_text=joined))
        idx += 1
    if not pages:
        pages.append(Page(index=0, blocks=[], image=None, raw_text=""))
    return Document(path=path, doc_type="epub", pages=pages, metadata={"title": name})
