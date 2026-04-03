"""Fast unit tests for pure layout/session helpers (no PDF, no layout model)."""

from __future__ import annotations

from projectwhy.core.layout import (
    _rejoin_hyphenated,
    _sort_words_into_lines,
    assign_words_to_blocks,
)
from projectwhy.core.models import BBox, Block, BlockType, WordPosition, WordTimestamp
from projectwhy.core.session import ReadingSession


def test_sort_words_into_lines_clusters_by_y_tolerance():
    words = [
        WordPosition("a", BBox(0, 100, 10, 120)),
        WordPosition("b", BBox(20, 102, 30, 118)),
        WordPosition("c", BBox(0, 150, 10, 170)),
    ]
    out = _sort_words_into_lines(words)
    assert [w.text for w in out] == ["a", "b", "c"]


def test_rejoin_hyphenated_merges_soft_hyphen_pair():
    shy = "\u00ad"
    words = [
        WordPosition(f"hyph{shy}", BBox(0, 0, 1, 1)),
        WordPosition("en", BBox(0, 0, 1, 1)),
    ]
    out = _rejoin_hyphenated(words)
    assert len(out) == 1
    assert out[0].text == "hyphen"


def test_rejoin_hyphenated_trailing_soft_hyphen_last_word():
    shy = "\u00ad"
    words = [WordPosition(f"end{shy}", BBox(0, 0, 1, 1))]
    out = _rejoin_hyphenated(words)
    assert len(out) == 1
    assert out[0].text == "end"


def test_assign_words_to_blocks_nearest_when_outside_all_boxes():
    left = Block(BlockType.TEXT, "", BBox(0, 0, 40, 100))
    right = Block(BlockType.TEXT, "", BBox(60, 0, 100, 100))
    blocks = [left, right]
    # Center (56, 50) lies in the gap; closer to right block center (80, 50) than left (20, 50).
    w = WordPosition("lonely", BBox(55, 40, 57, 60))
    assign_words_to_blocks(blocks, [w])
    assert right.words
    assert "lonely" in right.text


def test_build_alignment_maps_tokens_to_word_indices():
    bws = [
        WordPosition("Hello", BBox(0, 0, 1, 1)),
        WordPosition("world", BBox(0, 0, 1, 1)),
    ]
    ts = [
        WordTimestamp("Hello", 0.0, 0.2),
        WordTimestamp("world", 0.2, 0.4),
    ]
    m = ReadingSession._build_alignment(bws, ts)
    assert m == [0, 1]


def test_build_alignment_reuses_previous_index_when_token_missing():
    bws = [WordPosition("only", BBox(0, 0, 1, 1))]
    ts = [
        WordTimestamp("only", 0.0, 0.2),
        WordTimestamp("ghost", 0.2, 0.4),
    ]
    m = ReadingSession._build_alignment(bws, ts)
    assert m == [0, 0]
