"""Reading session: navigation, playback orchestration, and cursor management."""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np
import pypdfium2 as pdfium

from projectwhy.config import DEFAULT_PDF_TEXT, PdfTextConfig, normalize_highlight_granularity
from projectwhy.core.document import ensure_pdf_page_loaded
from projectwhy.core.models import BBox, Block, BlockType, Document, Page, ReadingState, TTSResult, WordTimestamp
from projectwhy.core.player import AudioPlayer
from projectwhy.core.prefetch import PrefetchWarmer
from projectwhy.core.substitutions import SubstitutionRule, block_tts_parts, block_tts_text
from projectwhy.core.time_stretch import time_stretch
from projectwhy.core.tts.base import TTSEngine
from projectwhy.core.utterance_cache import UtteranceCache

logger = logging.getLogger(__name__)

# Built-in TTS behavior per PP-DocLayout class (overridable via config ``[blocks.types.*]``).
DEFAULT_BLOCK_CONFIG: dict[BlockType, dict[str, Any]] = {
    BlockType.DOCUMENT_TITLE: {"speak": True, "pause_after": 1.0},
    BlockType.DOC_TITLE: {"speak": True, "pause_after": 1.0},
    BlockType.PARAGRAPH_TITLE: {"speak": True, "pause_after": 0.8},
    BlockType.TEXT: {"speak": True, "pause_after": 0.0},
    BlockType.CONTENT: {"speak": True, "pause_after": 0.3},
    BlockType.PAGE_NUMBER: {"speak": False, "pause_after": 0.0},
    BlockType.NUMBER: {"speak": False, "pause_after": 0.0},
    BlockType.ABSTRACT: {"speak": True, "pause_after": 0.4},
    BlockType.TABLE_OF_CONTENTS: {"speak": False, "pause_after": 0.0},
    BlockType.REFERENCES: {"speak": False, "pause_after": 0.0},
    BlockType.FOOTNOTE: {"speak": True, "pause_after": 0.3},
    BlockType.HEADER: {"speak": False, "pause_after": 0.0},
    BlockType.FOOTER: {"speak": False, "pause_after": 0.0},
    BlockType.ALGORITHM: {"speak": True, "pause_after": 0.3},
    BlockType.FORMULA: {"speak": False, "pause_after": 0.0},
    BlockType.FORMULA_NUMBER: {"speak": False, "pause_after": 0.0},
    BlockType.IMAGE: {"speak": False, "pause_after": 0.0},
    BlockType.FIGURE_CAPTION: {"speak": True, "pause_after": 0.5},
    BlockType.TABLE: {"speak": False, "pause_after": 0.0},
    BlockType.TABLE_CAPTION: {"speak": True, "pause_after": 0.5},
    BlockType.SEAL: {"speak": False, "pause_after": 0.0},
    BlockType.FIGURE_TITLE: {"speak": True, "pause_after": 0.6},
    BlockType.CHART_TITLE: {"speak": True, "pause_after": 0.6},
    BlockType.FIGURE: {"speak": False, "pause_after": 0.0},
    BlockType.CHART: {"speak": False, "pause_after": 0.0},
    BlockType.HEADER_IMAGE: {"speak": False, "pause_after": 0.0},
    BlockType.FOOTER_IMAGE: {"speak": False, "pause_after": 0.0},
    BlockType.ASIDE_TEXT: {"speak": True, "pause_after": 0.3},
    BlockType.UNKNOWN: {"speak": False, "pause_after": 0.0},
}


def merged_block_config(overrides: dict[str, dict[str, Any]] | None) -> dict[BlockType, dict[str, Any]]:
    """Return full block settings: defaults plus optional per-type overrides from config."""
    o = overrides or {}
    result: dict[BlockType, dict[str, Any]] = {
        bt: {"speak": bool(d["speak"]), "pause_after": float(d["pause_after"])}
        for bt, d in DEFAULT_BLOCK_CONFIG.items()
    }
    for key, row in o.items():
        try:
            bt = BlockType(key)
        except ValueError:
            continue
        if bt not in result:
            result[bt] = {"speak": True, "pause_after": 0.0}
        if not isinstance(row, dict):
            continue
        if "speak" in row:
            result[bt]["speak"] = bool(row["speak"])
        if "pause_after" in row:
            result[bt]["pause_after"] = float(row["pause_after"])
    return result


