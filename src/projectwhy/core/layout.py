"""DocLayout-YOLO integration."""

from __future__ import annotations

import logging

import numpy as np
from huggingface_hub import hf_hub_download
from huggingface_hub.errors import LocalEntryNotFoundError
from PIL import Image

from projectwhy.core.models import Block, BlockType, BBox
from projectwhy.core.reading_order import sort_blocks_reading_order

logger = logging.getLogger(__name__)

try:
    from doclayout_yolo import YOLOv10
except ImportError:  # pragma: no cover
    YOLOv10 = None  # type: ignore

DEFAULT_LAYOUT_REPO = "juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501"
DEFAULT_LAYOUT_FILE = "doclayout_yolo_docstructbench_imgsz1280_2501.pt"


def _label_to_block_type(name: str) -> BlockType:
    n = name.lower().strip()
    if any(k in n for k in ("title", "headline", "chapter", "section-header")):
        return BlockType.TITLE
    if "footer" in n or "page-footer" in n or "folio" in n:
        return BlockType.FOOTER
    if "header" in n or "page-header" in n:
        return BlockType.HEADER
    if n == "table":
        return BlockType.TABLE
    if "caption" in n:
        if "table" in n:
            return BlockType.TABLE_CAPTION
        return BlockType.FIGURE_CAPTION
    if any(k in n for k in ("figure", "picture", "image", "photo")):
        return BlockType.FIGURE
    if "formula" in n or "equation" in n:
        return BlockType.EQUATION
    if "reference" in n:
        return BlockType.REFERENCE
    return BlockType.TEXT


def download_default_layout_weights() -> str:
    try:
        return hf_hub_download(
            repo_id=DEFAULT_LAYOUT_REPO,
            filename=DEFAULT_LAYOUT_FILE,
            local_files_only=True,
        )
    except LocalEntryNotFoundError:
        return hf_hub_download(repo_id=DEFAULT_LAYOUT_REPO, filename=DEFAULT_LAYOUT_FILE)


def load_layout_model(weights_path: str | None = None):
    if YOLOv10 is None:
        raise RuntimeError("doclayout-yolo is not installed")
    path = (weights_path or "").strip() or None
    path = path or download_default_layout_weights()

    # PyTorch 2.6+ defaults weights_only=True; DocLayout checkpoints need full unpickle.
    import torch

    _orig_torch_load = torch.load

    def _torch_load_weights_compat(*args, **kwargs):  # noqa: ANN002, ANN003
        kwargs.setdefault("weights_only", False)
        return _orig_torch_load(*args, **kwargs)

    torch.load = _torch_load_weights_compat  # type: ignore[assignment]
    try:
        return YOLOv10(path)
    finally:
        torch.load = _orig_torch_load  # type: ignore[assignment]


def analyze_layout(
    image: Image.Image,
    model,
    conf: float = 0.25,
    imgsz: int = 1024,
) -> list[Block]:
    """Run layout detection; return blocks with types and bboxes (no text, words)."""
    arr = np.array(image.convert("RGB"))
    # BGR for OpenCV-style models (Ultralytics accepts ndarray)
    arr_bgr = arr[:, :, ::-1].copy()
    det_res = model.predict(arr_bgr, imgsz=imgsz, conf=conf, verbose=False)
    if not det_res or det_res[0].boxes is None or len(det_res[0].boxes) == 0:
        return []

    res = det_res[0]
    names: dict = getattr(res, "names", None) or getattr(model, "names", {}) or {}
    blocks: list[Block] = []
    for box in res.boxes:
        cls_id = int(box.cls[0].item() if hasattr(box.cls[0], "item") else box.cls[0])
        label = str(names.get(cls_id, cls_id))
        x1, y1, x2, y2 = box.xyxy[0].tolist()
        blocks.append(
            Block(
                block_type=_label_to_block_type(label),
                text="",
                bbox=BBox(float(x1), float(y1), float(x2), float(y2)),
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


def assign_words_to_blocks(blocks: list[Block], words: list) -> None:
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
        b.words = _sort_words_into_lines(b.words)
        b.text = " ".join(w.text for w in b.words).strip()


def layout_and_assign_words(
    image: Image.Image,
    words: list,
    model,
    page_w: int,
    page_h: int,
    conf: float,
    imgsz: int,
) -> list[Block]:
    blocks = analyze_layout(image, model, conf=conf, imgsz=imgsz)
    if not blocks:
        one = Block(
            block_type=BlockType.TEXT,
            text="",
            bbox=BBox(0, 0, float(page_w), float(page_h)),
        )
        blocks = [one]
    assign_words_to_blocks(blocks, words)
    blocks = [b for b in blocks if b.text or b.block_type in (BlockType.FIGURE, BlockType.TABLE)]
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
        words_sorted = _sort_words_into_lines(words)
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
