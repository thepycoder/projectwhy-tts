"""Small helpers for PDF block regression tests."""

from __future__ import annotations

from projectwhy.core.models import Block


def find_block_containing(blocks: list[Block], snippet: str) -> Block | None:
    """Return the first block whose combined text contains *snippet*, or None."""
    for b in blocks:
        if snippet in b.text:
            return b
    return None


def assert_reading_order(blocks: list[Block], *snippets: str) -> None:
    """Assert *snippets* appear in blocks in order (block index non-decreasing)."""
    search_from = 0
    for snippet in snippets:
        found_idx: int | None = None
        for i in range(search_from, len(blocks)):
            if snippet in blocks[i].text:
                found_idx = i
                break
        assert found_idx is not None, (
            f"Snippet {snippet!r} not found in blocks[{search_from}:]"
        )
        search_from = found_idx


def assert_not_split(blocks: list[Block], *snippets: str) -> None:
    """Assert all *snippets* occur in the same block."""
    target: Block | None = None
    for snippet in snippets:
        block = find_block_containing(blocks, snippet)
        assert block is not None, f"{snippet!r} not found in any block"
        if target is None:
            target = block
        else:
            assert block is target, (
                f"{snippet!r} is in a different block than {snippets[0]!r}"
            )
