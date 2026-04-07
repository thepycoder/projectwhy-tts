"""Heuristic reading order for layout blocks (after PP-DocLayout detection).

PP-DocLayout ``boxes`` order is not reliable document reading order; we sort narrow blocks into
columns, then merge full-width strips without re-sorting narrow blocks by global y (which would
swap same-row left/right when one column is a pixel higher).
"""

from __future__ import annotations

from statistics import mean

from projectwhy.core.models import Block, BBox


def _center_x(b: BBox) -> float:
    return (b.x1 + b.x2) / 2


def _top_y(b: BBox) -> float:
    return min(b.y1, b.y2)


def _is_full_width(b: BBox, page_width: float, frac: float = 0.7) -> bool:
    return (b.x2 - b.x1) >= page_width * frac


def _merge_full_width_by_y(fw: list[Block], ordered_narrow: list[Block]) -> list[Block]:
    """Interleave full-width blocks (by top y) with *ordered_narrow* without reordering narrow."""
    result: list[Block] = []
    fw_queue = sorted(fw, key=lambda b: _top_y(b.bbox))
    narrow_queue = list(ordered_narrow)
    while narrow_queue or fw_queue:
        if not fw_queue:
            result.extend(narrow_queue)
            break
        if not narrow_queue:
            result.extend(fw_queue)
            break
        ny = _top_y(narrow_queue[0].bbox)
        fy = _top_y(fw_queue[0].bbox)
        if fy <= ny:
            result.append(fw_queue.pop(0))
        else:
            result.append(narrow_queue.pop(0))
    return result


def sort_blocks_reading_order(
    blocks: list[Block], page_width: float, _page_height: float
) -> list[Block]:
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

    return _merge_full_width_by_y(fw, ordered_narrow)
