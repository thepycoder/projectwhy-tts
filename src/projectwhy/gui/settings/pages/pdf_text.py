"""PDF word-extraction: line-break marker and hyphen-continuation character."""

from __future__ import annotations

from PyQt6.QtWidgets import QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from projectwhy.config import AppConfig, PdfTextConfig


def _first_char(s: str) -> str:
    return (s or "")[:1]


def _char_desc(ch: str) -> str:
    if not ch:
        return "(empty — this half is disabled; line-break rejoin needs both set)"
    o = ord(ch)
    name = "OBJECT REPLACEMENT" if o == 0xFFFE else "SOFT HYPHEN" if o == 0x00AD else ""
    suffix = f" ({name})" if name else ""
    return f"U+{o:04X}{suffix}"


class PdfTextSettingsPage:
    def __init__(self) -> None:
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(8, 8, 8, 8)

        intro = QLabel(
            "These two characters work together when a PDF line break splits a hyphenated word "
            '(e.g. "exam-" at end of one line and "ple" at the start of the next).\n\n'
            "• Line-break marker — pypdfium2 inserts this one placeholder character in the "
            "extracted text exactly where the engine split the word across lines (default "
            "U+FFFE, not a character / private-use in Unicode). We end the current word when we see it.\n\n"
            "• Hyphen continuation — we append this character to that first fragment (default "
            "U+00AD, soft hyphen). During layout, a word ending with it is merged with the next "
            "word so TTS speaks a single word and order stays correct.\n\n"
            "Defaults: U+FFFE + U+00AD. Fields are invisible in most fonts; check the U+ line "
            "under each box. Leave a field empty only to disable that step (empty line-break "
            "marker ⇒ splits are not detected; empty continuation ⇒ fragments are never rejoined). "
            "Reload the document after changes."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        group = QGroupBox("Characters (only the first character in each field is used)")
        form = QFormLayout(group)

        self._line_break = QLineEdit()
        self._line_break.setPlaceholderText("Default: paste U+FFFE or leave as loaded from config")
        self._line_break.setToolTip(
            "pypdfium2 puts this character in the char stream where a line break broke a word. "
            "Must match what your PDF engine emits (project default U+FFFE)."
        )
        self._line_break_desc = QLabel()
        self._line_break.textChanged.connect(lambda _: self._refresh_desc())
        form.addRow("Line-break marker:", self._line_break)
        form.addRow("Detected as:", self._line_break_desc)

        self._soft_hyphen = QLineEdit()
        self._soft_hyphen.setPlaceholderText("Default: paste U+00AD (soft hyphen) or use loaded config")
        self._soft_hyphen.setToolTip(
            "Appended to the word fragment before the line-break marker so we can find "
            "“…fragment\u00ad” + “rest…” and merge into one token for TTS (default U+00AD)."
        )
        self._soft_hyphen_desc = QLabel()
        self._soft_hyphen.textChanged.connect(lambda _: self._refresh_desc())
        form.addRow("Hyphen continuation:", self._soft_hyphen)
        form.addRow("Detected as:", self._soft_hyphen_desc)

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
