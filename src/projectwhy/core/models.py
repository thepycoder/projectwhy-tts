"""Shared data structures."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class BlockType(StrEnum):
    """Labels returned by PP-DocLayout / PP-DocLayout_plus layout detectors (snake_case).

    Different checkpoints use slightly different vocabularies (e.g. ``doc_title`` vs
    ``document_title``); we keep the model string as the enum value so the Inspector
    matches inference output.
    """

    DOCUMENT_TITLE = "document_title"
    DOC_TITLE = "doc_title"
    PARAGRAPH_TITLE = "paragraph_title"
    TEXT = "text"
    CONTENT = "content"
    PAGE_NUMBER = "page_number"
    NUMBER = "number"
    ABSTRACT = "abstract"
    TABLE_OF_CONTENTS = "table_of_contents"
    REFERENCES = "references"
    FOOTNOTES = "footnotes"
    HEADER = "header"
    FOOTER = "footer"
    ALGORITHM = "algorithm"
    FORMULA = "formula"
    FORMULA_NUMBER = "formula_number"
    IMAGE = "image"
    FIGURE_CAPTION = "figure_caption"
    TABLE = "table"
    TABLE_CAPTION = "table_caption"
    SEAL = "seal"
    FIGURE_TITLE = "figure_title"
    CHART_TITLE = "chart_title"
    FIGURE = "figure"
    CHART = "chart"
    HEADER_IMAGE = "header_image"
    FOOTER_IMAGE = "footer_image"
    ASIDE_TEXT = "aside_text"
    UNKNOWN = "_unknown_"

    @classmethod
    def from_pp_label(cls, label: str) -> BlockType:
        s = label.strip().lower().replace(" ", "_")
        try:
            return cls(s)
        except ValueError:
            logger.warning("Unknown layout label from model: %r — using UNKNOWN", label)
            return cls.UNKNOWN


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
