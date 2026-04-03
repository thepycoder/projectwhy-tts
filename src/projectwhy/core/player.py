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
        self._stream: sd.OutputStream | None = None
        self._complete_event = threading.Event()
        self._on_complete: Callable[[], None] | None = None

    def play(
        self,
        audio: np.ndarray,
        sample_rate: int,
        on_complete: Callable[[], None] | None = None,
    ) -> None:
        self.stop()
        with self._lock:
            self._audio = np.ascontiguousarray(audio, dtype=np.float32).reshape(-1, 1)
            self._sample_rate = sample_rate
            self._current_frame = 0
            self._playing = True
            self._complete_event.clear()
            self._on_complete = on_complete

        frames_total = self._audio.shape[0]

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
                self._playing = False
            self._complete_event.set()
            cb = self._on_complete
            if cb:
                cb()

        self._stream = sd.OutputStream(
            samplerate=self._sample_rate,
            channels=1,
            dtype="float32",
            callback=callback,
            finished_callback=finished,
        )
        self._stream.start()

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
        if self._stream:
            self._stream.stop()

    def resume(self) -> None:
        if self._stream:
            self._stream.start()

    def stop(self) -> None:
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self._stream = None
        with self._lock:
            self._playing = False
            self._audio = None
            self._current_frame = 0

    def is_playing(self) -> bool:
        return self._playing
