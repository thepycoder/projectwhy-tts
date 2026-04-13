"""PDF word-extraction: line-break marker and hyphen-continuation character."""

from __future__ import annotations

from PyQt6.QtWidgets import QFormLayout, QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget

from projectwhy.config import AppConfig, PdfTextConfig


def _first_char(s: str) -> str:
    return (s or "")[:1]


def _hex_from_char(ch: str) -> str:
    if not ch:
        return ""
    return f"{ord(ch[0]):04X}"


def _parse_hex_codepoint(s: str) -> str | None:
    """Return one-character string, '' if empty (disabled), or None if invalid."""
    t = s.strip().upper().replace("U+", "").replace("0X", "")
    if not t:
        return ""
    try:
        n = int(t, 16)
    except ValueError:
        return None
    if n < 0 or n > 0x10FFFF or 0xD800 <= n <= 0xDFFF:
        return None
    return chr(n)


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
            "Enter each as a hexadecimal code point (e.g. FFFE and 00AD). Qt line edits cannot "
            "hold U+FFFE, so we never store the raw character in the field. Leave a field empty "
            "only to disable that step. Reload the document after changes."
        )
        intro.setWordWrap(True)
        outer.addWidget(intro)

        group = QGroupBox("Code points (hex, e.g. FFFE — optional U+ prefix)")
        form = QFormLayout(group)

        self._line_break = QLineEdit()
        self._line_break.setPlaceholderText("FFFE (default line-break marker)")
        self._line_break.setToolTip(
            "pypdfium2 puts this character in the char stream where a line break broke a word. "
            "Must match what your PDF engine emits (project default U+FFFE)."
        )
        self._line_break_desc = QLabel()
        self._line_break.textChanged.connect(lambda _: self._refresh_desc())
        form.addRow("Line-break marker:", self._line_break)
        form.addRow("Detected as:", self._line_break_desc)

        self._soft_hyphen = QLineEdit()
        self._soft_hyphen.setPlaceholderText("00AD (default soft hyphen)")
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
        lb = _parse_hex_codepoint(self._line_break.text())
        sh = _parse_hex_codepoint(self._soft_hyphen.text())
        self._line_break_desc.setText(
            "(invalid hex)" if lb is None else _char_desc(lb),
        )
        self._soft_hyphen_desc.setText(
            "(invalid hex)" if sh is None else _char_desc(sh),
        )

    def page_title(self) -> str:
        return "PDF text"

    def widget(self) -> QWidget:
        return self._root

    def load_from_config(self, cfg: AppConfig) -> None:
        self._line_break.setText(_hex_from_char(_first_char(cfg.pdf_text.line_break_marker)))
        self._soft_hyphen.setText(_hex_from_char(_first_char(cfg.pdf_text.soft_hyphen_continuation)))
        self._refresh_desc()

    def apply_to_config(self, cfg: AppConfig) -> str | None:
        lb = _parse_hex_codepoint(self._line_break.text())
        sh = _parse_hex_codepoint(self._soft_hyphen.text())
        if lb is None:
            return "Line-break marker: enter a valid hex code point (e.g. FFFE) or leave empty."
        if sh is None:
            return "Hyphen continuation: enter a valid hex code point (e.g. 00AD) or leave empty."
        cfg.pdf_text = PdfTextConfig(
            line_break_marker=lb,
            soft_hyphen_continuation=sh,
        )
        return None
