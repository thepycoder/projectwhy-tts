"""OpenAI-compatible speech API (no word timestamps)."""

from __future__ import annotations

import io
import wave

import numpy as np

from projectwhy.core.models import TTSResult

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore


class OpenAITTS:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "tts-1",
        voice: str = "alloy",
        response_format: str = "wav",
    ):
        if OpenAI is None:
            raise RuntimeError("openai package not installed; use: uv sync --extra openai")
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.voice = voice
        self.response_format = response_format

    def synthesize(self, text: str) -> TTSResult:
        if not text.strip():
            return TTSResult(audio=np.array([], dtype=np.float32), sample_rate=24000, word_timestamps=None)

        resp = self.client.audio.speech.create(
            model=self.model,
            voice=self.voice,
            input=text,
            response_format=self.response_format,
        )
        if hasattr(resp, "read"):
            data = resp.read()
        elif hasattr(resp, "content"):
            data = resp.content
        else:
            data = bytes(resp)

        if self.response_format == "wav":
            with wave.open(io.BytesIO(data), "rb") as wf:
                sr = wf.getframerate()
                n = wf.getnframes()
                raw = wf.readframes(n)
                width = wf.getsampwidth()
                if width == 2:
                    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                else:
                    arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
                if wf.getnchannels() == 2:
                    arr = arr.reshape(-1, 2).mean(axis=1)
                return TTSResult(audio=arr, sample_rate=sr, word_timestamps=None)

        raise ValueError(f"Unsupported response_format {self.response_format!r} (use 'wav')")

    def get_voices(self) -> list[str]:
        return ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
