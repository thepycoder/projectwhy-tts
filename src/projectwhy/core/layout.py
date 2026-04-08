"""PP-DocLayout (PaddleOCR LayoutDetection) integration."""

from __future__ import annotations

import numpy as np
from PIL import Image

from projectwhy.core.models import Block, BlockType, BBox, WordPosition
from projectwhy.core.reading_order import sort_blocks_reading_order

try:
    from paddleocr import LayoutDetection
except ImportError:  # pragma: no cover
    LayoutDetection = None  # type: ignore[misc, assignment]


def load_layout_model(
    model_name: str = "PP-DocLayout-M",
    model_dir: str | None = None,
    threshold: float = 0.25,
    device: str | None = None,
    *,
    layout_nms: bool = True,
    enable_mkldnn: bool = False,
):
    """Load a PP-DocLayout-S / M / L (or compatible) layout detector."""
    if LayoutDetection is None:
        raise RuntimeError("paddleocr is not installed")
    kwargs: dict = {
        "model_name": model_name,
        "threshold": threshold,
        "layout_nms": layout_nms,
        "enable_mkldnn": enable_mkldnn,
    }
    md = (model_dir or "").strip() or None
    if md is not None:
        kwargs["model_dir"] = md
    if device is not None and device.strip():
        kwargs["device"] = device.strip()
    return LayoutDetection(**kwargs)


def analyze_layout(
    image: Image.Image,
    model,
) -> list[Block]:
    """Run layout detection; return blocks with PP-native types and bboxes (no text/words)."""
    arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
    raw = model.predict(arr)
    if not raw:
        return []

    res = raw[0]
    boxes = res["boxes"]
    if not boxes:
        return []

    blocks: list[Block] = []
    for box in boxes:
        label = str(box.get("label", ""))
        coord = box.get("coordinate")
        if not coord or len(coord) < 4:
            continue
        c = [float(x) for x in coord]
        if len(c) == 4:
            x1, y1, x2, y2 = c[0], c[1], c[2], c[3]
        elif len(c) == 8:
            xs, ys = c[0::2], c[1::2]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
        else:
            continue
        blocks.append(
            Block(
                block_type=BlockType.from_pp_label(label),
                text="",
                bbox=BBox(x1, y1, x2, y2),
            )
        )
    return blocks


def _sort_words_into_lines(words: list) -> list:
    """Group *words* into visual lines by Y proximity, then sort left-to-right
    within each line and top-to-bottom across lines.

    Adaptive tolerance: half the median word height so that words on the same
    baseline cluster together even when individual Y values jitter slightly.
    """
    if not words:
        return []

    heights = [abs(w.bbox.y2 - w.bbox.y1) for w in words]
    heights.sort()
    median_h = heights[len(heights) // 2] if heights else 0
    tolerance = max(median_h * 0.5, 2.0)

    by_top = sorted(words, key=lambda w: min(w.bbox.y1, w.bbox.y2))

    lines: list[list] = []
    current_line: list = [by_top[0]]
    current_y = min(by_top[0].bbox.y1, by_top[0].bbox.y2)

    for w in by_top[1:]:
        top = min(w.bbox.y1, w.bbox.y2)
        if abs(top - current_y) <= tolerance:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
            current_y = top
    lines.append(current_line)

    result: list = []
    for line in lines:
        line.sort(key=lambda w: w.bbox.x1)
        result.extend(line)
    return result


def _rejoin_hyphenated(words: list, continuation: str) -> list:
    """Merge word pairs marked with trailing *continuation* (line-break split from PDF)."""
    if not words or not continuation:
        return list(words)
    result: list = []
    i = 0
    while i < len(words):
        w = words[i]
        if w.text.endswith(continuation) and i + 1 < len(words):
            nxt = words[i + 1]
            merged_text = w.text.removesuffix(continuation) + nxt.text
            result.append(WordPosition(text=merged_text, bbox=nxt.bbox))
            i += 2
        else:
            if w.text.endswith(continuation):
                result.append(WordPosition(text=w.text.removesuffix(continuation), bbox=w.bbox))
            else:
                result.append(w)
            i += 1
    return result


def assign_words_to_blocks(blocks: list[Block], words: list, *, soft_hyphen_continuation: str) -> None:
    """Mutate blocks: set words list and combined text."""
    for b in blocks:
        b.words = []
    unassigned: list = []

    for w in words:
        cx = (w.bbox.x1 + w.bbox.x2) / 2
        cy = (w.bbox.y1 + w.bbox.y2) / 2
        chosen = None
        for b in blocks:
            bb = b.bbox
            if bb.x1 <= cx <= bb.x2 and bb.y1 <= cy <= bb.y2:
                chosen = b
                break
        if chosen is None:
            unassigned.append(w)
        else:
            chosen.words.append(w)

    if unassigned and blocks:
        for w in unassigned:
            cx = (w.bbox.x1 + w.bbox.x2) / 2
            cy = (w.bbox.y1 + w.bbox.y2) / 2

            def dist2(b: Block) -> float:
                mx = (b.bbox.x1 + b.bbox.x2) / 2
                my = (b.bbox.y1 + b.bbox.y2) / 2
                return (mx - cx) ** 2 + (my - cy) ** 2

            nearest = min(blocks, key=dist2)
            nearest.words.append(w)

    for b in blocks:
        b.words = _rejoin_hyphenated(_sort_words_into_lines(b.words), soft_hyphen_continuation)
        b.text = " ".join(w.text for w in b.words).strip()


def layout_and_assign_words(
    image: Image.Image,
    words: list,
    model,
    page_w: int,
    page_h: int,
    *,
    soft_hyphen_continuation: str = "\u00ad",
) -> list[Block]:
    blocks = analyze_layout(image, model)
    if not blocks:
        one = Block(
            block_type=BlockType.TEXT,
            text="",
            bbox=BBox(0, 0, float(page_w), float(page_h)),
        )
        blocks = [one]
    assign_words_to_blocks(blocks, words, soft_hyphen_continuation=soft_hyphen_continuation)
    blocks = [b for b in blocks if b.text.strip()]
    if not blocks:
        blocks = [
            Block(
                block_type=BlockType.TEXT,
                text="",
                bbox=BBox(0, 0, float(page_w), float(page_h)),
                words=[],
            )
        ]
    blocks = sort_blocks_reading_order(blocks, float(page_w), float(page_h))
    if not any(b.text.strip() for b in blocks) and words:
        words_sorted = _rejoin_hyphenated(
            _sort_words_into_lines(words),
            soft_hyphen_continuation,
        )
        merged_text = " ".join(w.text for w in words_sorted)
        blocks = [
            Block(
                block_type=BlockType.TEXT,
                text=merged_text,
                bbox=BBox(0, 0, float(page_w), float(page_h)),
                words=words_sorted,
            )
        ]
    return blocks
