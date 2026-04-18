"""Regression: plain-text normalization matches QTextBrowser quirks."""

from projectwhy.core.plain_qt import plain_text_like_qtextbrowser


def test_typographic_quote_space_matches_qtextdocument_plain_text() -> None:
    """Qt drops the space after an opening curly quote in toPlainText(); BS often keeps it."""
    assert plain_text_like_qtextbrowser('He said “ Singapore') == 'He said “Singapore'
    assert plain_text_like_qtextbrowser('He said ‘ Singapore') == 'He said ‘Singapore'
