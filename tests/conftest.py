"""Pytest fixtures: layout model (session) and PDF page → blocks."""

from __future__ import annotations

from pathlib import Path

import pytest

from projectwhy.config import load_config
from projectwhy.core.layout import layout_and_assign_words, load_layout_model
from projectwhy.core.pdf import extract_words, open_pdf

FIXTURES_PDF_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


@pytest.fixture(scope="session")
def layout_model():
    cfg = load_config()
    return load_layout_model(
        model_name=cfg.layout.model_name,
        model_dir=cfg.layout.model_dir or None,
        threshold=cfg.layout.confidence,
        device=cfg.layout.device,
        layout_nms=cfg.layout.layout_nms,
        enable_mkldnn=cfg.layout.enable_mkldnn,
    )


@pytest.fixture
def pdf_scale():
    return load_config().display.pdf_scale


@pytest.fixture
def load_page(layout_model, pdf_scale):
    """Return ``(filename, page_index=0) -> list[Block]`` for files under fixtures/pdfs/."""

    def _load(filename: str, page_index: int = 0):
        pdf_path = FIXTURES_PDF_DIR / filename
        if not pdf_path.is_file():
            raise FileNotFoundError(f"Fixture PDF not found: {pdf_path}")
        doc = open_pdf(str(pdf_path))
        page = doc[page_index]
        try:
            pil, words = extract_words(page, pdf_scale)
            w, h = pil.size
            return layout_and_assign_words(pil, words, layout_model, w, h)
        finally:
            page.close()
            doc.close()

    return _load
