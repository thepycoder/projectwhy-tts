"""Load documents and build typed pages."""

from __future__ import annotations

import logging
from pathlib import Path

import pypdfium2 as pdfium

from projectwhy.core.epub import load_epub_document
from projectwhy.core.layout import layout_and_assign_words
from projectwhy.core.models import Document, Page
from projectwhy.core.pdf import extract_words, open_pdf
from projectwhy.core.text import load_plain_document

logger = logging.getLogger(__name__)


def _skeleton_pdf_pages(path: str, n: int) -> Document:
    meta = {"title": Path(path).stem}
    pages = [Page(index=i, blocks=[], image=None, raw_text=None) for i in range(n)]
    return Document(path=path, doc_type="pdf", pages=pages, metadata=meta)


def ensure_pdf_page_loaded(
    doc: Document,
    page_index: int,
    pdf: pdfium.PdfDocument,
    layout_model,
    pdf_scale: float,
) -> Page:
    if page_index < 0 or page_index >= len(doc.pages):
        raise IndexError("page_index out of range")
    page = doc.pages[page_index]
    if page.blocks and page.image is not None:
        return page

    p = pdf[page_index]
    try:
        pil, words = extract_words(p, pdf_scale)
        w, h = pil.size
        blocks = layout_and_assign_words(pil, words, layout_model, w, h)
        page.image = pil
        page.blocks = blocks
    finally:
        p.close()

    return page


def ensure_pdf_neighbor_pages_loaded(
    doc: Document,
    center_index: int,
    pdf: pdfium.PdfDocument,
    layout_model,
    pdf_scale: float,
) -> None:
    """Prefetch current, previous, and next PDF pages (lazy layout + text)."""
    for delta in (-1, 0, 1):
        i = center_index + delta
        if 0 <= i < len(doc.pages):
            ensure_pdf_page_loaded(doc, i, pdf, layout_model, pdf_scale)


def open_pdf_document(path: str) -> tuple[Document, pdfium.PdfDocument]:
    pdf = open_pdf(path)
    n = len(pdf)
    doc = _skeleton_pdf_pages(path, n)
    return doc, pdf


def load_document(path: str) -> tuple[Document, pdfium.PdfDocument | None]:
    suf = Path(path).suffix.lower()
    if suf == ".pdf":
        return open_pdf_document(path)
    if suf == ".epub":
        return load_epub_document(path), None
    return load_plain_document(path), None


def close_document_resources(doc: Document, pdf: pdfium.PdfDocument | None) -> None:
    if pdf is not None:
        try:
            pdf.close()
        except Exception as e:  # pragma: no cover
            logger.debug("pdf close: %s", e)
