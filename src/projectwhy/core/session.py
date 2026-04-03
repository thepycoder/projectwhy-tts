"""Reading session: navigation + playback orchestration."""

from __future__ import annotations

import threading
import time
from typing import Any

import pypdfium2 as pdfium

from projectwhy.core.document import ensure_pdf_neighbor_pages_loaded, ensure_pdf_page_loaded
from projectwhy.core.models import BBox, Block, BlockType, Document, Page, ReadingState
from projectwhy.core.player import AudioPlayer
from projectwhy.core.tts.base import TTSEngine


BLOCK_CONFIG: dict[BlockType, dict[str, Any]] = {
    BlockType.TITLE: {"speak": True, "pause_after": 1.0},
    BlockType.TEXT: {"speak": True, "pause_after": 0.3},
    BlockType.FIGURE: {"speak": False, "pause_after": 0.0},
    BlockType.FIGURE_CAPTION: {"speak": True, "pause_after": 0.5},
    BlockType.TABLE: {"speak": False, "pause_after": 0.0},
    BlockType.TABLE_CAPTION: {"speak": True, "pause_after": 0.5},
    BlockType.HEADER: {"speak": False, "pause_after": 0.0},
    BlockType.FOOTER: {"speak": False, "pause_after": 0.0},
    BlockType.EQUATION: {"speak": False, "pause_after": 0.0},
    BlockType.REFERENCE: {"speak": False, "pause_after": 0.0},
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
        layout_conf: float = 0.25,
        layout_imgsz: int = 1024,
    ) -> None:
        self.document = document
        self.pdf = pdf
        self.tts = tts
        self.player = player
        self.layout_model = layout_model
        self.pdf_scale = pdf_scale
        self.layout_conf = layout_conf
        self.layout_imgsz = layout_imgsz

        self.page_index = 0
        self.block_index = 0
        self._lock = threading.Lock()
        self._utterance_done = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

        self._current_timestamps: list | None = None
        self._current_block: Block | None = None

    def _ensure_page(self, idx: int) -> Page:
        if self.document.doc_type != "pdf" or self.pdf is None:
            return self.document.pages[idx]
        return ensure_pdf_page_loaded(
            self.document,
            idx,
            self.pdf,
            self.layout_model,
            self.pdf_scale,
            self.layout_conf,
            self.layout_imgsz,
        )

    def current_page(self) -> Page:
        return self._ensure_page(self.page_index)

    def go_to_page(self, page_index: int) -> Page:
        if page_index < 0 or page_index >= len(self.document.pages):
            raise IndexError("page_index out of range")
        self.page_index = page_index
        self.block_index = 0
        page = self._ensure_page(page_index)
        if self.document.doc_type == "pdf" and self.pdf is not None:
            ensure_pdf_neighbor_pages_loaded(
                self.document,
                page_index,
                self.pdf,
                self.layout_model,
                self.pdf_scale,
                self.layout_conf,
                self.layout_imgsz,
            )
        return page

    def next_page(self) -> Page:
        return self.go_to_page(min(self.page_index + 1, len(self.document.pages) - 1))

    def prev_page(self) -> Page:
        return self.go_to_page(max(self.page_index - 1, 0))

    @staticmethod
    def _should_speak(block: Block) -> bool:
        cfg = BLOCK_CONFIG.get(block.block_type, {"speak": True, "pause_after": 0.3})
        if not block.text.strip() and cfg["speak"]:
            return False
        return bool(cfg["speak"])

    @staticmethod
    def _pause_after_block(block: Block) -> float:
        cfg = BLOCK_CONFIG.get(block.block_type, {"speak": True, "pause_after": 0.3})
        return float(cfg["pause_after"])

    def _advance_to_next_speakable(self, page: Page) -> bool:
        """Increment block_index to next speakable block; flip page if needed. Returns False if end."""
        while True:
            while self.block_index < len(page.blocks):
                b = page.blocks[self.block_index]
                if self._should_speak(b):
                    return True
                self.block_index += 1

            if self.page_index + 1 >= len(self.document.pages):
                return False

            self.page_index += 1
            self.block_index = 0
            page = self._ensure_page(self.page_index)

    def _on_utterance_done(self) -> None:
        self._utterance_done.set()

    def _playback_loop(self) -> None:
        while not self._stop.is_set():
            page = self._ensure_page(self.page_index)
            if not self._advance_to_next_speakable(page):
                break

            page = self._ensure_page(self.page_index)
            block = page.blocks[self.block_index]
            self._current_block = block
            self._current_timestamps = None

            res = self.tts.synthesize(block.text)
            self._current_timestamps = res.word_timestamps

            if self._stop.is_set():
                break

            self._utterance_done.clear()
            if res.audio is not None and len(res.audio) > 0:
                self.player.play(res.audio, res.sample_rate, on_complete=self._on_utterance_done)
                self._utterance_done.wait(timeout=7200.0)
            else:
                self._on_utterance_done()

            if self._stop.is_set():
                break

            time.sleep(self._pause_after_block(block))
            self.block_index += 1

        self.player.stop()
        self._current_block = None
        self._current_timestamps = None

    def play(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._worker = threading.Thread(target=self._playback_loop, name="reading-playback", daemon=True)
        self._worker.start()

    def pause(self) -> None:
        """Stop audio and background worker; keeps page/block cursor."""
        self._stop.set()
        self.player.stop()
        self._utterance_done.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._worker = None
        self._stop.clear()

    def stop(self) -> None:
        self._stop.set()
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
        if not ts or not block:
            return None
        for i, wt in enumerate(ts):
            if wt.start_sec <= position_sec < wt.end_sec:
                return min(i, max(0, len(block.words) - 1))
        if ts and position_sec >= ts[-1].end_sec:
            return min(len(ts) - 1, max(0, len(block.words) - 1))
        return 0 if ts else None

    def get_active_block(self) -> Block | None:
        return self._current_block

    def get_active_word_bbox(self) -> BBox | None:
        st = self.get_state()
        block = self._current_block
        if block is None or st.word_index is None:
            return block.bbox if block else None
        idx = st.word_index
        if not block.words:
            return block.bbox
        idx = max(0, min(idx, len(block.words) - 1))
        return block.words[idx].bbox
