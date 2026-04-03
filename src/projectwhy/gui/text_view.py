"""Plain / EPUB text view with QTextBrowser and word highlighting."""

from __future__ import annotations

from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import QTextBrowser

from projectwhy.core.models import Block


class TextDocView(QTextBrowser):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fmt = QTextCharFormat()
        self._fmt.setBackground(QColor(255, 200, 0, 120))
        self._blocks: list[Block] = []
        self._plain: str = ""

    def set_highlight_color(self, rgba: tuple[int, int, int, int]) -> None:
        self._fmt.setBackground(QColor(*rgba))

    def set_document_text(self, text: str, blocks: list[Block]) -> None:
        self._blocks = blocks
        self._plain = text
        self.setPlainText(text)
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def highlight_word_in_block(self, block: Block | None, word_index: int | None) -> None:
        cur = QTextCursor(self.document())
        cur.select(QTextCursor.SelectionType.Document)
        cur.setCharFormat(QTextCharFormat())
        cur.clearSelection()

        if block is None or word_index is None or word_index >= len(block.words):
            return

        word = block.words[word_index]
        needle = word.text
        if not needle:
            return

        hcur = QTextCursor(self.document())
        from_pos = 0
        found_at = -1
        for i, b in enumerate(self._blocks):
            if b is block:
                chunk_start = from_pos
                local = b.text.find(needle)
                if local >= 0:
                    found_at = chunk_start + local
                break
            from_pos += len(b.text) + 2
        if found_at < 0:
            # Fallback: search in full document
            found_at = self._plain.find(needle)

        if found_at < 0:
            return

        hcur.setPosition(found_at)
        hcur.setPosition(found_at + len(needle), QTextCursor.MoveMode.KeepAnchor)
        hcur.mergeCharFormat(self._fmt)
