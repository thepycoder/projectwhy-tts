"""Cursor-driven prefetch warmer: fills UtteranceCache ahead of the playback cursor."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pypdfium2 as pdfium

from projectwhy.config import PdfTextConfig
from projectwhy.core.document import ensure_pdf_page_loaded
from projectwhy.core.models import Block, Document, Page
from projectwhy.core.utterance_cache import UtteranceCache

logger = logging.getLogger(__name__)


@dataclass
class WarmRow:
    """Inspector snapshot of one warmer target."""
    page_index: int
    block_index: int
    block_type: str
    cached: bool


class PrefetchWarmer:
    """Background thread that pre-synthesizes upcoming speakable blocks into UtteranceCache.

    The warmer reads the current cursor via *get_cursor* (which returns
    ``(page_index, block_index, cursor_gen)`` under the session's cursor lock),
    computes the next *lookahead* speakable block positions, and calls
    ``cache.get_or_synthesize`` for each one that is not already cached.

    Before and after each ``synthesize()`` call the warmer re-reads the cursor
    generation; if it changed (user navigated), the current target list is
    abandoned and the outer loop restarts from the new cursor.
    """

    def __init__(
        self,
        document: Document,
        pdf: pdfium.PdfDocument | None,
        *,
        layout_model: Any,
        pdf_scale: float,
        pdf_text: PdfTextConfig,
        should_speak: Callable[[Block], bool],
        page_lock: threading.Lock,
        cache: UtteranceCache,
        get_cursor: Callable[[], tuple[int, int, int]],
        lookahead: int = 3,
    ) -> None:
        self._document = document
        self._pdf = pdf
        self._layout_model = layout_model
        self._pdf_scale = pdf_scale
        self._pdf_text = pdf_text
        self._should_speak = should_speak
        self._page_lock = page_lock
        self._cache = cache
        self._get_cursor = get_cursor
        self._lookahead = lookahead

        self._wake = threading.Condition()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None

        self._snapshot_lock = threading.Lock()
        self._snapshot: list[WarmRow] = []

    # -- public API ----------------------------------------------------------

    def start(self) -> None:
        self._cancel.clear()
        self._worker = threading.Thread(
            target=self._run, daemon=True, name="prefetch-warmer"
        )
        self._worker.start()
        self.notify()  # kick off an immediate pass

    def stop(self) -> None:
        self._cancel.set()
        with self._wake:
            self._wake.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=3.0)
            self._worker = None
        with self._snapshot_lock:
            self._snapshot.clear()

    def notify(self) -> None:
        """Wake the warmer to re-read cursor and update targets."""
        with self._wake:
            self._wake.notify_all()

    def update_lookahead(self, n: int) -> None:
        self._lookahead = n
        self.notify()

    def set_pdf_text(self, pdf_text: PdfTextConfig) -> None:
        self._pdf_text = pdf_text

    def peek_snapshot(self) -> list[WarmRow]:
        """Return a snapshot of current warm targets (safe to call from any thread)."""
        with self._snapshot_lock:
            return list(self._snapshot)

    # -- worker internals ----------------------------------------------------

    def _ensure_page(self, idx: int) -> Page:
        if self._document.doc_type != "pdf" or self._pdf is None:
            return self._document.pages[idx]
        with self._page_lock:
            return ensure_pdf_page_loaded(
                self._document,
                idx,
                self._pdf,
                self._layout_model,
                self._pdf_scale,
                pdf_text=self._pdf_text,
            )

    def _find_next(self, pi: int, bi: int) -> tuple[int, int] | None:
        """Return first speakable block at or after (pi, bi), loading pages as needed."""
        n = len(self._document.pages)
        while pi < n:
            if self._cancel.is_set():
                return None
            page = self._ensure_page(pi)
            while bi < len(page.blocks):
                if self._should_speak(page.blocks[bi]):
                    return pi, bi
                bi += 1
            pi += 1
            bi = 0
        return None

    def _run(self) -> None:
        try:
            self._run_inner()
        except Exception:
            logger.exception("prefetch warmer crashed")

    def _run_inner(self) -> None:
        while not self._cancel.is_set():
            with self._wake:
                self._wake.wait(timeout=0.5)

            if self._cancel.is_set():
                break

            pi, bi, gen = self._get_cursor()

            # Compute lookahead targets starting from current cursor (inclusive)
            targets: list[tuple[int, int]] = []
            cur_pi, cur_bi = pi, bi
            for _ in range(self._lookahead):
                if self._cancel.is_set():
                    break
                pos = self._find_next(cur_pi, cur_bi)
                if pos is None:
                    break
                targets.append(pos)
                cur_pi, cur_bi = pos[0], pos[1] + 1

            if self._cancel.is_set():
                break

            # Build inspector snapshot (use already-loaded page data)
            rows: list[WarmRow] = []
            for tpi, tbi in targets:
                pages = self._document.pages
                if tpi < len(pages) and tbi < len(pages[tpi].blocks):
                    block = pages[tpi].blocks[tbi]
                    rows.append(WarmRow(tpi, tbi, block.block_type.value, self._cache.get(block) is not None))
            with self._snapshot_lock:
                self._snapshot = rows

            # Synthesize uncached targets
            for i, (tpi, tbi) in enumerate(targets):
                if self._cancel.is_set():
                    break

                _, _, cur_gen = self._get_cursor()
                if cur_gen != gen:
                    break

                pages = self._document.pages
                if tpi >= len(pages) or tbi >= len(pages[tpi].blocks):
                    continue
                block = pages[tpi].blocks[tbi]

                if self._cache.get(block) is not None:
                    # already cached — update snapshot if needed
                    with self._snapshot_lock:
                        if i < len(self._snapshot) and not self._snapshot[i].cached:
                            r = self._snapshot[i]
                            self._snapshot[i] = WarmRow(r.page_index, r.block_index, r.block_type, True)
                    continue

                _, _, cur_gen = self._get_cursor()
                if cur_gen != gen:
                    break

                try:
                    self._cache.get_or_synthesize(block)
                except Exception:
                    logger.exception("warmer: synthesis failed for block (%d, %d)", tpi, tbi)
                    continue

                with self._snapshot_lock:
                    if i < len(self._snapshot):
                        r = self._snapshot[i]
                        self._snapshot[i] = WarmRow(r.page_index, r.block_index, r.block_type, True)

                _, _, cur_gen = self._get_cursor()
                if cur_gen != gen:
                    break
