"""Unit tests for TTS substitutions and the refactored alignment."""

from __future__ import annotations

import pytest

from projectwhy.core.models import BBox, Block, BlockType, WordPosition, WordTimestamp
from projectwhy.core.session import ReadingSession
from projectwhy.core.substitutions import (
    SubstitutionRule,
    apply_rules_to_word,
    block_tts_parts,
    block_tts_text,
    parse_rules,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rule(find: str, replace: str, *, regex: bool = False) -> SubstitutionRule:
    return SubstitutionRule(find=find, replace=replace, use_regex=regex)


def _word(text: str) -> WordPosition:
    return WordPosition(text=text, bbox=BBox(0, 0, 10, 10))


def _block_with_words(*words: str) -> Block:
    wps = [_word(w) for w in words]
    return Block(
        block_type=BlockType.TEXT,
        text=" ".join(words),
        bbox=BBox(0, 0, 100, 20),
        words=wps,
    )


# ---------------------------------------------------------------------------
# apply_rules_to_word
# ---------------------------------------------------------------------------

def test_literal_replace_all_occurrences() -> None:
    rule = _rule("o", "0")
    assert apply_rules_to_word("foo", [rule]) == "f00"


def test_literal_no_match_unchanged() -> None:
    rule = _rule("xyz", "ABC")
    assert apply_rules_to_word("hello", [rule]) == "hello"


def test_rules_applied_in_order() -> None:
    rules = [_rule("CO2", "Carbon Dioxide"), _rule("Dioxide", "dioxide")]
    assert apply_rules_to_word("CO2", rules) == "Carbon dioxide"


def test_regex_replace_all_matches() -> None:
    rule = _rule(r"\d+", "NUM", regex=True)
    assert apply_rules_to_word("abc123def456", [rule]) == "abcNUMdefNUM"


def test_regex_group_reference() -> None:
    rule = _rule(r"(\w+)_(\w+)", r"\2_\1", regex=True)
    assert apply_rules_to_word("hello_world", [rule]) == "world_hello"


def test_empty_find_skipped_by_parse_rules() -> None:
    rules = parse_rules([{"find": "", "replace": "x"}])
    assert rules == []


def test_parse_rules_invalid_regex_raises() -> None:
    with pytest.raises(ValueError, match="invalid regex"):
        parse_rules([{"find": "[invalid", "replace": "x", "regex": True}])


def test_parse_rules_literal_and_regex() -> None:
    raw = [
        {"find": "CO2", "replace": "Carbon Dioxide"},
        {"find": r"\bH2O\b", "replace": "water", "regex": True},
    ]
    rules = parse_rules(raw)
    assert len(rules) == 2
    assert not rules[0].use_regex
    assert rules[1].use_regex


# ---------------------------------------------------------------------------
# block_tts_parts and block_tts_text
# ---------------------------------------------------------------------------

def test_block_tts_parts_no_rules() -> None:
    b = _block_with_words("Hello", "world")
    assert block_tts_parts(b, []) == ["Hello", "world"]


def test_block_tts_parts_substitution_applied_per_word() -> None:
    b = _block_with_words("The", "CO2", "level")
    rules = [_rule("CO2", "Carbon Dioxide")]
    parts = block_tts_parts(b, rules)
    assert parts == ["The", "Carbon Dioxide", "level"]


def test_block_tts_text_joins_with_spaces() -> None:
    assert block_tts_text(["Carbon Dioxide", "level"]) == "Carbon Dioxide level"


def test_block_tts_text_strips_whitespace() -> None:
    assert block_tts_text([" hello ", " world "]) == "hello   world"


# ---------------------------------------------------------------------------
# _build_alignment (via ReadingSession static method)
# ---------------------------------------------------------------------------

def _ts(*words: str, base: float = 0.0, dur: float = 0.3) -> list[WordTimestamp]:
    result = []
    for i, w in enumerate(words):
        start = base + i * dur
        result.append(WordTimestamp(text=w, start_sec=start, end_sec=start + dur))
    return result


def test_alignment_no_substitution() -> None:
    parts = ["hello", "world"]
    timestamps = _ts("hello", "world")
    mapping = ReadingSession._build_alignment(parts, timestamps)
    assert mapping == [0, 1]


def test_alignment_co2_expansion() -> None:
    # CO2 → "Carbon Dioxide": two Kokoro tokens both map to word index 1
    parts = ["The", "Carbon Dioxide", "level"]
    timestamps = _ts("The", "Carbon", "Dioxide", "level")
    mapping = ReadingSession._build_alignment(parts, timestamps)
    assert mapping[0] == 0   # "The"
    assert mapping[1] == 1   # "Carbon" → slot for "CO2"
    assert mapping[2] == 1   # "Dioxide" → same slot
    assert mapping[3] == 2   # "level"


def test_alignment_empty_timestamps() -> None:
    assert ReadingSession._build_alignment(["hello"], []) == []


def test_alignment_empty_parts() -> None:
    assert ReadingSession._build_alignment([], _ts("hello")) == []


def test_alignment_token_not_found_uses_previous() -> None:
    parts = ["hello", "world"]
    # "bogus" does not appear in "hello world"
    timestamps = [WordTimestamp(text="bogus", start_sec=0.0, end_sec=0.3)]
    mapping = ReadingSession._build_alignment(parts, timestamps)
    assert mapping == [0]  # fallback to last valid (or 0)
