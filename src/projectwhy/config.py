"""Load application config from TOML with defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


@dataclass
class OpenAIConfig:
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "tts-1"
    voice: str = "alloy"
    format: str = "wav"


@dataclass
class TTSConfig:
    engine: str = "kokoro"
    voice: str = "af_heart"
    speed: float = 1.0
    device: str | None = "cpu"
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)


@dataclass
class LayoutConfig:
    model_path: str = ""
    confidence: float = 0.25
    imgsz: int = 1024


@dataclass
class DisplayConfig:
    pdf_scale: float = 2.0
    highlight_color: tuple[int, int, int, int] = (255, 200, 0, 128)


@dataclass
class AppConfig:
    tts: TTSConfig = field(default_factory=TTSConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    cfg = AppConfig()
    if path is None:
        return cfg

    p = Path(path)
    if not p.exists():
        return cfg

    data = tomllib.loads(p.read_text(encoding="utf-8"))

    if "tts" in data:
        t = data["tts"]
        cfg.tts.engine = str(t.get("engine", cfg.tts.engine))
        cfg.tts.voice = str(t.get("voice", cfg.tts.voice))
        cfg.tts.speed = float(t.get("speed", cfg.tts.speed))
        dev = t.get("device", cfg.tts.device)
        cfg.tts.device = None if dev in ("", "none", None) else str(dev)

    if "tts" in data and isinstance(data["tts"], dict) and "openai" in data["tts"]:
        o = data["tts"]["openai"]
        cfg.tts.openai.api_key = str(o.get("api_key", ""))
        cfg.tts.openai.base_url = str(o.get("base_url", cfg.tts.openai.base_url))
        cfg.tts.openai.model = str(o.get("model", cfg.tts.openai.model))
        cfg.tts.openai.voice = str(o.get("voice", cfg.tts.openai.voice))
        cfg.tts.openai.format = str(o.get("format", cfg.tts.openai.format))

    if "layout" in data:
        l = data["layout"]
        cfg.layout.model_path = str(l.get("model_path", "") or "")
        cfg.layout.confidence = float(l.get("confidence", cfg.layout.confidence))
        cfg.layout.imgsz = int(l.get("imgsz", cfg.layout.imgsz))

    if "display" in data:
        d = data["display"]
        cfg.display.pdf_scale = float(d.get("pdf_scale", cfg.display.pdf_scale))
        hc = d.get("highlight_color")
        if isinstance(hc, list) and len(hc) == 4:
            cfg.display.highlight_color = tuple(int(x) for x in hc)  # type: ignore[assignment]

    return cfg
