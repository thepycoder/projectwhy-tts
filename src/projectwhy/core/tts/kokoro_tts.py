"""Local Kokoro TTS with word timestamps (English)."""

from __future__ import annotations

import numpy as np
from kokoro import KPipeline

from projectwhy.core.models import TTSResult, WordTimestamp

KOKORO_VOICES = [
    "af_heart",
    "af_bella",
    "af_sarah",
    "af_sky",
    "am_adam",
    "am_michael",
    "bf_emma",
    "bf_isabella",
    "bm_george",
    "bm_lewis",
]


class KokoroTTS:
    def __init__(
        self,
        voice: str = "af_heart",
        device: str | None = None,
        repo_id: str = "hexgrad/Kokoro-82M",
        lang_code: str = "a",
    ):
        self.voice = voice
        self.pipeline = KPipeline(lang_code=lang_code, repo_id=repo_id, device=device)

    def synthesize(self, text: str) -> TTSResult:
        if not text.strip():
            return TTSResult(audio=np.array([], dtype=np.float32), sample_rate=24000, word_timestamps=[])

        # Fixed 1.0× synthesis; playback tempo (with pitch preservation) is applied in the session.
        results = list(self.pipeline(text, voice=self.voice, speed=1.0))
        audio_chunks: list[np.ndarray] = []
        word_timestamps: list[WordTimestamp] = []
        offset = 0.0
        sample_rate = 24000

        for result in results:
            if result.audio is None:
                continue
            audio_np = result.audio.detach().cpu().numpy().reshape(-1)
            if result.tokens:
                for token in result.tokens:
                    if getattr(token, "start_ts", None) is None:
                        continue
                    if getattr(token, "end_ts", None) is None:
                        continue
                    word_timestamps.append(
                        WordTimestamp(
                            text=token.text,
                            start_sec=float(token.start_ts) + offset,
                            end_sec=float(token.end_ts) + offset,
                        )
                    )
            offset += float(len(audio_np)) / float(sample_rate)
            audio_chunks.append(audio_np)

        if not audio_chunks:
            return TTSResult(audio=np.array([], dtype=np.float32), sample_rate=sample_rate, word_timestamps=[])

        audio = np.concatenate(audio_chunks).astype(np.float32, copy=False)
        return TTSResult(audio=audio, sample_rate=sample_rate, word_timestamps=word_timestamps)

    def get_voices(self) -> list[str]:
        return list(KOKORO_VOICES)
