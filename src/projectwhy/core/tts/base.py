"""TTS protocol."""

from __future__ import annotations

from typing import Protocol

from projectwhy.core.models import TTSResult


class TTSEngine(Protocol):
    def synthesize(self, text: str) -> TTSResult: ...

    def get_voices(self) -> list[str]: ...
