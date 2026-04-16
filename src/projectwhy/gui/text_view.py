"""Plain / EPUB text view with QTextBrowser and word highlighting."""

from __future__ import annotations

import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QResizeEvent, QShowEvent, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QTextBrowser, QTextEdit, QWidget

from projectwhy.core.models import Block
from projectwhy.core.plain_qt import normalize_plain_with_position_map, plain_text_like_qtextbrowser

THEME_PRESETS: dict[str, dict[str, str]] = {
    "light": {"bg": "#FFFFFF", "fg": "#1A1A1A", "quote": "#555555"},
    "sepia": {"bg": "#F5F0E8", "fg": "#5B4636", "quote": "#6B5646"},
    "dark": {"bg": "#1E1E1E", "fg": "#D4D4D4", "quote": "#AAAAAA"},
}

# QTextBrowser's CSS engine does not reliably honor ``font-size: inherit``; EPUBs often
# set ``p.class { font-size: small }`` (keywords), which then ignore the body px size.
# Force reader px / line-height / a screen-friendly stack on running text under .eread-root.
_READER_BODY_FONT = (
    'system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Helvetica Neue", '
    "Arial, sans-serif"
)


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
        ff = _READER_BODY_FONT
        fs = self._font_size
        lh = self._line_height
        return f"""
            html {{
              background-color: {c["bg"]} !important;
              margin: 0;
              padding: 0;
              font-family: {ff} !important;
              font-size: {fs}px !important;
              line-height: {lh} !important;
            }}
            body {{
              margin: 0;
              padding: 40px 28px 56px;
              background-color: {c["bg"]} !important;
              color: {c["fg"]} !important;
              font-family: {ff} !important;
              font-size: {fs}px !important;
              line-height: {lh} !important;
              max-width: {self._column_max_width}px;
              margin-left: auto;
              margin-right: auto;
            }}
            body .eread-root p,
            body .eread-root li,
            body .eread-root td,
            body .eread-root th,
            body .eread-root div,
            body .eread-root span,
            body .eread-root em,
            body .eread-root strong,
            body .eread-root b,
            body .eread-root i,
            body .eread-root cite,
            body .eread-root a,
            body .eread-root small,
            body .eread-root blockquote,
            body .eread-root dd,
            body .eread-root dt,
            body .eread-root section,
            body .eread-root article,
            body .eread-root aside,
            body .eread-root address {{
              font-family: {ff} !important;
              font-size: {fs}px !important;
              line-height: {lh} !important;
            }}
            body .eread-root sub,
            body .eread-root sup {{
              font-family: {ff} !important;
              font-size: 0.75em !important;
            }}
            p {{ margin: 0.6em 0; }}
            h1, h2, h3, h4, h5, h6 {{
              font-family: {ff} !important;
              line-height: 1.25;
              margin: 0.75em 0 0.4em;
            }}
            h1 {{ font-size: 1.75em !important; }}
            h2 {{ font-size: 1.45em !important; }}
            h3 {{ font-size: 1.2em !important; }}
            ul, ol {{ margin: 0.5em 0; padding-left: 1.4em; }}
            li {{ margin: 0.2em 0; }}
            img {{ max-width: 100%; height: auto; display: block; margin: 0.5em auto; }}
            figure {{ margin: 0.5em 0; }}
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
        """Build a complete HTML document, moving any <style> blocks from body_inner into <head>.

        QTextBrowser only applies stylesheets declared in <head>; <style> elements
        inside <body> are silently ignored.  EPUB CSS is embedded in the body fragment
        by epub.py, so we hoist it here before ``setHtml``.

        Hoisted EPUB styles come first; the app stylesheet is last so reader font size,
        line height, and theme colors (via ``!important``) win over publisher rules.
        """
        css = self._document_css()
        extra_styles: list[str] = []

        def _hoist(m: re.Match) -> str:
            extra_styles.append(m.group(0))
            return ""

        clean_body = re.sub(
            r"<style[^>]*>.*?</style>", _hoist, body_inner, flags=re.DOTALL | re.IGNORECASE
        )
        head_extra = "\n".join(extra_styles)
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            f"{head_extra}<style>{css}</style></head><body>{clean_body}</body></html>"
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
        # QTextBrowser's CSS subset often leaves body text sized from QTextDocument.defaultFont()
        # while some headline rules still apply from CSS. Sync default/widget font to reader size.
        doc = self._browser.document()
        base = QFont()
        base.setStyleHint(QFont.StyleHint.SansSerif)
        base.setPixelSize(max(1, int(self._font_size)))
        doc.setDefaultFont(base)
        self._browser.setFont(base)
        vw = self._browser.viewport().width()
        if vw > 0:
            doc.setTextWidth(vw)
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
        if self._same_epub_page_content(text, blocks, html_fragment):
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
        if self._fragment_html is not None or self._raw_plain:
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

    def _scroll_cursor_to_viewport_ratio(self, cursor: QTextCursor, ratio_from_top: float) -> None:
        """Scroll so *cursor* sits near ``ratio_from_top`` of the viewport height."""
        sb = self._browser.verticalScrollBar()
        if sb is None:
            return
        ratio = max(0.0, min(1.0, float(ratio_from_top)))
        rect = self._browser.cursorRect(cursor)
        viewport_h = self._browser.viewport().height()
        doc_y = sb.value() + rect.top()
        target = int(doc_y - (viewport_h * ratio))
        sb.setValue(max(0, min(target, sb.maximum())))

    def _set_highlight_extra(self, selection: QTextCursor) -> None:
        """Draw highlight without touching document char formats.

        Applying ``setCharFormat`` across the whole ``QTextDocument`` replaces
        stylesheet-derived typography (and can break rich content).  Extra
        selections paint on top and leave EPUB/CSS + images intact.
        """
        extra = QTextEdit.ExtraSelection()
        extra.cursor = selection
        extra.format = self._fmt
        self._browser.setExtraSelections([extra])

    def highlight_word_in_block(
        self,
        block: Block | None,
        word_index: int | None,
        *,
        block_index: int | None = None,
        scroll_into_view: bool = False,
    ) -> None:
        if block is None:
            if block_index is not None and 0 <= block_index < len(self._blocks):
                block = self._blocks[block_index]
            else:
                self._browser.setExtraSelections([])
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
            self._browser.setExtraSelections([])
            return

        block_start, block_end = span
        hcur = QTextCursor(self._browser.document())

        if word_index is None:
            hcur.setPosition(block_start)
            hcur.setPosition(block_end, QTextCursor.MoveMode.KeepAnchor)
            self._set_highlight_extra(hcur)
            if scroll_into_view:
                scroll_cur = QTextCursor(self._browser.document())
                scroll_cur.setPosition(block_start)
                self._scroll_cursor_to_viewport_ratio(scroll_cur, 0.25)
            return

        if word_index >= len(block.words):
            self._browser.setExtraSelections([])
            return

        word = block.words[word_index]
        needle = word.text
        if not needle:
            self._browser.setExtraSelections([])
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
        self._set_highlight_extra(hcur)
        if scroll_into_view:
            scroll_cur = QTextCursor(self._browser.document())
            scroll_cur.setPosition(found_at)
            self._scroll_cursor_to_viewport_ratio(scroll_cur, 0.25)
