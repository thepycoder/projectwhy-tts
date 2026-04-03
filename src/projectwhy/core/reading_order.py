"""Heuristic reading order for layout blocks."""

from __future__ import annotations

from statistics import mean

from projectwhy.core.models import Block, BBox


def _center_x(b: BBox) -> float:
    return (b.x1 + b.x2) / 2


def _top_y(b: BBox) -> float:
    return min(b.y1, b.y2)


def _is_full_width(b: BBox, page_width: float, frac: float = 0.7) -> bool:
    return (b.x2 - b.x1) >= page_width * frac


def sort_blocks_reading_order(blocks: list[Block], page_width: float, page_height: float) -> list[Block]:
    if not blocks:
        return []

    fw = [b for b in blocks if _is_full_width(b.bbox, page_width)]
    narrow = [b for b in blocks if not _is_full_width(b.bbox, page_width)]

    if not narrow:
        return sorted(blocks, key=lambda b: _top_y(b.bbox))

    centers = [_center_x(b.bbox) for b in narrow]
    m = mean(centers)
    left_col = [b for b in narrow if _center_x(b.bbox) < m]
    right_col = [b for b in narrow if _center_x(b.bbox) >= m]

    # If right column is tiny, treat as single column
    if len(right_col) <= max(1, len(left_col) // 10):
        ordered_narrow = sorted(narrow, key=lambda b: (_top_y(b.bbox), _center_x(b.bbox)))
    else:
        left_sorted = sorted(left_col, key=lambda b: _top_y(b.bbox))
        right_sorted = sorted(right_col, key=lambda b: _top_y(b.bbox))
        ordered_narrow = left_sorted + right_sorted

    # Merge full-width blocks by vertical position
    all_items: list[tuple[float, int, Block]] = []
    for i, b in enumerate(ordered_narrow):
        all_items.append((_top_y(b.bbox), i, b))
    for j, b in enumerate(fw):
        all_items.append((_top_y(b.bbox), 10000 + j, b))

    all_items.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in all_items]
