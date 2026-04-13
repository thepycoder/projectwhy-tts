"""Config save writes [pdf_text] markers as TOML \\u escapes (not raw UTF-8)."""

from __future__ import annotations

from pathlib import Path

from projectwhy.config import load, save


def test_save_pdf_text_uses_unicode_escapes_in_toml(tmp_path: Path) -> None:
    src = Path(__file__).resolve().parents[1] / "config.example.toml"
    cfg = load(src)
    out = tmp_path / "out.toml"
    save(out, cfg)
    text = out.read_text(encoding="utf-8")
    assert r'line_break_marker = "\ufffe"' in text
    assert r'soft_hyphen_continuation = "\u00ad"' in text
    again = load(out)
    assert again.pdf_text.line_break_marker == "\ufffe"
    assert again.pdf_text.soft_hyphen_continuation == "\u00ad"
