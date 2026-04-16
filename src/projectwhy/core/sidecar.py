"""Merge-aware read/write helpers for per-document sidecar TOML files.

The sidecar for a document at ``/path/to/book.epub`` lives at
``/path/to/book.epub.projectwhy.toml``.  Multiple features (substitutions,
reading position, …) share this file under separate TOML sections.  All
writes must preserve sections they did not touch.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import tomli_w

logger = logging.getLogger(__name__)


def load_sidecar(doc_path: str) -> dict[str, Any]:
    """Return the full sidecar dict, or ``{}`` if absent or unreadable."""
    try:
        import tomllib  # type: ignore[import]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]

    sidecar = Path(doc_path + ".projectwhy.toml")
    if not sidecar.exists():
        return {}
    try:
        return tomllib.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("sidecar read failed: %s", sidecar)
        return {}


def save_sidecar_section(doc_path: str, section: str, data: dict[str, Any]) -> None:
    """Write *data* under *section* in the sidecar, preserving all other sections."""
    existing = load_sidecar(doc_path)
    existing[section] = data
    sidecar = Path(doc_path + ".projectwhy.toml")
    try:
        with sidecar.open("wb") as f:
            tomli_w.dump(existing, f)
    except OSError:
        logger.exception("sidecar write failed: %s", sidecar)


def load_reading_position(doc_path: str, page_count: int) -> tuple[int, int] | None:
    """Return ``(page_index, block_index)`` from sidecar if still valid, else ``None``.

    ``page_count`` is used to validate that the saved page is still in range.
    ``block_index`` is clamped to ``≥ 0``; out-of-range block indices are handled
    gracefully by ``ReadingSession.go_to_position`` (falls back to first speakable).
    """
    rp = load_sidecar(doc_path).get("reading_position")
    if not isinstance(rp, dict):
        return None
    pi = rp.get("page_index")
    bi = rp.get("block_index")
    if not isinstance(pi, int) or not isinstance(bi, int):
        return None
    if pi < 0 or pi >= page_count:
        return None
    return pi, max(0, bi)


def save_reading_position(doc_path: str, page_index: int, block_index: int) -> None:
    """Persist ``(page_index, block_index)`` into the sidecar's ``[reading_position]`` section."""
    save_sidecar_section(doc_path, "reading_position", {
        "page_index": page_index,
        "block_index": block_index,
    })
