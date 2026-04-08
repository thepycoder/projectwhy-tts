"""Application config: dataclass schema ↔ TOML (file must define every key)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import tomli_w

from projectwhy.core.playback_speed import clamp_playback_speed


@dataclass
class OpenAIConfig:
    api_key: str
    base_url: str
    model: str
    voice: str
    format: str


@dataclass
class TTSConfig:
    engine: str
    voice: str
    device: str
    openai: OpenAIConfig


@dataclass
class LayoutConfig:
    model_name: str
    model_dir: str
    confidence: float
    device: str
    layout_nms: bool
    enable_mkldnn: bool


@dataclass
class DisplayConfig:
    pdf_scale: float
    highlight_color: list[int]


@dataclass
class ReadingConfig:
    tts_cache_max_entries: int
    prefetch_lookahead: int
    playback_speed: float


@dataclass
class PdfTextConfig:
    """Characters used when extracting PDF words (pypdfium2 line-break + hyphen continuation)."""

    line_break_marker: str
    soft_hyphen_continuation: str


DEFAULT_PDF_TEXT = PdfTextConfig(line_break_marker="\ufffe", soft_hyphen_continuation="\u00ad")


@dataclass
class BlocksConfig:
    """Per PP-DocLayout class: keys are ``BlockType`` values (e.g. ``document_title``)."""

    types: dict[str, dict[str, Any]]


@dataclass
class AppConfig:
    tts: TTSConfig
    layout: LayoutConfig
    display: DisplayConfig
    reading: ReadingConfig
    pdf_text: PdfTextConfig
    blocks: BlocksConfig


def _normalize_block_types(raw: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, row in raw.items():
        if not isinstance(name, str) or not isinstance(row, dict):
            continue
        entry: dict[str, Any] = {}
        if "speak" in row:
            entry["speak"] = bool(row["speak"])
        if "pause_after" in row:
            entry["pause_after"] = float(row["pause_after"])
        if entry:
            out[name] = entry
    return out


def _config_from_toml_dict(data: dict) -> AppConfig:
    t = data["tts"]
    o = t["openai"]
    layout = data["layout"]
    display = data["display"]
    reading = data["reading"]
    pdf_text = data["pdf_text"]
    blocks = data["blocks"]
    return AppConfig(
        tts=TTSConfig(
            engine=t["engine"],
            voice=t["voice"],
            device=t["device"],
            openai=OpenAIConfig(
                api_key=o["api_key"],
                base_url=o["base_url"],
                model=o["model"],
                voice=o["voice"],
                format=o["format"],
            ),
        ),
        layout=LayoutConfig(
            model_name=layout["model_name"],
            model_dir=layout["model_dir"],
            confidence=layout["confidence"],
            device=layout["device"],
            layout_nms=layout["layout_nms"],
            enable_mkldnn=layout["enable_mkldnn"],
        ),
        display=DisplayConfig(
            pdf_scale=display["pdf_scale"],
            highlight_color=display["highlight_color"],
        ),
        reading=ReadingConfig(
            tts_cache_max_entries=reading["tts_cache_max_entries"],
            prefetch_lookahead=reading["prefetch_lookahead"],
            playback_speed=clamp_playback_speed(reading["playback_speed"]),
        ),
        pdf_text=PdfTextConfig(
            line_break_marker=str(pdf_text["line_break_marker"]),
            soft_hyphen_continuation=str(pdf_text["soft_hyphen_continuation"]),
        ),
        blocks=BlocksConfig(types=_normalize_block_types(blocks.get("types", {}))),
    )


def load(path: str | Path) -> AppConfig:
    """Read TOML from *path* and build ``AppConfig`` (every key must be present)."""
    p = Path(path)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return _config_from_toml_dict(data)


def save(path: str | Path, cfg: AppConfig) -> None:
    """Write *cfg* to TOML at *path* (overwrites)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        tomli_w.dump(asdict(cfg), f)


# Backward-compatible names
load_config = load
save_config = save
