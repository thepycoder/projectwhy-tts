"""RGB colors per layout block type — shared by inspector UI and PDF overlays."""

from __future__ import annotations

from projectwhy.core.models import BlockType

# TITLE: blue, TEXT: green, FIGURE: purple, TABLE: orange,
# HEADER/FOOTER: gray, EQUATION: red, REFERENCE: brown, captions: lighter.
BLOCK_COLORS: dict[BlockType, tuple[int, int, int]] = {
    BlockType.TITLE: (50, 120, 255),
    BlockType.TEXT: (40, 180, 80),
    BlockType.FIGURE: (160, 80, 220),
    BlockType.FIGURE_CAPTION: (200, 150, 240),
    BlockType.TABLE: (255, 140, 40),
    BlockType.TABLE_CAPTION: (255, 200, 120),
    BlockType.HEADER: (120, 120, 130),
    BlockType.FOOTER: (100, 100, 110),
    BlockType.EQUATION: (220, 60, 60),
    BlockType.REFERENCE: (139, 90, 43),
}

DEFAULT_BLOCK_RGB: tuple[int, int, int] = (100, 100, 100)


def rgb_for_block_type(t: BlockType) -> tuple[int, int, int]:
    return BLOCK_COLORS.get(t, DEFAULT_BLOCK_RGB)
