---
name: projectwhy-test-harness
description: Creates and runs regression tests for projectwhy-tts PDF layout, reading order, and block text using fixtures, pytest, and tests/helper_cli.py. Use when the user reports PDF layout bugs, wrong block types, mis-assigned text, reading-order issues, or asks to add a test for a specific PDF page.
---

# projectwhy-tts test harness

## Commands

- **One-shot scaffold (extract page → layout → find snippet → print test):**
  ```bash
  uv sync --group dev
  uv run python -m tests.helper_cli add /path/to/source.pdf \
    --page 0 \
    --snippet "exact substring from the PDF" \
    --expect-type text \
    --test-name short_snake_case_name
  ```
  - `--expect-type` must be a `BlockType` **value** (same strings as in GUI), e.g. `text`, `paragraph_title`, `figure_caption`, `abstract`.
  - Default fixture path: `tests/fixtures/pdfs/<slug>_p<N>.pdf`. Override with `--output`.
  - Copies printed function into [`tests/test_pdf_blocks.py`](tests/test_pdf_blocks.py) and add imports if missing: `pytest`, `BlockType`, `find_block_containing` (already there in scaffold).

- **Inspect blocks** (debug without writing a test):
  ```bash
  uv run python -m tests.helper_cli inspect /path/to/file.pdf --page 0
  ```

- **Extract only** (single-page PDF into fixtures):
  ```bash
  uv run python -m tests.helper_cli extract-page /path/to/file.pdf --page 3
  ```

## Running tests

- Fast (no PDF / no layout model): `uv run pytest -m "not slow"`
- All including slow: `uv run pytest`

Slow tests use a session-scoped layout model and files under [`tests/fixtures/pdfs/`](tests/fixtures/pdfs/).

## Assertion helpers

From [`tests/helpers.py`](tests/helpers.py):

- `find_block_containing(blocks, snippet)` — prefer anchoring tests on **snippets**, not block indices (indices change if layout shifts).
- `assert_reading_order(blocks, "first phrase", "second phrase")` — block order non-decreasing.
- `assert_not_split(blocks, "part1", "part2")` — snippets must share one block.

## Agent workflow

1. Confirm path to source PDF and 0-based `--page`.
2. Run `add` with a snippet copied from the document; fix `--expect-type` if CLI reports wrong type.
3. Paste output into `test_pdf_blocks.py`; remove any `@pytest.mark.skip` on examples; commit the PDF under `tests/fixtures/pdfs/` when adding a new file.

## Conventions

- Keep new unit tests **rare**; prefer a few solid `slow` PDF regressions over many trivial tests.
- Reuse small single-page fixtures; avoid committing huge PDFs.
