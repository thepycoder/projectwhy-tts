"""Block-level prefetch pipeline: layout + TTS synthesis ahead of playback."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import pypdfium2 as pdfium

from projectwhy.core.document import ensure_pdf_page_loaded
from projectwhy.core.models import Block, Document, Page, TTSResult, WordPosition, WordTimestamp
from projectwhy.core.tts.base import TTSEngine

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    SYNTHESIZING = "synthesizing"
    READY = "ready"
    PLAYING = "playing"
    DONE = "done"


@dataclass
class BlockJob:
    page_index: int
    block_index: int
    status: JobStatus
    block: Block
    tts_result: TTSResult | None = None
    alignment: list[int] | None = None


class Prefetcher:
    """Walks ahead through the document, synthesizing upcoming speakable blocks.

    A single worker thread does page layout (if needed) + TTS for each block.
    Backpressure keeps at most *lookahead* unconsumed jobs in the queue.
    The playback thread calls ``take_next()``; the inspector calls ``peek()``.
    """

    def __init__(
        self,
        document: Document,
        pdf: pdfium.PdfDocument | None,
        tts: TTSEngine,
        *,
        layout_model: Any,
        pdf_scale: float,
        should_speak: Callable[[Block], bool],
        build_alignment: Callable[[list[WordPosition], list[WordTimestamp]], list[int]],
        page_lock: threading.Lock,
        tts_lock: threading.Lock,
        lookahead: int = 3,
        should_yield: Callable[[], bool] | None = None,
    ) -> None:
        self._document = document
        self._pdf = pdf
        self._tts = tts
        self._layout_model = layout_model
        self._pdf_scale = pdf_scale
        self._should_speak = should_speak
        self._build_alignment = build_alignment
        self._page_lock = page_lock
        self._tts_lock = tts_lock
        self._lookahead = lookahead
        self._should_yield = should_yield

        self._jobs: list[BlockJob] = []
        self._cond = threading.Condition()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._exhausted = False

    # -- public API ----------------------------------------------------------

    def start(self, page_index: int, block_index: int) -> None:
        self._cancel.clear()
        self._exhausted = False
        with self._cond:
            self._jobs.clear()
        self._worker = threading.Thread(
            target=self._run,
            args=(page_index, block_index),
            daemon=True,
            name="prefetch",
        )
        self._worker.start()

    def stop(self) -> None:
        self._cancel.set()
        with self._cond:
            self._cond.notify_all()
        if self._worker is not None:
            self._worker.join(timeout=3.0)
        self._worker = None
        with self._cond:
            self._jobs.clear()
            self._exhausted = False

    def take_next(self) -> BlockJob | None:
        """Block until the next job is READY.  Returns *None* at end-of-document, cancel, or yield."""
        with self._cond:
            while True:
                if self._cancel.is_set():
                    return None
                if self._should_yield and self._should_yield():
                    return None

                for job in self._jobs:
                    if job.status == JobStatus.READY:
                        for prev in self._jobs:
                            if prev.status == JobStatus.PLAYING:
                                prev.status = JobStatus.DONE
                        job.status = JobStatus.PLAYING
                        self._cond.notify_all()
                        return job

                if self._exhausted:
                    return None

                self._cond.wait(timeout=0.2)

    def wake(self) -> None:
        """Wake take_next() so it can re-check external conditions."""
        with self._cond:
            self._cond.notify_all()

    def peek(self) -> list[BlockJob]:
        """Snapshot of the pipeline (safe to call from any thread)."""
        with self._cond:
            return list(self._jobs)

    def invalidate(self, page_index: int, block_index: int) -> None:
        """Flush the queue and restart from a new position."""
        self.stop()
        self.start(page_index, block_index)

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
            )

    def _next_speakable(self, pi: int, bi: int) -> tuple[int, int] | None:
        """Scan forward for the next speakable block, loading pages as needed."""
        n_pages = len(self._document.pages)
        while pi < n_pages:
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

    def _wait_for_space(self) -> bool:
        """Block until fewer than *lookahead* jobs are unconsumed.  False on cancel."""
        with self._cond:
            while not self._cancel.is_set():
                unconsumed = sum(
                    1
                    for j in self._jobs
                    if j.status in (JobStatus.SYNTHESIZING, JobStatus.READY)
                )
                if unconsumed < self._lookahead:
                    return True
                self._cond.wait(timeout=0.2)
        return False

    def _run(self, pi: int, bi: int) -> None:
        try:
            self._run_inner(pi, bi)
        except Exception:
            logger.exception("prefetch worker crashed")
        finally:
            with self._cond:
                self._exhausted = True
                self._cond.notify_all()

    def _run_inner(self, pi: int, bi: int) -> None:
        while not self._cancel.is_set():
            with self._cond:
                self._jobs = [j for j in self._jobs if j.status != JobStatus.DONE]

            if not self._wait_for_space():
                return

            pos = self._next_speakable(pi, bi)
            if pos is None:
                return
            pi, bi = pos

            page = self._document.pages[pi]
            block = page.blocks[bi]

            job = BlockJob(
                page_index=pi,
                block_index=bi,
                status=JobStatus.SYNTHESIZING,
                block=block,
            )
            with self._cond:
                self._jobs.append(job)
                self._cond.notify_all()

            if self._cancel.is_set():
                return

            with self._tts_lock:
                if self._cancel.is_set():
                    return
                res = self._tts.synthesize(block.text)

            if self._cancel.is_set():
                return

            job.tts_result = res
            job.alignment = (
                self._build_alignment(block.words, res.word_timestamps)
                if res.word_timestamps
                else None
            )

            with self._cond:
                job.status = JobStatus.READY
                self._cond.notify_all()

            bi += 1
