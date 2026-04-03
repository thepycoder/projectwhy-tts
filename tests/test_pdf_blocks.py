"""Slow tests: real PDF fixtures + PP-DocLayout. Run all: ``uv run pytest``; skip slow: ``uv run pytest -m 'not slow'``."""

from __future__ import annotations

import pytest

from projectwhy.core.models import BlockType

from tests.helpers import find_block_containing

# Add regression tests here. One-shot scaffold:
#   uv run python -m tests.helper_cli add /path/to/source.pdf --page N --snippet "..." \\
#       --expect-type text --test-name my_case

@pytest.mark.slow
@pytest.mark.skip(reason="Add a PDF under tests/fixtures/pdfs/ and remove skip to enable example.")
def test_example_placeholder(load_page):
    blocks = load_page("example_p0.pdf", 0)
    block = find_block_containing(blocks, "example snippet")
    assert block is not None
    assert block.block_type == BlockType.TEXT
