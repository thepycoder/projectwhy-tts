"""EPUB loader + QTextBrowser reader: regression for page index 10 and font sizing."""

from __future__ import annotations

from pathlib import Path

import pytest
from ebooklib import epub

from projectwhy.core.epub import load_epub_document
from projectwhy.gui.text_view import TextDocView

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


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


def test_epub_option_b_word_spans_match_plain(qtbot, eleven_chapter_epub_path: Path) -> None:
    doc = load_epub_document(str(eleven_chapter_epub_path))
    p10 = doc.pages[10]
    view = TextDocView()
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    view.set_document_text(p10.raw_text or "", p10.blocks, p10.html)

    assert view._word_spans
    assert len(view._word_spans) == len(p10.blocks)
    plain = view._browser.toPlainText()
    for bi, block in enumerate(p10.blocks):
        assert len(view._word_spans[bi]) == len(block.words)
        for wi, w in enumerate(block.words):
            start, end = view._word_spans[bi][wi]
            assert plain[start:end] == w.text


def test_epub_char_index_to_hit_word_mode(qtbot, eleven_chapter_epub_path: Path) -> None:
    doc = load_epub_document(str(eleven_chapter_epub_path))
    p10 = doc.pages[10]
    view = TextDocView()
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    view.set_hover_granularity("word")
    view.set_document_text(p10.raw_text or "", p10.blocks, p10.html)

    plain = view._browser.toPlainText()
    needle = "UNIQUE_PAGE_TEN_MARKER"
    idx = plain.find(needle)
    assert idx >= 0
    mid = idx + len(needle) // 2
    hit = view._char_index_to_hit(mid)
    assert hit is not None
    bi, wi = hit
    assert bi == 0
    assert p10.blocks[0].words[wi].text == needle


def test_epub_char_index_to_hit_block_mode(qtbot, eleven_chapter_epub_path: Path) -> None:
    doc = load_epub_document(str(eleven_chapter_epub_path))
    p10 = doc.pages[10]
    view = TextDocView()
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    view.set_hover_granularity("block")
    view.set_document_text(p10.raw_text or "", p10.blocks, p10.html)

    plain = view._browser.toPlainText()
    idx = plain.find("emphasis")
    assert idx >= 0
    hit = view._char_index_to_hit(idx)
    assert hit == (0, None)


def test_pg389_fixture_word_spans_when_aligned(qtbot) -> None:
    path = RESOURCES_DIR / "pg389-images-3.epub"
    if not path.is_file():
        pytest.skip(f"missing fixture {path}")
    doc = load_epub_document(str(path))
    p0 = doc.pages[0]
    view = TextDocView()
    qtbot.addWidget(view)
    view.resize(900, 700)
    view.show()
    qtbot.waitExposed(view)
    view.set_document_text(p0.raw_text or "", p0.blocks, p0.html)
    if not view._block_spans or not view._word_spans:
        pytest.skip("page 0 block/plain alignment not available for this build")
    plain = view._browser.toPlainText()
    for bi, block in enumerate(p0.blocks):
        for wi, w in enumerate(block.words):
            start, end = view._word_spans[bi][wi]
            assert plain[start:end] == w.text
