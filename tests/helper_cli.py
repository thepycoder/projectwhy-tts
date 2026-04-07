"""CLI to extract single-page PDF fixtures, inspect layout blocks, and scaffold tests.

Run: ``uv run python -m tests.helper_cli --help``
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium

from projectwhy.config import load
from projectwhy.core.layout import layout_and_assign_words, load_layout_model
from projectwhy.core.models import Block, BlockType
from projectwhy.core.pdf import extract_words, open_pdf

from tests.helpers import find_block_containing

FIXTURES_PDF_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"
FIXTURE_CONFIG = Path(__file__).resolve().parent / "fixtures" / "config.toml"


def _resolved_config_path() -> Path:
    cwd = Path.cwd() / "config.toml"
    if cwd.is_file():
        return cwd
    return FIXTURE_CONFIG
_PREVIEW_LEN = 72


def _slug_stem(path: Path) -> str:
    s = path.stem
    s = re.sub(r"[^a-zA-Z0-9_-]+", "_", s).strip("_")
    return s or "doc"


def default_fixture_path(source_pdf: Path, page_index: int) -> Path:
    stem = _slug_stem(source_pdf)
    return FIXTURES_PDF_DIR / f"{stem}_p{page_index}.pdf"


def extract_page_to_fixture(
    source_pdf: Path,
    page_index: int,
    out_path: Path,
) -> None:
    """Write a one-page PDF containing *page_index* from *source_pdf*."""
    src = pdfium.PdfDocument(str(source_pdf))
    try:
        n = len(src)
        if page_index < 0 or page_index >= n:
            raise IndexError(f"page_index {page_index} out of range (0..{n - 1})")
        dst = pdfium.PdfDocument.new()
        try:
            dst.import_pages(src, pages=[page_index])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            dst.save(str(out_path))
        finally:
            dst.close()
    finally:
        src.close()


def blocks_for_pdf(pdf_path: Path, model, pdf_scale: float, page_index: int = 0) -> list[Block]:
    doc = open_pdf(str(pdf_path))
    page = doc[page_index]
    try:
        pil, words = extract_words(page, pdf_scale)
        w, h = pil.size
        return layout_and_assign_words(pil, words, model, w, h)
    finally:
        page.close()
        doc.close()


def _preview(text: str) -> str:
    t = " ".join(text.split())
    if len(t) <= _PREVIEW_LEN:
        return t
    return t[: _PREVIEW_LEN - 3] + "..."


def cmd_inspect(args: argparse.Namespace) -> int:
    cfg = load(_resolved_config_path())
    model = load_layout_model(
        model_name=cfg.layout.model_name,
        model_dir=cfg.layout.model_dir or None,
        threshold=cfg.layout.confidence,
        device=cfg.layout.device or None,
        layout_nms=cfg.layout.layout_nms,
        enable_mkldnn=cfg.layout.enable_mkldnn,
    )
    pdf_path = Path(args.pdf).expanduser().resolve()
    blocks = blocks_for_pdf(pdf_path, model, cfg.display.pdf_scale, page_index=args.page)
    print(f"{pdf_path.name} page {args.page} — {len(blocks)} blocks\n")
    for i, b in enumerate(blocks):
        prev = _preview(b.text) if b.text else "(no text)"
        print(f"  [{i}] {b.block_type.value!r}  {prev!r}")
    return 0


def cmd_extract_page(args: argparse.Namespace) -> int:
    source = Path(args.pdf).expanduser().resolve()
    out = Path(args.output).expanduser().resolve() if args.output else default_fixture_path(
        source,
        args.page,
    )
    extract_page_to_fixture(source, args.page, out)
    print(str(out))
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    cfg = load(_resolved_config_path())
    model = load_layout_model(
        model_name=cfg.layout.model_name,
        model_dir=cfg.layout.model_dir or None,
        threshold=cfg.layout.confidence,
        device=cfg.layout.device or None,
        layout_nms=cfg.layout.layout_nms,
        enable_mkldnn=cfg.layout.enable_mkldnn,
    )
    source = Path(args.pdf).expanduser().resolve()
    fixture = (
        Path(args.output).expanduser().resolve()
        if args.output
        else default_fixture_path(source, args.page)
    )

    if not fixture.is_file():
        extract_page_to_fixture(source, args.page, fixture)
        print(f"Wrote fixture: {fixture}\n")
    else:
        print(f"Using existing fixture: {fixture}\n")

    try:
        expect_type = BlockType(args.expect_type)
    except ValueError:
        print(f"Invalid --expect-type {args.expect_type!r}: not a BlockType value.", file=sys.stderr)
        print("Use the StrEnum value, e.g. text, paragraph_title, figure_caption.", file=sys.stderr)
        return 2

    blocks = blocks_for_pdf(fixture, model, cfg.display.pdf_scale, page_index=0)
    block = find_block_containing(blocks, args.snippet)
    if block is None:
        print(f"Snippet not found in any block: {args.snippet!r}\n", file=sys.stderr)
        print("Blocks on this page:", file=sys.stderr)
        for i, b in enumerate(blocks):
            print(f"  [{i}] {b.block_type.value!r}  {_preview(b.text)!r}", file=sys.stderr)
        return 1

    idx = blocks.index(block)
    print(f"Snippet found in block [{idx}] type={block.block_type.value!r}")
    print(f"Preview: {_preview(block.text)!r}\n")

    fixture_name = fixture.name
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", args.test_name)
    sk = f'''@pytest.mark.slow
def test_{safe_name}(load_page):
    blocks = load_page("{fixture_name}", 0)
    block = find_block_containing(blocks, {args.snippet!r})
    assert block is not None
    assert block.block_type == BlockType.{expect_type.name}
'''
    print("--- Paste into tests/test_pdf_blocks.py ---")
    print(sk, end="")
    print("---")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="PDF test fixture + scaffold helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Extract page if needed, run layout, print test skeleton")
    p_add.add_argument("pdf", help="Source PDF path")
    p_add.add_argument("--page", type=int, default=0, help="0-based page index (default: 0)")
    p_add.add_argument("--snippet", required=True, help="Text that must appear in the target block")
    p_add.add_argument(
        "--expect-type",
        required=True,
        help="BlockType value (e.g. text, paragraph_title)",
    )
    p_add.add_argument("--test-name", required=True, help="Function suffix: test_<name>")
    p_add.add_argument(
        "--output",
        help="Fixture path (default: tests/fixtures/pdfs/<stem>_p<N>.pdf)",
    )
    p_add.set_defaults(func=cmd_add)

    p_insp = sub.add_parser("inspect", help="List blocks for a PDF page")
    p_insp.add_argument("pdf", help="PDF path")
    p_insp.add_argument("--page", type=int, default=0, help="0-based page index")
    p_insp.set_defaults(func=cmd_inspect)

    p_ext = sub.add_parser("extract-page", help="Write one page to tests/fixtures/pdfs/")
    p_ext.add_argument("pdf", help="Source PDF path")
    p_ext.add_argument("--page", type=int, default=0, help="0-based page index")
    p_ext.add_argument(
        "--output",
        help="Output path (default: tests/fixtures/pdfs/<stem>_p<N>.pdf)",
    )
    p_ext.set_defaults(func=cmd_extract_page)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
