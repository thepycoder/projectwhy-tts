"""PDF word-extraction: line-break marker and hyphen-continuation character."""

from __future__ import annotations

from PyQt6.QtWidgets import QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from projectwhy.config import AppConfig, PdfTextConfig


def _first_char(s: str) -> str:
    return (s or "")[:1]


def _char_desc(ch: str) -> str:
    if not ch:
        return "(empty — disabled)"
    o = ord(ch)
    return f"U+{o:04X}"


class PdfTextSettingsPage:
    def __init__(self) -> None:
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "pypdfium2 emits a placeholder where a PDF line break splits a word, and can mark "
            "a hyphenation continuation. "
            "Reload the document after changing these. "
            "Leave a field empty to disable that behavior."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        group = QGroupBox("Markers (first character of each field is used)")
        form = QFormLayout(group)

        self._line_break = QLineEdit()
        self._line_break.setToolTip(
            "When this character appears in PDF text extraction, the current word is flushed "
            "and marked for optional merge with the next line (see hyphen continuation). "
            "Default U+FFFE."
        )
        self._line_break_desc = QLabel()
        self._line_break.textChanged.connect(lambda _: self._refresh_desc())
        form.addRow("Line-break marker:", self._line_break)
        form.addRow("", self._line_break_desc)

        self._soft_hyphen = QLineEdit()
        self._soft_hyphen.setToolTip(
            "Appended to a word split by a line-break marker so the next word can be merged "
            "for TTS. Default U+00AD (soft hyphen)."
        )
        self._soft_hyphen_desc = QLabel()
        self._soft_hyphen.textChanged.connect(lambda _: self._refresh_desc())
        form.addRow("Hyphen continuation:", self._soft_hyphen)
        form.addRow("", self._soft_hyphen_desc)

        outer.addWidget(group)
        outer.addStretch(1)

    def _refresh_desc(self) -> None:
        self._line_break_desc.setText(_char_desc(_first_char(self._line_break.text())))
        self._soft_hyphen_desc.setText(_char_desc(_first_char(self._soft_hyphen.text())))

    def page_title(self) -> str:
        return "PDF text"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        self._line_break.setText(cfg.pdf_text.line_break_marker)
        self._soft_hyphen.setText(cfg.pdf_text.soft_hyphen_continuation)
        self._refresh_desc()

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        cfg.pdf_text = PdfTextConfig(
            line_break_marker=_first_char(self._line_break.text()),
            soft_hyphen_continuation=_first_char(self._soft_hyphen.text()),
        )
        return None
