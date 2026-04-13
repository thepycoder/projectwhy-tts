"""Mistral Voxtral TTS API (cloud). No word timestamps in API response."""

from __future__ import annotations

import base64
import io
import logging
import wave

import numpy as np

from projectwhy.core.models import TTSResult

try:
    from mistralai.client import Mistral
except ImportError:  # pragma: no cover
    Mistral = None  # type: ignore

logger = logging.getLogger(__name__)


class MistralVoxtralTTS:
    def __init__(
        self,
        api_key: str,
        model: str = "voxtral-mini-tts-2603",
        voice_id: str = "",
        response_format: str = "wav",
    ) -> None:
        if Mistral is None:
            raise RuntimeError("mistralai package not installed; use: uv sync --extra mistral")
        self._client = Mistral(api_key=api_key)
        self.model = model
        self.voice = voice_id
        self.response_format = response_format
        self._voice_ids: list[str] | None = None
        self._voice_labels: list[str] | None = None

    def _load_voices(self) -> None:
        ids: list[str] = []
        labels: list[str] = []
        try:
            offset = 0
            while True:
                page = self._client.audio.voices.list(limit=50, offset=offset, type_="all")
                items = page.items or []
                for v in items:
                    vid = str(getattr(v, "id", "") or "")
                    if not vid:
                        continue
                    name = str(getattr(v, "name", "") or "")
                    ids.append(vid)
                    labels.append(f"{name} ({vid[:8]}…)" if name else vid)
                total = int(getattr(page, "total", 0) or 0)
                offset += len(items)
                if offset >= total or not items:
                    break
        except Exception:
            logger.exception("mistral: failed to list voices")
        self._voice_ids = ids
        self._voice_labels = labels if labels else None

    def refresh_voices(self) -> None:
        """Clear cached voice list (next ``get_voices`` refetches from API)."""
        self._voice_ids = None
        self._voice_labels = None

    def get_voices(self) -> list[str]:
        if self._voice_ids is None:
            self._load_voices()
        return list(self._voice_ids or [])

    def voice_labels(self) -> list[str] | None:
        if self._voice_ids is None:
            self._load_voices()
        if not self._voice_labels:
            return None
        return list(self._voice_labels)

    def synthesize(self, text: str) -> TTSResult:
        if not text.strip():
            return TTSResult(audio=np.array([], dtype=np.float32), sample_rate=24000, word_timestamps=None)
        if not (self.voice or "").strip():
            raise ValueError("Mistral TTS: set a voice_id (pick a voice in settings or the toolbar)")

        resp = self._client.audio.speech.complete(
            input=text,
            model=self.model,
            voice_id=self.voice,
            response_format=self.response_format,  # type: ignore[arg-type]
            stream=False,
        )
        b64 = getattr(resp, "audio_data", None) or getattr(resp, "audioData", None)
        if not b64 or not isinstance(b64, str):
            raise ValueError("Mistral TTS: response missing audio_data")
        data = base64.b64decode(b64)

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

        raise ValueError(
            f"Mistral TTS: unsupported response_format {self.response_format!r} (use 'wav')"
        )
