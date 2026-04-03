"""RGB colors per layout block type — shared by inspector UI and PDF overlays."""

from __future__ import annotations

from projectwhy.core.models import BlockType

# Distinct hues across PP-DocLayout categories; captions/titles in blue family, body green,
# figures purple, tables orange, structural gray, math red, metadata brown/olive.
BLOCK_COLORS: dict[BlockType, tuple[int, int, int]] = {
    BlockType.DOCUMENT_TITLE: (40, 90, 220),
    BlockType.DOC_TITLE: (35, 85, 215),
    BlockType.PARAGRAPH_TITLE: (70, 130, 240),
    BlockType.FIGURE_TITLE: (90, 110, 235),
    BlockType.CHART_TITLE: (85, 100, 225),
    BlockType.TEXT: (40, 160, 70),
    BlockType.CONTENT: (45, 165, 75),
    BlockType.ABSTRACT: (50, 170, 90),
    BlockType.ASIDE_TEXT: (55, 145, 85),
    BlockType.ALGORITHM: (30, 140, 100),
    BlockType.FOOTNOTES: (45, 150, 75),
    BlockType.FIGURE: (150, 70, 200),
    BlockType.CHART: (145, 65, 195),
    BlockType.IMAGE: (170, 90, 210),
    BlockType.FIGURE_CAPTION: (195, 140, 235),
    BlockType.TABLE: (235, 120, 35),
    BlockType.TABLE_CAPTION: (235, 175, 90),
    BlockType.FORMULA: (210, 55, 55),
    BlockType.FORMULA_NUMBER: (180, 70, 70),
    BlockType.HEADER: (115, 115, 125),
    BlockType.FOOTER: (95, 95, 105),
    BlockType.PAGE_NUMBER: (100, 100, 115),
    BlockType.NUMBER: (105, 105, 118),
    BlockType.HEADER_IMAGE: (130, 100, 160),
    BlockType.FOOTER_IMAGE: (110, 95, 130),
    BlockType.TABLE_OF_CONTENTS: (160, 120, 60),
    BlockType.REFERENCES: (130, 85, 45),
    BlockType.SEAL: (200, 80, 120),
    BlockType.UNKNOWN: (90, 90, 95),
}


def rgb_for_block_type(t: BlockType) -> tuple[int, int, int]:
    if t in BLOCK_COLORS:
        return BLOCK_COLORS[t]
    # Stable pseudo-color for UNKNOWN or future labels
    h = hash(t.value) % (256**3)
    r = 80 + (h & 0x7F)
    g = 80 + ((h >> 8) & 0x7F)
    b = 80 + ((h >> 16) & 0x7F)
    return (r, g, b)
