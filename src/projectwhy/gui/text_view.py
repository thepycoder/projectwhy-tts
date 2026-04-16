"""Plain / EPUB text view with QTextBrowser and word highlighting."""

from __future__ import annotations

import html

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QResizeEvent, QShowEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QTextBrowser, QWidget

from projectwhy.core.models import Block
from projectwhy.core.plain_qt import normalize_plain_with_position_map, plain_text_like_qtextbrowser

THEME_PRESETS: dict[str, dict[str, str]] = {
    "light": {"bg": "#FFFFFF", "fg": "#1A1A1A", "quote": "#555555"},
    "sepia": {"bg": "#F5F0E8", "fg": "#5B4636", "quote": "#6B5646"},
    "dark": {"bg": "#1E1E1E", "fg": "#D4D4D4", "quote": "#AAAAAA"},
}


class TextDocView(QWidget):
    """Centered reading column with theme + HTML or plain text."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._theme = "light"
        self._font_size = 17
        self._line_height = 1.6
        self._column_max_width = 1000
        self._blocks: list[Block] = []
        self._raw_plain = ""
        self._fragment_html: str | None = None
        self._block_spans: list[tuple[int, int]] = []
        self._fmt = QTextCharFormat()
        self._fmt.setBackground(QColor(255, 200, 0, 120))

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(True)
        self._browser.setFrameShape(QFrame.Shape.NoFrame)
        self._browser.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self._browser, 0)
        outer.addStretch(1)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        super().resizeEvent(event)
        self._sync_browser_geometry()

    def showEvent(self, event: QShowEvent | None) -> None:
        super().showEvent(event)
        self._sync_browser_geometry()

    def set_highlight_color(self, rgba: list[int] | tuple[int, int, int, int]) -> None:
        self._fmt.setBackground(QColor(*rgba))

    def set_theme(self, theme: str) -> None:
        t = theme.strip().lower()
        self._theme = t if t in THEME_PRESETS else "light"
        self._reload_document_preserve_scroll()

    def set_font_size(self, size: int) -> None:
        self._font_size = max(12, min(28, int(size)))
        self._reload_document_preserve_scroll()

    def set_line_height(self, lh: float) -> None:
        self._line_height = max(1.2, min(2.0, float(lh)))
        self._reload_document_preserve_scroll()

    def apply_reader_settings(
        self,
        theme: str,
        font_size: int,
        line_height: float,
        column_max_width: int,
    ) -> None:
        self._theme = theme.strip().lower() if theme.strip().lower() in THEME_PRESETS else "light"
        self._font_size = max(12, min(28, int(font_size)))
        self._line_height = max(1.2, min(2.0, float(line_height)))
        self._column_max_width = max(520, min(1400, int(column_max_width)))
        self._reload_document_preserve_scroll()

    def _sync_browser_geometry(self) -> None:
        """QHBoxLayout keeps QTextBrowser at a tiny size hint unless we set an explicit width.

        Also drive QTextDocument layout width so wrapping matches the visible column.
        """
        pad = 24
        desired = self._column_max_width + 72
        inner = self.width() - 2 * pad
        if inner <= 0:
            target = desired
        else:
            target = min(desired, inner)
        target = max(200, int(target))
        self._browser.setFixedWidth(target)
        doc = self._browser.document()
        vw = self._browser.viewport().width()
        if vw > 0:
            doc.setTextWidth(vw)

    def _colors(self) -> dict[str, str]:
        return THEME_PRESETS.get(self._theme, THEME_PRESETS["light"])

    def _document_css(self) -> str:
        c = self._colors()
        return f"""
            html {{
              background-color: {c["bg"]};
              margin: 0;
              padding: 0;
            }}
            body {{
              margin: 0;
              padding: 40px 28px 56px;
              background-color: {c["bg"]};
              color: {c["fg"]};
              font-family: Georgia, 'Noto Serif', 'Times New Roman', serif;
              font-size: {self._font_size}px;
              line-height: {self._line_height};
              max-width: {self._column_max_width}px;
              margin-left: auto;
              margin-right: auto;
            }}
            p {{ margin: 0.6em 0; }}
            h1, h2, h3, h4, h5, h6 {{
              font-family: Georgia, 'Noto Serif', serif;
              line-height: 1.25;
              margin: 0.75em 0 0.4em;
            }}
            h1 {{ font-size: 1.75em; }}
            h2 {{ font-size: 1.45em; }}
            h3 {{ font-size: 1.2em; }}
            ul, ol {{ margin: 0.5em 0; padding-left: 1.4em; }}
            li {{ margin: 0.2em 0; }}
            blockquote {{
              margin: 0.8em 0;
              padding-left: 1em;
              border-left: 3px solid {c["quote"]};
              color: {c["quote"]};
            }}
            pre, code {{
              font-family: 'Consolas', 'DejaVu Sans Mono', monospace;
              font-size: 0.92em;
            }}
            a {{ color: {c["fg"]}; text-decoration: underline; }}
            .eread-root {{ max-width: {self._column_max_width}px; margin: 0 auto; }}
            .plainwrap {{
              white-space: pre-wrap;
              word-wrap: break-word;
            }}
        """

    def _full_html(self, body_inner: str) -> str:
        css = self._document_css()
        return (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            f"<style>{css}</style></head><body>{body_inner}</body></html>"
        )

    def _apply_chrome(self) -> None:
        c = self._colors()
        self.setStyleSheet(
            f"TextDocView {{ background-color: {c['bg']}; }}"
            f"QTextBrowser {{ background-color: {c['bg']}; color: {c['fg']}; border: none; }}",
        )

    def _render_document(self) -> None:
        self._sync_browser_geometry()
        self._apply_chrome()
        if self._fragment_html:
            self._browser.setHtml(self._full_html(self._fragment_html))
        else:
            esc = html.escape(self._raw_plain)
            inner = f'<div class="plainwrap">{esc}</div>'
            self._browser.setHtml(self._full_html(inner))
        vw = self._browser.viewport().width()
        if vw > 0:
            self._browser.document().setTextWidth(vw)
        self._recompute_block_starts()

    def _same_epub_page_content(
        self,
        text: str,
        blocks: list[Block],
        html_fragment: str | None,
    ) -> bool:
        if text != self._raw_plain:
            return False
        if (html_fragment or None) != (self._fragment_html or None):
            return False
        if len(blocks) != len(self._blocks):
            return False
        return all(nb.text == ob.text for nb, ob in zip(blocks, self._blocks, strict=True))

    def set_document_text(
        self,
        text: str,
        blocks: list[Block],
        html_fragment: str | None = None,
        *,
        move_cursor_start: bool = True,
    ) -> None:
        if self._blocks and self._same_epub_page_content(text, blocks, html_fragment):
            self._blocks = list(blocks)
            return
        self._blocks = blocks
        self._raw_plain = text
        self._fragment_html = html_fragment
        self._render_document()
        if move_cursor_start:
            self._browser.moveCursor(QTextCursor.MoveOperation.Start)

    def _reload_document_preserve_scroll(self) -> None:
        sb = self._browser.verticalScrollBar()
        pos = sb.value() if sb else 0
        if self._blocks:
            self._render_document()
            if sb:
                sb.setValue(min(pos, sb.maximum()))
        else:
            self._apply_chrome()

    def _recompute_block_starts(self) -> None:
        self._block_spans = []
        if not self._blocks:
            return
        plain = self._browser.toPlainText()

        norm_plain, pos_map = normalize_plain_with_position_map(plain)
        search_pos = 0
        for i, b in enumerate(self._blocks):
            norm_needle = plain_text_like_qtextbrowser(b.text)
            idx = norm_plain.find(norm_needle, search_pos)
            if idx < 0:
                self._block_spans = []
                return
            end_idx = idx + len(norm_needle) - 1
            orig_start = pos_map[idx]
            orig_end = pos_map[end_idx] + 1 if end_idx < len(pos_map) else len(plain)
            self._block_spans.append((orig_start, orig_end))
            search_pos = idx + len(norm_needle)
        if len(self._block_spans) != len(self._blocks):
            self._block_spans = []

    def highlight_word_in_block(
        self,
        block: Block | None,
        word_index: int | None,
        *,
        block_index: int | None = None,
        scroll_into_view: bool = False,
    ) -> None:
        cur = QTextCursor(self._browser.document())
        cur.select(QTextCursor.SelectionType.Document)
        cur.setCharFormat(QTextCharFormat())
        cur.clearSelection()

        if block is None:
            if block_index is not None and 0 <= block_index < len(self._blocks):
                block = self._blocks[block_index]
            else:
                return

        span: tuple[int, int] | None = None
        if (
            block_index is not None
            and self._block_spans
            and len(self._block_spans) == len(self._blocks)
            and 0 <= block_index < len(self._block_spans)
        ):
            span = self._block_spans[block_index]
        elif self._block_spans and len(self._block_spans) == len(self._blocks) and block is not None:
            for i, b in enumerate(self._blocks):
                if b is block:
                    span = self._block_spans[i]
                    break
            if span is None:
                for i, b in enumerate(self._blocks):
                    if b.text == block.text:
                        span = self._block_spans[i]
                        break

        if span is None:
            return

        block_start, block_end = span
        hcur = QTextCursor(self._browser.document())

        if word_index is None:
            hcur.setPosition(block_start)
            hcur.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
            hcur.mergeCharFormat(self._fmt)
            if scroll_into_view:
                self._browser.setTextCursor(hcur)
                self._browser.ensureCursorVisible()
            return

        if word_index >= len(block.words):
            return

        word = block.words[word_index]
        needle = word.text
        if not needle:
            return

        plain = self._browser.toPlainText()
        region = plain[block_start:block_end]
        search_from = 0
        for j in range(word_index):
            wp = region.find(block.words[j].text, search_from)
            if wp >= 0:
                search_from = wp + len(block.words[j].text)
        found_in_region = region.find(needle, search_from)
        if found_in_region < 0:
            found_in_region = search_from
        found_at = block_start + found_in_region

        hcur.setPosition(found_at)
        hcur.setPosition(found_at + len(needle), QTextCursor.MoveMode.KeepAnchor)
        hcur.mergeCharFormat(self._fmt)
        if scroll_into_view:
            self._browser.setTextCursor(hcur)
            self._browser.ensureCursorVisible()
