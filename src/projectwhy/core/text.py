"""Plain text / markdown as a single faux page."""

from __future__ import annotations

from pathlib import Path

from projectwhy.core.models import Block, BlockType, BBox, Document, Page, WordPosition


def load_plain_document(path: str) -> Document:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    paragraphs = [p.strip() for p in raw.split("\n\n") if p.strip()]
    blocks: list[Block] = []
    y = 0.0
    for p in paragraphs:
        h = 16.0
        blocks.append(
            Block(
                block_type=BlockType.TEXT,
                text=p,
                bbox=BBox(0, y, 800, y + h),
                words=[WordPosition(text=w, bbox=BBox(0, y, 800, y + h)) for w in p.split()],
            )
        )
        y += h + 8
    if not blocks:
        blocks.append(
            Block(
                block_type=BlockType.TEXT,
                text=raw,
                bbox=BBox(0, 0, 800, 400),
                words=[WordPosition(text=w, bbox=BBox(0, 0, 800, 400)) for w in raw.split()],
            )
        )
    page = Page(index=0, blocks=blocks, image=None, raw_text=raw)
    return Document(path=path, doc_type="text", pages=[page], metadata={"title": Path(path).stem})
