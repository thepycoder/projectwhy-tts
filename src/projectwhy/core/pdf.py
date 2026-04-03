"""PDF rendering and word geometry with pypdfium2."""

from __future__ import annotations

import pypdfium2 as pdfium
from PIL import Image

from projectwhy.core.models import BBox, WordPosition

# pypdfium2 uses this as a placeholder where a PDF line-break splits a word (e.g. hyphenation).
_PDF_LINE_BREAK_MARKER = "\ufffe"
# Marks a word half that continues on the next line; stripped / merged in layout._rejoin_hyphenated.
_SOFT_HYPHEN_CONT = "\u00ad"


def open_pdf(path: str) -> pdfium.PdfDocument:
    return pdfium.PdfDocument(path)


def render_page(page: pdfium.PdfPage, scale: float) -> Image.Image:
    bitmap = page.render(scale=scale)
    return bitmap.to_pil()


def _pdf_to_image_xy(
    left: float,
    bottom: float,
    right: float,
    top: float,
    page_w: float,
    page_h: float,
    img_w: int,
    img_h: int,
) -> tuple[float, float, float, float]:
    sx = img_w / page_w
    sy = img_h / page_h
    x1 = left * sx
    x2 = right * sx
    # PDF origin bottom-left; image origin top-left
    y_top_img = img_h - (top * sy)
    y_bot_img = img_h - (bottom * sy)
    y1 = min(y_top_img, y_bot_img)
    y2 = max(y_top_img, y_bot_img)
    return x1, y1, x2, y2


def extract_words(page: pdfium.PdfPage, scale: float) -> tuple[Image.Image, list[WordPosition]]:
    pil = render_page(page, scale)
    img_w, img_h = pil.size
    page_w = float(page.get_width())
    page_h = float(page.get_height())

    textpage = page.get_textpage()
    n = textpage.count_chars()
    current_chars: list[tuple[str, tuple[float, float, float, float]]] = []

    def flush_word(*, line_break: bool = False) -> WordPosition | None:
        if not current_chars:
            return None
        texts = [c[0] for c in current_chars]
        boxes = [c[1] for c in current_chars]
        word_text = "".join(texts).strip()
        if not word_text:
            current_chars.clear()
            return None
        if line_break:
            word_text += _SOFT_HYPHEN_CONT
        x1 = min(b[0] for b in boxes)
        y1 = min(b[1] for b in boxes)
        x2 = max(b[2] for b in boxes)
        y2 = max(b[3] for b in boxes)
        current_chars.clear()
        return WordPosition(text=word_text, bbox=BBox(x1, y1, x2, y2))

    words: list[WordPosition] = []
    for i in range(n):
        ch = textpage.get_text_range(i, 1)
        left, bottom, right, top = textpage.get_charbox(i)
        xi1, yi1, xi2, yi2 = _pdf_to_image_xy(left, bottom, right, top, page_w, page_h, img_w, img_h)

        if ch.isspace():
            w = flush_word()
            if w is not None:
                words.append(w)
            continue

        if ch == _PDF_LINE_BREAK_MARKER:
            w = flush_word(line_break=True)
            if w is not None:
                words.append(w)
            continue

        current_chars.append((ch, (xi1, yi1, xi2, yi2)))

    w = flush_word()
    if w is not None:
        words.append(w)

    textpage.close()
    return pil, words


def page_count(doc: pdfium.PdfDocument) -> int:
    return len(doc)
