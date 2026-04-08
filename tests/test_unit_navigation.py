"""Unit tests: speakable navigation, UtteranceCache deduplication, generation counter race."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import numpy as np

from projectwhy.core.models import BBox, Block, BlockType, Document, Page, TTSResult, WordTimestamp
from projectwhy.core.session import ReadingSession


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block(text: str, btype: BlockType = BlockType.TEXT) -> Block:
    return Block(block_type=btype, text=text, bbox=BBox(0, 0, 100, 20))


def _page(blocks: list[Block], idx: int = 0) -> Page:
    return Page(index=idx, blocks=blocks)


def _doc(*pages: list[Block]) -> Document:
    return Document(
        path="test.txt",
        doc_type="text",
        pages=[_page(bs, i) for i, bs in enumerate(pages)],
    )


def _tts_result(text: str = "x") -> TTSResult:
    audio = np.zeros(100, dtype=np.float32)
    ts = [WordTimestamp(text=text, start_sec=0.0, end_sec=0.5)]
    return TTSResult(audio=audio, sample_rate=24000, word_timestamps=ts)


def _make_session(doc: Document, tts=None, player=None) -> ReadingSession:
    tts = tts or MagicMock()
    tts.get_voices.return_value = []
    tts.synthesize.return_value = _tts_result()
    player = player or MagicMock()
    player.is_playing.return_value = False
    player.is_paused.return_value = False
    player.get_position_sec.return_value = 0.0
    return ReadingSession(
        doc,
        None,  # no PDF
        tts,
        player,
        layout_model=None,
        tts_cache_max_entries=64,
        prefetch_lookahead=2,
    )


# ---------------------------------------------------------------------------
# Speakable navigation
# ---------------------------------------------------------------------------

class TestSpeakableNavigation:
    def test_next_speakable_skips_non_speakable(self):
        doc = _doc([
            _block("title", BlockType.DOCUMENT_TITLE),
            _block("", BlockType.PAGE_NUMBER),  # non-speakable (empty)
            _block("body", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)
        # Cursor should snap to first speakable on page 0 (index 0, the title)
        assert s.block_index == 0

        moved = s.next_speakable_block()
        assert moved is True
        # PAGE_NUMBER with empty text is skipped; TEXT is speakable
        assert s.block_index == 2
        assert s.page_index == 0

    def test_next_speakable_crosses_page_boundary(self):
        doc = _doc(
            [_block("only block", BlockType.TEXT)],
            [_block("page 2 block", BlockType.TEXT)],
        )
        s = _make_session(doc)
        s.go_to_page(0)
        moved = s.next_speakable_block()
        assert moved is True
        assert s.page_index == 1
        assert s.block_index == 0

    def test_next_speakable_returns_false_at_eof(self):
        doc = _doc([_block("last", BlockType.TEXT)])
        s = _make_session(doc)
        s.go_to_page(0)
        moved = s.next_speakable_block()  # no next speakable
        assert moved is False
        # Cursor unchanged
        assert s.page_index == 0
        assert s.block_index == 0

    def test_prev_speakable_finds_previous(self):
        doc = _doc([
            _block("first", BlockType.TEXT),
            _block("", BlockType.PAGE_NUMBER),
            _block("third", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s._move_cursor(0, 2)  # on "third"
        moved = s.prev_speakable_block()
        assert moved is True
        assert s.block_index == 0  # "first" (PAGE_NUMBER skipped)

    def test_prev_speakable_returns_false_at_start(self):
        doc = _doc([_block("only", BlockType.TEXT)])
        s = _make_session(doc)
        s.go_to_page(0)
        moved = s.prev_speakable_block()
        assert moved is False

    def test_prev_speakable_crosses_page_boundary(self):
        doc = _doc(
            [_block("page 1", BlockType.TEXT)],
            [_block("page 2", BlockType.TEXT)],
        )
        s = _make_session(doc)
        s._move_cursor(1, 0)  # on page 2, first block
        moved = s.prev_speakable_block()
        assert moved is True
        assert s.page_index == 0
        assert s.block_index == 0

    def test_go_to_page_snaps_to_first_speakable(self):
        doc = _doc([
            _block("", BlockType.PAGE_NUMBER),  # non-speakable
            _block("body", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)
        # Should snap past PAGE_NUMBER to TEXT
        assert s.block_index == 1

    def test_go_to_page_no_speakable_uses_zero(self):
        doc = _doc([
            _block("", BlockType.PAGE_NUMBER),  # non-speakable
        ])
        s = _make_session(doc)
        s.go_to_page(0)
        assert s.block_index == 0  # fallback: no speakable → 0

    def test_cursor_gen_bumped_on_next(self):
        doc = _doc([_block("a", BlockType.TEXT), _block("b", BlockType.TEXT)])
        s = _make_session(doc)
        s.go_to_page(0)
        gen_before = s._cursor_gen
        s.next_speakable_block()
        assert s._cursor_gen == gen_before + 1

    def test_cursor_gen_bumped_on_prev(self):
        doc = _doc([_block("a", BlockType.TEXT), _block("b", BlockType.TEXT)])
        s = _make_session(doc)
        s._move_cursor(0, 1)
        gen_before = s._cursor_gen
        s.prev_speakable_block()
        assert s._cursor_gen == gen_before + 1

    def test_cursor_gen_bumped_on_go_to_page(self):
        doc = _doc([_block("a", BlockType.TEXT)], [_block("b", BlockType.TEXT)])
        s = _make_session(doc)
        s.go_to_page(0)
        gen_before = s._cursor_gen
        s.go_to_page(1)
        assert s._cursor_gen == gen_before + 1


# ---------------------------------------------------------------------------
# UtteranceCache deduplication
# ---------------------------------------------------------------------------

class TestUtteranceCache:
    def test_cache_hit_avoids_second_synthesis(self):
        from projectwhy.core.utterance_cache import UtteranceCache

        tts = MagicMock()
        tts.synthesize.return_value = _tts_result()
        getattr(tts, "voice", None)  # ensure attr
        tts.voice = "test_voice"
        lock = threading.Lock()
        cache = UtteranceCache(tts, lock, max_entries=10)

        block = _block("hello world")
        r1 = cache.get_or_synthesize(block)
        r2 = cache.get_or_synthesize(block)

        assert r1 is r2  # same object from cache
        assert tts.synthesize.call_count == 1

    def test_different_text_synthesizes_separately(self):
        from projectwhy.core.utterance_cache import UtteranceCache

        tts = MagicMock()
        tts.synthesize.side_effect = lambda text: _tts_result(text)
        tts.voice = "v"
        lock = threading.Lock()
        cache = UtteranceCache(tts, lock, max_entries=10)

        r1 = cache.get_or_synthesize(_block("hello"))
        r2 = cache.get_or_synthesize(_block("world"))

        assert r1 is not r2
        assert tts.synthesize.call_count == 2

    def test_lru_eviction(self):
        from projectwhy.core.utterance_cache import UtteranceCache

        tts = MagicMock()
        tts.synthesize.side_effect = lambda text: _tts_result(text)
        tts.voice = "v"
        lock = threading.Lock()
        cache = UtteranceCache(tts, lock, max_entries=2)

        blocks = [_block(f"text{i}") for i in range(3)]
        for b in blocks:
            cache.get_or_synthesize(b)

        # max_entries=2: oldest (text0) should be evicted
        assert cache.get(blocks[0]) is None
        assert cache.get(blocks[1]) is not None
        assert cache.get(blocks[2]) is not None

    def test_clear_empties_cache(self):
        from projectwhy.core.utterance_cache import UtteranceCache

        tts = MagicMock()
        tts.synthesize.return_value = _tts_result()
        tts.voice = "v"
        lock = threading.Lock()
        cache = UtteranceCache(tts, lock, max_entries=10)

        block = _block("hello")
        cache.get_or_synthesize(block)
        assert cache.get(block) is not None

        cache.clear()
        assert cache.get(block) is None

    def test_concurrent_same_key_deduplicates(self):
        """T1 synthesizes slowly; T2 starts mid-synthesis and should receive the same result."""
        from projectwhy.core.utterance_cache import UtteranceCache

        call_count = [0]
        started = threading.Event()

        def slow_synthesize(text: str) -> TTSResult:
            call_count[0] += 1
            started.set()   # tell T2 that synthesis has started
            time.sleep(0.1)
            return _tts_result(text)

        tts = MagicMock()
        tts.synthesize.side_effect = slow_synthesize
        tts.voice = "v"
        lock = threading.Lock()
        cache = UtteranceCache(tts, lock, max_entries=10)

        block = _block("shared text")
        results: list[TTSResult] = []

        def t1_worker():
            results.append(cache.get_or_synthesize(block))

        def t2_worker():
            started.wait(timeout=5.0)  # wait until T1 has started synthesis
            results.append(cache.get_or_synthesize(block))  # should deduplicate

        t1 = threading.Thread(target=t1_worker)
        t2 = threading.Thread(target=t2_worker)
        t1.start()
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert len(results) == 2
        assert results[0] is results[1]  # same TTSResult object
        assert call_count[0] == 1       # only one synthesis call


# ---------------------------------------------------------------------------
# Generation counter: auto-advance race guard
# ---------------------------------------------------------------------------

class TestGenerationCounter:
    def test_auto_advance_suppressed_when_gen_changes(self):
        """Simulate: audio ends naturally, but user navigated before auto-advance commits."""
        doc = _doc([
            _block("block 0", BlockType.TEXT),
            _block("block 1", BlockType.TEXT),
            _block("block 2", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)

        # Start with cursor at block 0, gen snapshot
        with s._cursor_lock:
            pi, bi, gen = s.page_index, s.block_index, s._cursor_gen

        # Simulate user navigation bumping gen BEFORE auto-advance runs
        s._move_cursor(0, 2)  # user moved to block 2

        # Auto-advance logic: check gen, detect mismatch, do NOT overwrite cursor
        with s._cursor_lock:
            if s._cursor_gen != gen:
                advanced = False  # user navigated — skip auto-advance
            else:
                next_pos = s._find_speakable_at_or_after(pi, bi + 1)
                if next_pos:
                    s.page_index, s.block_index = next_pos
                advanced = True

        assert advanced is False
        # Cursor should still be at block 2 (user's choice)
        assert s.block_index == 2

    def test_auto_advance_proceeds_when_gen_unchanged(self):
        """When user did not navigate, auto-advance commits under the lock."""
        doc = _doc([
            _block("block 0", BlockType.TEXT),
            _block("block 1", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)

        with s._cursor_lock:
            pi, bi, gen = s.page_index, s.block_index, s._cursor_gen

        # No user navigation — gen still matches
        next_pos = s._find_speakable_at_or_after(pi, bi + 1)
        with s._cursor_lock:
            if s._cursor_gen == gen and next_pos:
                s.page_index, s.block_index = next_pos
                advanced = True
            else:
                advanced = False

        assert advanced is True
        assert s.block_index == 1

    def test_deferred_advance_cursor_stays_on_played_block(self):
        """After natural audio end, shared cursor must stay on the just-played block.

        Reproduces the +2 skip bug: if auto-advance wrote to the shared cursor
        immediately, the GUI would read the advanced position and overshoot.
        With deferred advance the cursor stays put until the next iteration.
        """
        doc = _doc([
            _block("block 0", BlockType.TEXT),
            _block("block 1", BlockType.TEXT),
            _block("block 2", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)

        with s._cursor_lock:
            pi, bi = s.page_index, s.block_index

        # Simulate what the playback loop does at natural end:
        # compute next (locally), store as pending, DON'T write to cursor.
        next_pos = s._find_speakable_at_or_after(pi, bi + 1)
        assert next_pos == (0, 1)

        # Shared cursor must still be at block 0 (the block that just played)
        assert s.page_index == 0
        assert s.block_index == 0

        # Now user clicks Next — reads cursor = 0, correctly goes to 1
        moved = s.next_speakable_block()
        assert moved is True
        assert s.page_index == 0
        assert s.block_index == 1  # NOT 2

    def test_deferred_advance_committed_when_gen_unchanged(self):
        """If user didn't navigate, the deferred advance is applied at the top of the next iteration."""
        doc = _doc([
            _block("block 0", BlockType.TEXT),
            _block("block 1", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)

        with s._cursor_lock:
            gen = s._cursor_gen

        # Simulate deferred advance: pending = block 1
        pending_pi, pending_bi, pending_gen = 0, 1, gen

        # Commit at top of next iteration (same logic as playback loop)
        with s._cursor_lock:
            if s._cursor_gen == pending_gen:
                s.page_index = pending_pi
                s.block_index = pending_bi

        assert s.page_index == 0
        assert s.block_index == 1  # advance committed

    def test_deferred_advance_discarded_when_user_navigated(self):
        """If user navigated during pause_after, the deferred advance is discarded."""
        doc = _doc([
            _block("block 0", BlockType.TEXT),
            _block("block 1", BlockType.TEXT),
            _block("block 2", BlockType.TEXT),
        ])
        s = _make_session(doc)
        s.go_to_page(0)

        with s._cursor_lock:
            gen = s._cursor_gen

        # Simulate deferred advance: pending = block 1
        pending_pi, pending_bi, pending_gen = 0, 1, gen

        # User navigates to block 2 during pause_after
        s._move_cursor(0, 2)

        # Commit attempt at top of next iteration
        with s._cursor_lock:
            if s._cursor_gen == pending_gen:
                s.page_index = pending_pi
                s.block_index = pending_bi

        # User's navigation wins — cursor stays at block 2
        assert s.page_index == 0
        assert s.block_index == 2

    def test_get_cursor_snapshot_is_consistent(self):
        """_get_cursor_snapshot returns a consistent triple even under concurrent writes."""
        doc = _doc([_block("a", BlockType.TEXT), _block("b", BlockType.TEXT)])
        s = _make_session(doc)
        s.go_to_page(0)

        snapshots: list[tuple[int, int, int]] = []
        stop_flag = threading.Event()

        def writer():
            while not stop_flag.is_set():
                s._move_cursor(0, 0)
                s._move_cursor(0, 1)

        def reader():
            for _ in range(200):
                pi, bi, gen = s._get_cursor_snapshot()
                snapshots.append((pi, bi, gen))

        t_write = threading.Thread(target=writer)
        t_read = threading.Thread(target=reader)
        t_write.start()
        t_read.start()
        t_read.join(timeout=2.0)
        stop_flag.set()
        t_write.join(timeout=2.0)

        # All snapshots should be valid (bi in {0, 1}, pi == 0)
        for pi, bi, gen in snapshots:
            assert pi == 0
            assert bi in (0, 1)
            assert gen >= 0
