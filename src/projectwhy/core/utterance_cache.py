"""Content-keyed TTS cache: deduplicates synthesis and evicts via LRU."""

from __future__ import annotations

import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

from projectwhy.core.models import TTSResult
from projectwhy.core.tts.base import TTSEngine

logger = logging.getLogger(__name__)


@dataclass
class _Pending:
    cond: threading.Condition
    done: bool = False


class UtteranceCache:
    """Thread-safe LRU cache: text+voice hash → TTSResult.

    Concurrent requests for the same key are deduplicated: the first caller
    synthesizes under *tts_lock*; subsequent callers block until the result is
    stored, then return the same TTSResult.

    The cache is NOT cleared on stop/play — retained across sessions so
    revisiting blocks is instant. Call ``clear()`` when voice or engine changes.
    """

    def __init__(
        self,
        tts: TTSEngine,
        tts_lock: threading.Lock,
        max_entries: int = 64,
    ) -> None:
        self._tts = tts
        self._tts_lock = tts_lock
        self._max_entries = max_entries

        self._lock = threading.Lock()
        self._ready: OrderedDict[str, TTSResult] = OrderedDict()
        self._pending: dict[str, _Pending] = {}

    # -- public API ----------------------------------------------------------

    def make_key(self, tts_text: str) -> str:
        voice = getattr(self._tts, "voice", "") or ""
        raw = f"{voice}\x00{tts_text.strip()}"
        return hashlib.sha1(raw.encode()).hexdigest()

    def get(self, tts_text: str) -> TTSResult | None:
        """Non-blocking lookup by pre-computed TTS string. Returns None if not cached."""
        key = self.make_key(tts_text)
        with self._lock:
            result = self._ready.get(key)
            if result is not None:
                self._ready.move_to_end(key)
            return result

    def get_or_synthesize(self, tts_text: str) -> TTSResult:
        """Return cached result; synthesize (blocking) if missing.

        If another thread is already synthesizing the same key, this waits for
        that result rather than calling synthesize() a second time.
        """
        key = self.make_key(tts_text)

        with self._lock:
            if key in self._ready:
                self._ready.move_to_end(key)
                return self._ready[key]

            if key in self._pending:
                entry = self._pending[key]
                synthesize = False
            else:
                entry = _Pending(cond=threading.Condition())
                self._pending[key] = entry
                synthesize = True

        if not synthesize:
            with entry.cond:
                while not entry.done:
                    entry.cond.wait(timeout=0.2)
            with self._lock:
                if key in self._ready:
                    self._ready.move_to_end(key)
                    return self._ready[key]
            # Synthesizer failed — retry (will re-synthesize once, then succeed or raise)
            return self.get_or_synthesize(tts_text)

        # This thread is the synthesizer
        try:
            with self._tts_lock:
                result = self._tts.synthesize(tts_text)
        except Exception:
            with self._lock:
                self._pending.pop(key, None)
            with entry.cond:
                entry.done = True
                entry.cond.notify_all()
            raise

        with self._lock:
            self._ready[key] = result
            self._pending.pop(key, None)
            self._evict()
        with entry.cond:
            entry.done = True
            entry.cond.notify_all()

        return result

    def clear(self) -> None:
        """Discard all cached audio (e.g. after voice change).

        In-flight synthesis continues; results will be stored under the old
        voice key and won't match new voice lookups.
        """
        with self._lock:
            self._ready.clear()

    def replace_tts(self, tts: TTSEngine) -> None:
        """Point the cache at a new engine and drop entries (e.g. after engine swap)."""
        self._tts = tts
        self.clear()

    def update_max_entries(self, n: int) -> None:
        with self._lock:
            self._max_entries = n
            self._evict()

    # -- internal ------------------------------------------------------------

    def _evict(self) -> None:
        """Remove oldest entries until size <= max_entries. Call under self._lock."""
        while len(self._ready) > self._max_entries:
            self._ready.popitem(last=False)
