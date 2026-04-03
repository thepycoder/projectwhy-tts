"""Reading session: navigation + playback orchestration."""

from __future__ import annotations

import threading
import time
from typing import Any

import pypdfium2 as pdfium

from projectwhy.core.document import ensure_pdf_page_loaded
from projectwhy.core.models import BBox, Block, BlockType, Document, Page, ReadingState, WordPosition, WordTimestamp
from projectwhy.core.player import AudioPlayer
from projectwhy.core.prefetch import Prefetcher
from projectwhy.core.tts.base import TTSEngine


BLOCK_CONFIG: dict[BlockType, dict[str, Any]] = {
    BlockType.DOCUMENT_TITLE: {
        "speak": True,
        "pause_after": 1.0,
        "keep_if_no_words": False,
    },
    BlockType.DOC_TITLE: {
        "speak": True,
        "pause_after": 1.0,
        "keep_if_no_words": False,
    },
    BlockType.PARAGRAPH_TITLE: {
        "speak": True,
        "pause_after": 0.8,
        "keep_if_no_words": False,
    },
    BlockType.TEXT: {"speak": True, "pause_after": 0.3, "keep_if_no_words": False},
    BlockType.CONTENT: {"speak": True, "pause_after": 0.3, "keep_if_no_words": False},
    BlockType.PAGE_NUMBER: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": False,
    },
    BlockType.NUMBER: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": False,
    },
    BlockType.ABSTRACT: {"speak": True, "pause_after": 0.4, "keep_if_no_words": False},
    BlockType.TABLE_OF_CONTENTS: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": False,
    },
    BlockType.REFERENCES: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": False,
    },
    BlockType.FOOTNOTES: {
        "speak": True,
        "pause_after": 0.3,
        "keep_if_no_words": False,
    },
    BlockType.HEADER: {"speak": False, "pause_after": 0.0, "keep_if_no_words": False},
    BlockType.FOOTER: {"speak": False, "pause_after": 0.0, "keep_if_no_words": False},
    BlockType.ALGORITHM: {"speak": True, "pause_after": 0.3, "keep_if_no_words": False},
    BlockType.FORMULA: {"speak": False, "pause_after": 0.0, "keep_if_no_words": True},
    BlockType.FORMULA_NUMBER: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": True,
    },
    BlockType.IMAGE: {"speak": False, "pause_after": 0.0, "keep_if_no_words": True},
    BlockType.FIGURE_CAPTION: {
        "speak": True,
        "pause_after": 0.5,
        "keep_if_no_words": False,
    },
    BlockType.TABLE: {"speak": False, "pause_after": 0.0, "keep_if_no_words": True},
    BlockType.TABLE_CAPTION: {
        "speak": True,
        "pause_after": 0.5,
        "keep_if_no_words": False,
    },
    BlockType.SEAL: {"speak": False, "pause_after": 0.0, "keep_if_no_words": True},
    BlockType.FIGURE_TITLE: {
        "speak": True,
        "pause_after": 0.6,
        "keep_if_no_words": False,
    },
    BlockType.CHART_TITLE: {
        "speak": True,
        "pause_after": 0.6,
        "keep_if_no_words": False,
    },
    BlockType.FIGURE: {"speak": False, "pause_after": 0.0, "keep_if_no_words": True},
    BlockType.CHART: {"speak": False, "pause_after": 0.0, "keep_if_no_words": True},
    BlockType.HEADER_IMAGE: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": True,
    },
    BlockType.FOOTER_IMAGE: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": True,
    },
    BlockType.ASIDE_TEXT: {"speak": True, "pause_after": 0.3, "keep_if_no_words": False},
    BlockType.UNKNOWN: {
        "speak": False,
        "pause_after": 0.0,
        "keep_if_no_words": False,
    },
}


