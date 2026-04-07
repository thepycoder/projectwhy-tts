"""Slow tests: real PDF fixtures + PP-DocLayout. Run all: ``uv run pytest``; skip slow: ``uv run pytest -m 'not slow'``."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from projectwhy.config import load
from projectwhy.core.layout import layout_and_assign_words, load_layout_model
from projectwhy.core.models import BlockType
from projectwhy.core.pdf import extract_words, open_pdf

from tests.helpers import assert_reading_order, find_block_containing

_FIXTURE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "config.toml"
_FIXTURE_PDF_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"

# Add regression tests here. One-shot scaffold:
#   uv run python -m tests.helper_cli add /path/to/source.pdf --page N --snippet "..." \\
#       --expect-type text --test-name my_case


@pytest.fixture(scope="module")
def sewtha_p1_blocks_doclayout_l_scale4():
    """Same layout pipeline as typical ``config.toml`` (L model, pdf_scale 4) — reproduces column swap."""
    base = load(_FIXTURE_CONFIG)
    cfg = replace(
        base,
        layout=replace(base.layout, model_name="PP-DocLayout-L"),
        display=replace(base.display, pdf_scale=4.0),
    )
    model = load_layout_model(
        model_name=cfg.layout.model_name,
        model_dir=cfg.layout.model_dir or None,
        threshold=cfg.layout.confidence,
        device=cfg.layout.device or None,
        layout_nms=cfg.layout.layout_nms,
        enable_mkldnn=cfg.layout.enable_mkldnn,
    )
    pdf_path = _FIXTURE_PDF_DIR / "sewtha_p1.pdf"
    doc = open_pdf(str(pdf_path))
    page = doc[0]
    try:
        pil, words = extract_words(page, cfg.display.pdf_scale)
        w, h = pil.size
        return layout_and_assign_words(pil, words, model, w, h)
    finally:
        page.close()
        doc.close()


@pytest.mark.slow
def test_sewtha_page2_two_column_reading_order_left_before_right(sewtha_p1_blocks_doclayout_l_scale4):
    """Endorsements page: left column before right (LTR) for same-row quotes.

    Regression guard: uses PP-DocLayout-L and pdf_scale 4.0 (matches common ``config.toml``).
    PP-DocLayout-M at 2.0 merges text differently on this fixture.

    Note: raw PP-DocLayout ``boxes`` order is not reading order here (snippets can be ~15 blocks
    apart); sorting after detection is still required.
    """
    blocks = sewtha_p1_blocks_doclayout_l_scale4
    assert_reading_order(
        blocks,
        "The quest for safe, secure and sustainable energy",
        "This is a really valuable contribution to the continuing discussion",
    )


@pytest.mark.slow
@pytest.mark.skip(reason="Add a PDF under tests/fixtures/pdfs/ and remove skip to enable example.")
def test_example_placeholder(load_page):
    blocks = load_page("example_p0.pdf", 0)
    block = find_block_containing(blocks, "example snippet")
    assert block is not None
    assert block.block_type == BlockType.TEXT
