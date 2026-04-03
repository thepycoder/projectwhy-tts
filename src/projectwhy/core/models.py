"""Shared data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image


class BlockType(Enum):
    TITLE = "title"
    TEXT = "text"
    FIGURE = "figure"
    FIGURE_CAPTION = "figure_caption"
    TABLE = "table"
    TABLE_CAPTION = "table_caption"
    HEADER = "header"
    FOOTER = "footer"
    EQUATION = "equation"
    REFERENCE = "reference"


@dataclass
class BBox:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class WordPosition:
    text: str
    bbox: BBox


@dataclass
class WordTimestamp:
    text: str
    start_sec: float
    end_sec: float


@dataclass
class Block:
    block_type: BlockType
    text: str
    bbox: BBox
    words: list[WordPosition] = field(default_factory=list)


@dataclass
class Page:
    index: int
    blocks: list[Block]
    image: Any = None  # PIL.Image.Image | None (avoid importing PIL at module level for typing only)
    raw_text: str | None = None


@dataclass
class Document:
    path: str
    doc_type: str
    pages: list[Page] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResult:
    audio: Any  # np.ndarray
    sample_rate: int
    word_timestamps: list[WordTimestamp] | None = None


@dataclass
class ReadingState:
    page_index: int
    block_index: int
    word_index: int | None
    is_playing: bool
    position_sec: float