def speak_heuristic(block: Block, block_config: dict[BlockType, dict[str, Any]]) -> bool:
    """Whether *block* would be spoken given *block_config* (same rules as ``ReadingSession``)."""
    cfg = block_config.get(
        block.block_type,
        {"speak": True, "pause_after": 0.3},
    )
    if not block.text.strip() and cfg["speak"]:
        return False
    return bool(cfg["speak"])


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
        tts_cache_max_entries: int = 64,
        prefetch_lookahead: int = 3,
        playback_speed: float = 1.0,
        pdf_text: PdfTextConfig | None = None,
        block_config: dict[BlockType, dict[str, Any]] | None = None,
        substitution_rules: list[SubstitutionRule] | None = None,
        highlight_granularity: str = "word",
    ) -> None:
        self.document = document
        self.pdf = pdf
        self.tts = tts
        self.player = player
        self.layout_model = layout_model
        self.pdf_scale = pdf_scale
        self._pdf_text = pdf_text or DEFAULT_PDF_TEXT
        self._block_config = block_config or merged_block_config({})
        self._substitution_rules: list[SubstitutionRule] = substitution_rules or []
        self._highlight_granularity = normalize_highlight_granularity(highlight_granularity)
        self._prefetch_lookahead = prefetch_lookahead
        self._speed_lock = threading.Lock()
        self._playback_speed = float(playback_speed)

        # Cursor: protected by _cursor_lock; _cursor_gen bumped on every user-initiated move
        self._cursor_lock = threading.Lock()
        self._cursor_gen = 0
        self.page_index = 0
        self.block_index = 0

        self._page_lock = threading.Lock()
        self._tts_lock = threading.Lock()
        self._tts_cache = UtteranceCache(tts, self._tts_lock, max_entries=tts_cache_max_entries)

        self._utterance_done = threading.Event()
        self._stop = threading.Event()
        self._paused = False
        self._resume_event = threading.Event()
        self._resume_event.set()
        self._worker: threading.Thread | None = None
        self.warmer: PrefetchWarmer | None = None

        self._skip_current = False

        # Playback tracking (for word-level highlights)
        self._current_timestamps: list[WordTimestamp] | None = None
        self._current_alignment: list[int] | None = None
        self._current_block: Block | None = None
        self._current_pi: int | None = None
        self._current_bi: int | None = None

        # (page_index, block_index, word_index) — consumed when that block plays
        self._pending_word_seek: tuple[int, int, int] | None = None

    # -- page loading --------------------------------------------------------

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
                pdf_text=self._pdf_text,
            )

    def current_page(self) -> Page:
        return self._ensure_page(self.page_index)

    def _ensure_neighbor_pages(self) -> None:
        if self.document.doc_type != "pdf" or self.pdf is None:
            return
        pi = self.page_index
        for delta in (-1, 0, 1):
            i = pi + delta
            if 0 <= i < len(self.document.pages):
                self._ensure_page(i)

    # -- cursor management ---------------------------------------------------

    def _get_cursor_snapshot(self) -> tuple[int, int, int]:
        """Return (page_index, block_index, cursor_gen) atomically. Safe to call from any thread."""
        with self._cursor_lock:
            return self.page_index, self.block_index, self._cursor_gen

    def _move_cursor(self, pi: int, bi: int) -> None:
        """Atomically write cursor and bump generation. Call from GUI thread only."""
        with self._cursor_lock:
            self._cursor_gen += 1
            self.page_index = pi
            self.block_index = bi
            self._pending_word_seek = None
        if self.warmer is not None:
            self.warmer.notify()

    # -- speakable navigation ------------------------------------------------

    def _find_speakable_at_or_after(self, pi: int, bi: int) -> tuple[int, int] | None:
        """Return first speakable block at or after (pi, bi), loading pages as needed."""
        n_pages = len(self.document.pages)
        while pi < n_pages:
            page = self._ensure_page(pi)
            while bi < len(page.blocks):
                if self._should_speak(page.blocks[bi]):
                    return pi, bi
                bi += 1
            pi += 1
            bi = 0
        return None

    def _find_speakable_before(self, pi: int, bi: int) -> tuple[int, int] | None:
        """Return last speakable block strictly before (pi, bi), loading pages as needed."""
        cur_pi, cur_bi = pi, bi - 1
        while cur_pi >= 0:
            if cur_bi < 0:
                cur_pi -= 1
                if cur_pi < 0:
                    return None
                page = self._ensure_page(cur_pi)
                cur_bi = len(page.blocks) - 1
                if cur_bi < 0:
                    continue
            else:
                page = self._ensure_page(cur_pi)
            if self._should_speak(page.blocks[cur_bi]):
                return cur_pi, cur_bi
            cur_bi -= 1
        return None

    def next_speakable_block(self) -> bool:
        """Advance cursor to the next speakable block. Bumps cursor generation. Returns False at EOF."""
        with self._cursor_lock:
            pi, bi = self.page_index, self.block_index
        pos = self._find_speakable_at_or_after(pi, bi + 1)
        if pos is None:
            return False
        self._move_cursor(*pos)
        self._ensure_neighbor_pages()
        return True

    def prev_speakable_block(self) -> bool:
        """Retreat cursor to the previous speakable block. Bumps cursor generation. Returns False at start."""
        with self._cursor_lock:
            pi, bi = self.page_index, self.block_index
        pos = self._find_speakable_before(pi, bi)
        if pos is None:
            return False
        self._move_cursor(*pos)
        self._ensure_neighbor_pages()
        return True

    def interrupt_playback(self) -> None:
        """Stop current audio immediately. The playback loop detects the cursor change and re-reads."""
        self.player.stop()
        self._utterance_done.set()

    def play_from_pdf_word(self, page_index: int, block_index: int, word_index: int) -> bool:
        """Move to the given block and start playback at *word_index* (PDF only; Ctrl+click in the GUI)."""
        if self.document.doc_type != "pdf":
            return False
        page = self._ensure_page(page_index)
        if block_index >= len(page.blocks):
            return False
        block = page.blocks[block_index]
        if not self._should_speak(block):
            return False
        if word_index < 0 or word_index >= len(block.words):
            return False

        if self._paused:
            self._paused = False
            self._resume_event.set()

        with self._cursor_lock:
            self._cursor_gen += 1
            self.page_index = page_index
            self.block_index = block_index
            self._pending_word_seek = (page_index, block_index, word_index)
        if self.warmer is not None:
            self.warmer.notify()
        self._ensure_neighbor_pages()

        if self._worker is not None and self._worker.is_alive():
            self.interrupt_playback()
        else:
            self.play()
        return True

    def play_from_pdf_block(self, page_index: int, block_index: int) -> bool:
        """Move to the given block and start playback from the start of the utterance (PDF only)."""
        if self.document.doc_type != "pdf":
            return False
        page = self._ensure_page(page_index)
        if block_index >= len(page.blocks):
            return False
        block = page.blocks[block_index]
        if not self._should_speak(block):
            return False

        if self._paused:
            self._paused = False
            self._resume_event.set()

        with self._cursor_lock:
            self._cursor_gen += 1
            self.page_index = page_index
            self.block_index = block_index
            self._pending_word_seek = None
        if self.warmer is not None:
            self.warmer.notify()
        self._ensure_neighbor_pages()

        if self._worker is not None and self._worker.is_alive():
            self.interrupt_playback()
        else:
            self.play()
        return True

    # -- page navigation -----------------------------------------------------

    def go_to_page(self, page_index: int) -> Page:
        if page_index < 0 or page_index >= len(self.document.pages):
            raise IndexError("page_index out of range")
        page = self._ensure_page(page_index)
        # Snap block_index to the first speakable block on this page (fall back to 0)
        pos = self._find_speakable_at_or_after(page_index, 0)
        new_bi = pos[1] if pos is not None and pos[0] == page_index else 0
        self._move_cursor(page_index, new_bi)
        self._ensure_neighbor_pages()
        return page

    def go_to_position(self, page_index: int, block_index: int) -> Page:
        """Navigate to *page_index* honoring *block_index* where possible.

        Calls ``go_to_page`` first (which sets the cursor to the first speakable
        block), then tries to advance to *block_index* if it is in range.  If
        nothing speakable exists at or after *block_index* on the same page the
        cursor stays at whatever ``go_to_page`` chose, so this always succeeds.
        """
        page = self.go_to_page(page_index)
        if 0 <= block_index < len(page.blocks):
            pos = self._find_speakable_at_or_after(page_index, block_index)
            if pos is not None and pos[0] == page_index:
                self._move_cursor(page_index, pos[1])
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

    # -- block type helpers --------------------------------------------------

    def would_speak(self, block: Block) -> bool:
        return speak_heuristic(block, self._block_config)

    def _should_speak(self, block: Block) -> bool:
        return self.would_speak(block)

    def _pause_after_block(self, block: Block) -> float:
        cfg = self._block_config.get(
            block.block_type,
            {"speak": True, "pause_after": 0.3},
        )
        return float(cfg["pause_after"])

    @staticmethod
    def _build_alignment(tts_parts: list[str], word_timestamps: list[WordTimestamp]) -> list[int]:
        """Map each timestamp index to a block.words index via character offsets in the TTS string.

        tts_parts[i] is the (possibly substituted) string for block.words[i], so word_starts
        are computed from these parts rather than the raw PDF tokens. Kokoro tokens that expand
        from a single word slot (e.g. "Carbon", "Dioxide" from "CO2") both map to the same index.
        """
        if not tts_parts or not word_timestamps:
            return []

        word_starts: list[int] = []
        pos = 0
        for part in tts_parts:
            word_starts.append(pos)
            pos += len(part) + 1

        tts_text = " ".join(tts_parts)
        mapping: list[int] = []
        search_from = 0

        for wt in word_timestamps:
            tok_pos = tts_text.find(wt.text, search_from)
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

    @staticmethod
    def _start_sec_for_word_index(
        scaled_ts: list[WordTimestamp] | None,
        alignment: list[int],
        word_index: int,
        audio_duration_sec: float,
    ) -> float:
        """Map a ``block.words`` index to audio start time using TTS alignment."""
        if not scaled_ts or not alignment or word_index < 0:
            return 0.0
        start = 0.0
        matched = False
        for i, wi in enumerate(alignment):
            if i >= len(scaled_ts):
                break
            if wi == word_index:
                start = scaled_ts[i].start_sec
                matched = True
                break
        if not matched:
            n = min(len(alignment), len(scaled_ts))
            for i in range(n - 1, -1, -1):
                if alignment[i] <= word_index:
                    start = scaled_ts[i].start_sec
                    break
        eps = 1e-4
        hi = max(0.0, audio_duration_sec - eps)
        return max(0.0, min(float(start), hi))

    @staticmethod
    def _scale_word_timestamps(ts: list[WordTimestamp], speed: float) -> list[WordTimestamp]:
        if abs(speed - 1.0) < 1e-6:
            return ts
        inv = 1.0 / speed
        return [
            WordTimestamp(text=w.text, start_sec=w.start_sec * inv, end_sec=w.end_sec * inv) for w in ts
        ]

    def _prepare_playback_audio(
        self, result: TTSResult
    ) -> tuple[np.ndarray, int, list[WordTimestamp] | None]:
        """Rubber Band time-stretch and timestamps aligned to the played buffer."""
        if result is None or result.audio is None or len(result.audio) == 0:
            return np.array([], dtype=np.float32), 24000, None
        with self._speed_lock:
            speed = self._playback_speed
        raw = np.asarray(result.audio, dtype=np.float32).reshape(-1)
        stretched = time_stretch(raw, result.sample_rate, speed)
        ts = result.word_timestamps
        scaled_ts = self._scale_word_timestamps(ts, speed) if ts else None
        return stretched, result.sample_rate, scaled_ts

    # -- playback internals --------------------------------------------------

    def _on_utterance_done(self) -> None:
        self._utterance_done.set()

    def _wait_if_paused(self) -> bool:
        """Block while paused. Returns False if stopped."""
        while not self._resume_event.is_set() and not self._stop.is_set():
            self._resume_event.wait(timeout=0.2)
        return not self._stop.is_set()

    def _maybe_restart_current_utt_for_speed(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            return
        if not (self.player.is_playing() or self.player.is_paused()):
            return
        self._skip_current = True
        self.player.stop()
        self._utterance_done.set()

    def _playback_loop(self) -> None:
        # Deferred auto-advance: computed at natural block end, committed only
        # at the TOP of the next iteration — right before the new block starts
        # synthesizing.  Until then the shared cursor stays on the block that
        # just played, so GUI navigation reads the correct "current" position.
        pending_pi: int | None = None
        pending_bi: int | None = None
        pending_gen: int = -1

        while not self._stop.is_set():
            if not self._wait_if_paused():
                break

            with self._cursor_lock:
                if pending_pi is not None and self._cursor_gen == pending_gen:
                    self.page_index = pending_pi
                    self.block_index = pending_bi
                pending_pi = pending_bi = None
                pi, bi, gen = self.page_index, self.block_index, self._cursor_gen

            if self.warmer is not None:
                self.warmer.notify()

            try:
                page = self._ensure_page(pi)
            except Exception:
                logger.exception("playback: failed to load page %d", pi)
                break
            if bi >= len(page.blocks):
                pos = self._find_speakable_at_or_after(pi, 0)
                if pos is None:
                    break
                with self._cursor_lock:
                    if self._cursor_gen != gen:
                        continue
                    self.page_index, self.block_index = pos
                continue
            block = page.blocks[bi]
            tts_parts = block_tts_parts(block, self._substitution_rules)
            tts_text = block_tts_text(tts_parts)

            with self._cursor_lock:
                if self._cursor_gen != gen:
                    continue

            try:
                tts_result = self._tts_cache.get_or_synthesize(tts_text)
            except Exception:
                logger.exception("playback: synthesis failed for block (%d, %d)", pi, bi)
                next_pos = self._find_speakable_at_or_after(pi, bi + 1)
                with self._cursor_lock:
                    if self._cursor_gen != gen:
                        continue
                    if next_pos is None:
                        break
                    self.page_index, self.block_index = next_pos
                continue

            audio_out, sr_out, ts_out = self._prepare_playback_audio(tts_result)
            alignment = self._build_alignment(tts_parts, tts_result.word_timestamps or [])

            utterance_start_sec = 0.0
            with self._cursor_lock:
                if self._cursor_gen != gen:
                    continue
                pw = self._pending_word_seek
                if pw is not None:
                    ppi, pbi, pwi = pw
                    if ppi == pi and pbi == bi:
                        self._pending_word_seek = None
                        dur = len(audio_out) / float(sr_out) if sr_out > 0 else 0.0
                        utterance_start_sec = self._start_sec_for_word_index(
                            ts_out, alignment, pwi, dur
                        )
                    else:
                        self._pending_word_seek = None

            self._current_block = block
            self._current_pi = pi
            self._current_bi = bi
            self._current_alignment = alignment
            self._current_timestamps = ts_out

            self._skip_current = False
            self._utterance_done.clear()
            if audio_out is not None and len(audio_out) > 0:
                self.player.play(
                    audio_out,
                    sr_out,
                    self._on_utterance_done,
                    start_sec=utterance_start_sec,
                )
                self._utterance_done.wait(timeout=7200.0)
            else:
                self._on_utterance_done()

            if self._stop.is_set():
                break

            with self._cursor_lock:
                if self._cursor_gen != gen:
                    continue

            if self._skip_current:
                self._skip_current = False
                continue

            next_pos = self._find_speakable_at_or_after(pi, bi + 1)
            if next_pos is None:
                break

            pending_pi, pending_bi = next_pos
            pending_gen = gen

            pause = self._pause_after_block(block)
            if pause > 0:
                self._utterance_done.clear()
                self._utterance_done.wait(timeout=pause)

        # Cleanup
        self.player.stop()
        self._current_block = None
        self._current_pi = None
        self._current_bi = None
        self._current_timestamps = None
        self._current_alignment = None

    # -- public playback API -------------------------------------------------

    def play(self) -> None:
        if self._paused:
            self._paused = False
            self._resume_event.set()
            self.player.resume()
            return
        if self._worker is not None and self._worker.is_alive():
            return
        self._stop.clear()
        self._paused = False
        self._resume_event.set()
        self._skip_current = False

        self.warmer = PrefetchWarmer(
            self.document,
            self.pdf,
            layout_model=self.layout_model,
            pdf_scale=self.pdf_scale,
            pdf_text=self._pdf_text,
            should_speak=self._should_speak,
            get_tts_text=self.get_tts_text_for_block,
            page_lock=self._page_lock,
            cache=self._tts_cache,
            get_cursor=self._get_cursor_snapshot,
            lookahead=self._prefetch_lookahead,
        )
        self.warmer.start()

        self._worker = threading.Thread(
            target=self._playback_loop, name="reading-playback", daemon=True,
        )
        self._worker.start()

    def pause(self) -> None:
        """Pause audio playback; worker and warmer stay alive for fast resume."""
        self._paused = True
        self._resume_event.clear()
        self.player.pause()

    def stop(self) -> None:
        with self._cursor_lock:
            self._pending_word_seek = None
        self.player.stop()
        self._paused = False
        self._resume_event.set()
        self._stop.set()
        self._utterance_done.set()
        self._stop_warmer()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
        self._worker = None
        self._stop.clear()
        self._skip_current = False

    def _stop_warmer(self) -> None:
        if self.warmer is not None:
            self.warmer.stop()
            self.warmer = None

    @property
    def is_active(self) -> bool:
        """True when the playback worker is alive (playing or paused mid-playback)."""
        return self._worker is not None and self._worker.is_alive()

    # -- settings ------------------------------------------------------------

    def set_playback_settings(
        self, tts_cache_max_entries: int, prefetch_lookahead: int, playback_speed: float
    ) -> None:
        """Update cache size, prefetch depth, and playback speed from settings."""
        self._prefetch_lookahead = prefetch_lookahead
        self._tts_cache.update_max_entries(tts_cache_max_entries)
        if self.warmer is not None:
            self.warmer.update_lookahead(prefetch_lookahead)
        with self._speed_lock:
            old = self._playback_speed
            self._playback_speed = float(playback_speed)
        if old != float(playback_speed):
            self._maybe_restart_current_utt_for_speed()

    def set_pdf_text(self, pdf_text: PdfTextConfig) -> None:
        self._pdf_text = pdf_text
        if self.warmer is not None:
            self.warmer.set_pdf_text(pdf_text)

    def set_block_config(self, block_config: dict[BlockType, dict[str, Any]]) -> None:
        self._block_config = block_config

    def set_substitution_rules(self, rules: list[SubstitutionRule]) -> None:
        self._substitution_rules = rules
        self._tts_cache.clear()

    def set_highlight_granularity(self, mode: str) -> None:
        self._highlight_granularity = normalize_highlight_granularity(mode)

    def set_tts_engine(self, tts: TTSEngine) -> None:
        self.stop()
        self.tts = tts
        self._tts_cache.replace_tts(tts)

    def get_tts_text_for_block(self, block: Block) -> str:
        return block_tts_text(block_tts_parts(block, self._substitution_rules))

    def set_voice(self, voice: str) -> None:
        if hasattr(self.tts, "voice"):
            setattr(self.tts, "voice", voice)
        self._tts_cache.clear()

    def set_speed(self, speed: float) -> None:
        with self._speed_lock:
            self._playback_speed = float(speed)
        self._maybe_restart_current_utt_for_speed()

    # -- state queries -------------------------------------------------------

    def get_state(self) -> ReadingState:
        pos = self.player.get_position_sec()
        wi = (
            None
            if self._highlight_granularity == "block"
            else self._word_index_for_position(pos)
        )
        playing = not self._paused and (self.player.is_playing() or self.is_active)
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
        with self._cursor_lock:
            cursor_pi, cursor_bi = self.page_index, self.block_index

        cursor_block = self.get_cursor_block()
        if cursor_block is None:
            return None

        if self._highlight_granularity == "block":
            return cursor_block.bbox

        # Word-level tracking only when audio is playing for exactly the cursor block
        if (
            self.player.is_playing()
            and self._current_pi == cursor_pi
            and self._current_bi == cursor_bi
            and self._current_timestamps is not None
            and cursor_block.words
        ):
            pos = self.player.get_position_sec()
            wi = self._word_index_for_position(pos)
            if wi is not None:
                idx = max(0, min(wi, len(cursor_block.words) - 1))
                return cursor_block.words[idx].bbox

        return cursor_block.bbox
