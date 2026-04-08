"""Audio playback via sounddevice (non-blocking + position)."""

from __future__ import annotations

import threading
from collections.abc import Callable

import numpy as np
import sounddevice as sd


class AudioPlayer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current_frame = 0
        self._audio: np.ndarray | None = None
        self._sample_rate = 24000
        self._playing = False
        self._paused = False
        self._stream: sd.OutputStream | None = None
        self._complete_event = threading.Event()
        self._on_complete: Callable[[], None] | None = None
        # Bumped in stop() so a stale finished_callback from an aborted stream
        # never fires the *next* play()'s on_complete (fixes immediate wait return).
        self._play_generation = 0

    def _start_stream(
        self,
        on_complete: Callable[[], None] | None,
        completion_gen: int,
    ) -> None:
        """Create and start an output stream from the current frame position."""
        audio = self._audio
        if audio is None:
            return
        frames_total = audio.shape[0]

        def callback(outdata, frames, _time, status) -> None:  # noqa: ANN001
            if status:
                pass
            with self._lock:
                if self._audio is None:
                    outdata.fill(0)
                    raise sd.CallbackStop()
                idx = self._current_frame
                chunk = min(frames_total - idx, int(frames))
                if chunk <= 0:
                    outdata.fill(0)
                    self._playing = False
                    raise sd.CallbackStop()
                outdata[:chunk, 0] = self._audio[idx : idx + chunk, 0]
                if chunk < frames:
                    outdata[chunk:, 0] = 0
                self._current_frame += chunk

        def finished() -> None:
            with self._lock:
                if self._paused:
                    return
                if self._play_generation != completion_gen:
                    return
                self._playing = False
            self._complete_event.set()
            if on_complete:
                on_complete()

        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
            finished_callback=finished,
        )
        self._stream.start()

    def play(
        self,
        audio: np.ndarray,
        sample_rate: int,
        on_complete: Callable[[], None] | None = None,
        *,
        start_sec: float = 0.0,
    ) -> None:
        self.stop()
        with self._lock:
            gen = self._play_generation
            self._audio = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1, 1)
            self._sample_rate = sample_rate
            frames_total = int(self._audio.shape[0])
            start_frame = int(round(float(start_sec) * float(sample_rate)))
            if frames_total <= 0:
                start_frame = 0
            else:
                start_frame = max(0, min(start_frame, frames_total - 1))
            self._current_frame = start_frame
            self._playing = True
            self._paused = False
            self._complete_event.clear()
            self._on_complete = on_complete

        self._start_stream(on_complete, gen)

    def play_blocking(self, audio: np.ndarray, sample_rate: int) -> None:
        e = threading.Event()

        def done() -> None:
            e.set()

        self.play(audio, sample_rate, on_complete=done)
        e.wait()

    def get_position_sec(self) -> float:
        with self._lock:
            if self._sample_rate <= 0:
                return 0.0
            return self._current_frame / float(self._sample_rate)

    def pause(self) -> None:
        with self._lock:
            if not self._playing or self._paused:
                return
            self._paused = True
        if self._stream:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
        self._stream = None

    def resume(self) -> None:
        with self._lock:
            if not self._paused or self._audio is None:
                return
            self._paused = False
            self._playing = True
            gen = self._play_generation
            ocb = self._on_complete
        self._start_stream(ocb, gen)

    def stop(self) -> None:
        with self._lock:
            self._play_generation += 1
        if self._stream:
            try:
                self._stream.abort()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        with self._lock:
            self._playing = False
            self._paused = False
            self._audio = None
            self._current_frame = 0

    def is_playing(self) -> bool:
        with self._lock:
            return self._playing and not self._paused

    def is_paused(self) -> bool:
        with self._lock:
            return self._paused
