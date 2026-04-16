"""EPUB loader + QTextBrowser reader: regression for page index 10 and font sizing."""

from __future__ import annotations

from pathlib import Path

import pytest
from ebooklib import epub

from projectwhy.core.epub import load_epub_document
from projectwhy.gui.text_view import TextDocView


def _write_eleven_chapter_epub(path: Path) -> None:
    """Spine-only EPUB: ``pages[10]`` is the last chapter with a unique marker (no nav in spine)."""
    book = epub.EpubBook()
    book.set_identifier("pytest-eleven-chapters")
    book.set_title("Eleven Chapters")
    book.set_language("en")
    chapters: list[epub.EpubHtml] = []
    for i in range(11):
        ch = epub.EpubHtml(title=f"Ch{i}", file_name=f"text/ch{i}.xhtml", lang="en")
        if i == 10:
            body = "<p>UNIQUE_PAGE_TEN_MARKER and <em>emphasis</em>.</p>"
        else:
            body = f"<p>Chapter {i} filler.</p>"
        ch.content = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>c{i}</title></head><body>{body}</body></html>"
        ).encode("utf-8")
        book.add_item(ch)
        chapters.append(ch)
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [c.get_id() for c in chapters]
    epub.write_epub(str(path), book)


@pytest.fixture
def eleven_chapter_epub_path(tmp_path: Path) -> Path:
    path = tmp_path / "eleven.epub"
    _write_eleven_chapter_epub(path)
    return path


def test_epub_page_ten_marker_and_blocks(eleven_chapter_epub_path: Path) -> None:
    doc = load_epub_document(str(eleven_chapter_epub_path))
    assert len(doc.pages) == 11
    p10 = doc.pages[10]
    assert "UNIQUE_PAGE_TEN_MARKER" in (p10.raw_text or "")
    assert p10.blocks
    assert any("UNIQUE_PAGE_TEN_MARKER" in b.text for b in p10.blocks)
    assert p10.html is not None
    assert "UNIQUE_PAGE_TEN_MARKER" in p10.html


def test_epub_text_view_page_ten_font_pixels_and_highlight(qtbot, eleven_chapter_epub_path: Path) -> None:
    doc = load_epub_document(str(eleven_chapter_epub_path))
    p10 = doc.pages[10]

    view = TextDocView()
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)

    font_px = 22
    view.set_font_size(font_px)
    view.set_document_text(p10.raw_text or "", p10.blocks, p10.html)

    assert view._browser.document().defaultFont().pixelSize() == font_px
    assert view._browser.font().pixelSize() == font_px

    assert view._block_spans
    assert len(view._block_spans) == len(p10.blocks)

    block0 = p10.blocks[0]
    view.highlight_word_in_block(block0, 0, block_index=0, scroll_into_view=False)
    extras = view._browser.extraSelections()
    assert len(extras) == 1
    sel = extras[0].cursor.selectedText()
    assert sel, "word highlight should select non-empty text"