class ReadingSession:
    def __init__(
        self,
        document: Document,
        pdf: pdfium.PdfDocument | None,
        tts: TTSEngine,
        player: AudioPlayer,
        *,
        layout_model: Any,
        pdf_scale: float = 2.0,
    ) -> None:
        self.document = document
        self.pdf = pdf
        self.tts = tts
        self.player = player
        self.layout_model = layout_model
        self.pdf_scale = pdf_scale

        self.page_index = 0
        self.block_index = 0
        self._page_lock = threading.Lock()
        self._tts_lock = threading.Lock()
        self._utterance_done = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self.prefetcher: Prefetcher | None = None

        self._current_timestamps: list[WordTimestamp] | None = None
        self._current_alignment: list[int] | None = None
        self._current_block: Block | None = None

    def _ensure_page(self, idx: int) -> Page:
        if self.document.doc_type != "pdf" or self.pdf is None:
            return self.document.pages[idx]
        with self._page_lock:
            return ensure_pdf_page_loaded(
                self.document,
                idx,
                self.pdf,
                self.layout_model,
                self.pdf_scale,
            )

    def current_page(self) -> Page:
        return self._ensure_page(self.page_index)

    def _ensure_neighbor_pages(self) -> None:
        """Pre-load previous, current, and next PDF pages (all through the page lock)."""
        if self.document.doc_type != "pdf" or self.pdf is None:
            return
        for delta in (-1, 0, 1):
            i = self.page_index + delta
            if 0 <= i < len(self.document.pages):
                self._ensure_page(i)

    def go_to_page(self, page_index: int) -> Page:
        if page_index < 0 or page_index >= len(self.document.pages):
            raise IndexError("page_index out of range")
        self.page_index = page_index
        self.block_index = 0
        page = self._ensure_page(page_index)
        self._ensure_neighbor_pages()
        return page

    def next_page(self) -> Page:
        return self.go_to_page(min(self.page_index + 1, len(self.document.pages) - 1))

    def prev_page(self) -> Page:
        return self.go_to_page(max(self.page_index - 1, 0))

    def get_cursor_block(self) -> Block | None:
        page = self.current_page()
        if not page.blocks:
            return None
        idx = max(0, min(self.block_index, len(page.blocks) - 1))
        return page.blocks[idx]

    def next_block(self) -> None:
        page = self._ensure_page(self.page_index)
        if self.block_index + 1 < len(page.blocks):
            self.block_index += 1
            return
        if self.page_index + 1 < len(self.document.pages):
            self.page_index += 1
            self.block_index = 0
            self._ensure_neighbor_pages()

    def prev_block(self) -> None:
        if self.block_index > 0:
            self.block_index -= 1
            return
        if self.page_index <= 0:
            return
        self.page_index -= 1
        prev = self._ensure_page(self.page_index)
        self.block_index = max(0, len(prev.blocks) - 1)
        self._ensure_neighbor_pages()

    @staticmethod
    def _should_speak(block: Block) -> bool:
        cfg = BLOCK_CONFIG.get(
            block.block_type,
            {"speak": True, "pause_after": 0.3, "keep_if_no_words": False},
        )
        if not block.text.strip() and cfg["speak"]:
            return False
        return bool(cfg["speak"])

    @staticmethod
    def _pause_after_block(block: Block) -> float:
        cfg = BLOCK_CONFIG.get(
            block.block_type,
            {"speak": True, "pause_after": 0.3, "keep_if_no_words": False},
        )
        return float(cfg["pause_after"])

    @staticmethod
    def _build_alignment(block_words: list[WordPosition], word_timestamps: list[WordTimestamp]) -> list[int]:
        """Map each timestamp index to a block.words index via character offsets in space-joined text."""
        if not block_words or not word_timestamps:
            return []

        word_starts: list[int] = []
        pos = 0
        for w in block_words:
            word_starts.append(pos)
            pos += len(w.text) + 1

        block_text = " ".join(w.text for w in block_words)
        mapping: list[int] = []
        search_from = 0

        for wt in word_timestamps:
            tok_pos = block_text.find(wt.text, search_from)
            if tok_pos < 0:
                mapping.append(mapping[-1] if mapping else 0)
                continue
            search_from = tok_pos + len(wt.text)

            wi = 0
            for i, ws in enumerate(word_starts):
                if ws > tok_pos:
                    break
                wi = i
            mapping.append(wi)

        return mapping

    def _on_utterance_done(self) -> None:
        self._utterance_done.set()

    def _playback_loop(self) -> None:
        prefetcher = self.prefetcher
        if prefetcher is None:
            return

        while not self._stop.is_set():
            job = prefetcher.take_next()
            if job is None:
                break

            self.page_index = job.page_index
            self.block_index = job.block_index
            self._current_block = job.block
            self._current_timestamps = (
                job.tts_result.word_timestamps if job.tts_result else None
            )
            self._current_alignment = job.alignment

            if self._stop.is_set():
                break

            self._utterance_done.clear()
            if job.tts_result and job.tts_result.audio is not None and len(job.tts_result.audio) > 0:
                self.player.play(
                    job.tts_result.audio,
                    job.tts_result.sample_rate,
                    on_complete=self._on_utterance_done,
                )
                self._utterance_done.wait(timeout=7200.0)
            else:
                self._on_utterance_done()

            if self._stop.is_set():
                break

            time.sleep(self._pause_after_block(job.block))

        self.player.stop()
        self._current_block = None
        self._current_timestamps = None
        self._current_alignment = None

    def play(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self.prefetcher = Prefetcher(
            self.document,
            self.pdf,
            self.tts,
            layout_model=self.layout_model,
            pdf_scale=self.pdf_scale,
            should_speak=self._should_speak,
            build_alignment=self._build_alignment,
            page_lock=self._page_lock,
            tts_lock=self._tts_lock,
        )
        self.prefetcher.start(self.page_index, self.block_index)
        self._worker = threading.Thread(
            target=self._playback_loop, name="reading-playback", daemon=True,
        )
        self._worker.start()

    def _stop_prefetcher(self) -> None:
        if self.prefetcher is not None:
            self.prefetcher.stop()
            self.prefetcher = None

    def pause(self) -> None:
        """Stop audio and background worker; keeps page/block cursor."""
        self._stop.set()
        self._stop_prefetcher()
        self.player.stop()
        self._utterance_done.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._worker = None
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()
        self._stop_prefetcher()
        self.player.stop()
        self._utterance_done.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._worker = None
        self._stop.clear()

    def skip_block(self) -> None:
        self.player.stop()
        self._utterance_done.set()

    def set_voice(self, voice: str) -> None:
        if hasattr(self.tts, "voice"):
            setattr(self.tts, "voice", voice)

    def set_speed(self, speed: float) -> None:
        if hasattr(self.tts, "speed"):
            setattr(self.tts, "speed", float(speed))

    def get_state(self) -> ReadingState:
        pos = self.player.get_position_sec()
        wi = self._word_index_for_position(pos)
        playing = self.player.is_playing() or (self._worker is not None and self._worker.is_alive())
        return ReadingState(
            page_index=self.page_index,
            block_index=self.block_index,
            word_index=wi,
            is_playing=playing,
            position_sec=pos,
        )

    def _word_index_for_position(self, position_sec: float) -> int | None:
        ts = self._current_timestamps
        block = self._current_block
        alignment = self._current_alignment
        if not ts or not block:
            return None
        for i, wt in enumerate(ts):
            if wt.start_sec <= position_sec < wt.end_sec:
                if alignment and i < len(alignment):
                    return alignment[i]
                return min(i, max(0, len(block.words) - 1))
        if ts and position_sec >= ts[-1].end_sec:
            idx = len(ts) - 1
            if alignment and idx < len(alignment):
                return alignment[idx]
            return min(idx, max(0, len(block.words) - 1))
        return 0 if ts else None

    def get_active_block(self) -> Block | None:
        return self._current_block

    def get_active_word_bbox(self) -> BBox | None:
        st = self.get_state()
        if st.is_playing:
            block = self._current_block
            if block is None:
                return None
            if st.word_index is not None and block.words:
                idx = max(0, min(st.word_index, len(block.words) - 1))
                return block.words[idx].bbox
            return block.bbox
        cursor = self.get_cursor_block()
        return cursor.bbox if cursor else None
