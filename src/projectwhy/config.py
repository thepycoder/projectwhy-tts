"""Application config: dataclass schema ↔ TOML (file must define every key)."""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import tomli_w

from projectwhy.core.playback_speed import clamp_playback_speed


def normalize_highlight_granularity(raw: str) -> str:
    """Return ``word`` or ``block`` (default ``word``)."""
    v = (raw or "word").strip().lower()
    return "block" if v == "block" else "word"


@dataclass
class OpenAIConfig:
    api_key: str
    base_url: str
    model: str
    voice: str
    format: str


@dataclass
class MistralConfig:
    api_key: str
    model: str
    voice_id: str
    format: str


@dataclass
class TTSConfig:
    engine: str
    voice: str
    device: str
    openai: OpenAIConfig
    mistral: MistralConfig


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
    highlight_granularity: str


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
class SubstitutionRuleConfig:
    find: str
    replace: str
    regex: bool


@dataclass
class SubstitutionsConfig:
    """Global TTS find-and-replace rules (applied before synthesis)."""

    rules: list[SubstitutionRuleConfig]


@dataclass
class AppConfig:
    tts: TTSConfig
    layout: LayoutConfig
    display: DisplayConfig
    reading: ReadingConfig
    pdf_text: PdfTextConfig
    blocks: BlocksConfig
    substitutions: SubstitutionsConfig


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


def _parse_substitution_rules(raw: Any) -> list[SubstitutionRuleConfig]:
    if not isinstance(raw, list):
        return []
    out: list[SubstitutionRuleConfig] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        find = entry.get("find", "")
        replace = entry.get("replace", "")
        regex = bool(entry.get("regex", False))
        if isinstance(find, str) and isinstance(replace, str) and find:
            out.append(SubstitutionRuleConfig(find=find, replace=replace, regex=regex))
    return out


def _config_from_toml_dict(data: dict) -> AppConfig:
    t = data["tts"]
    o = t["openai"]
    m = t["mistral"]
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
            mistral=MistralConfig(
                api_key=m["api_key"],
                model=m["model"],
                voice_id=m["voice_id"],
                format=m["format"],
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
            highlight_granularity=normalize_highlight_granularity(str(display["highlight_granularity"])),
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
        substitutions=SubstitutionsConfig(
            rules=_parse_substitution_rules(data.get("substitutions", {}).get("rules", [])),
        ),
    )


def load(path: str | Path) -> AppConfig:
    """Read TOML from *path* and build ``AppConfig`` (every key must be present)."""
    p = Path(path)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    return _config_from_toml_dict(data)


def _toml_basic_str_unicode_escapes(s: str) -> str:
    """TOML double-quoted string: BMP code points as ``\\uXXXX`` (one char for pdf_text keys)."""
    if not s:
        return '""'
    c = s[0]
    o = ord(c)
    if o <= 0xFFFF:
        return f'"\\u{o:04x}"'
    return f'"\\U{o:08x}"'


def _rewrite_pdf_text_section(content: str, cfg: AppConfig) -> str:
    """Replace ``[pdf_text]`` assignments so markers are written as ``\\u`` escapes, not raw UTF-8."""
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.strip() == "[pdf_text]":
            out.append(line)
            i += 1
            others: list[str] = []
            while i < n:
                raw = lines[i]
                sl = raw.strip()
                if not sl:
                    out.append(raw)
                    i += 1
                    break
                if sl.startswith("["):
                    break
                if sl.startswith("line_break_marker") or sl.startswith("soft_hyphen_continuation"):
                    i += 1
                    continue
                others.append(raw)
                i += 1
            out.append(
                f"line_break_marker = {_toml_basic_str_unicode_escapes(cfg.pdf_text.line_break_marker)}\n",
            )
            out.append(
                f"soft_hyphen_continuation = "
                f"{_toml_basic_str_unicode_escapes(cfg.pdf_text.soft_hyphen_continuation)}\n",
            )
            out.extend(others)
            continue
        out.append(line)
        i += 1
    return "".join(out)


def save(path: str | Path, cfg: AppConfig) -> None:
    """Write *cfg* to TOML at *path* (overwrites)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    tomli_w.dump(asdict(cfg), buf)
    text = buf.getvalue().decode("utf-8")
    text = _rewrite_pdf_text_section(text, cfg)
    p.write_text(text, encoding="utf-8")


# Backward-compatible names
load_config = load
save_config = save
