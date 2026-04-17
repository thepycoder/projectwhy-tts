"""EPUB → single-file M4B audiobook export (resumable per-chapter WAV + ffmpeg)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

import numpy as np

from projectwhy.core.models import Block, BlockType, Document, Page
from projectwhy.core.session import speak_heuristic
from projectwhy.core.substitutions import SubstitutionRule, block_tts_parts, block_tts_text
from projectwhy.core.time_stretch import time_stretch
from projectwhy.core.tts.base import TTSEngine

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
CONCAT_LIST_NAME = "concat_list.txt"
FFMETADATA_NAME = "ffmetadata.txt"


class AudiobookError(Exception):
    """User-facing failure (missing ffmpeg, mux error, etc.)."""


@dataclass
class AudiobookMetadata:
    title: str
    author: str | None = None
    cover_bytes: bytes | None = None
    cover_mime: str | None = None  # e.g. image/jpeg


@dataclass
class AudiobookProgress:
    phase: Literal["synthesizing", "encoding", "done", "cancelled"]
    chapter_index: int
    total_chapters: int
    chapter_title: str
    block_index: int
    total_blocks: int
    elapsed_sec: float
    skipped_cached: bool = False


def _emit(
    cb: Callable[[AudiobookProgress], None] | None,
    p: AudiobookProgress,
) -> None:
    if cb is not None:
        cb(p)


def tts_fingerprint(tts: Any) -> tuple[str, str]:
    """Return (engine_id, voice_key) for cache invalidation."""
    name = type(tts).__name__
    if name == "KokoroTTS":
        return ("kokoro", str(getattr(tts, "voice", "")))
    if name == "OpenAITTS":
        m = getattr(tts, "model", "")
        v = getattr(tts, "voice", "")
        return ("openai", f"{m}|{v}")
    if name == "MistralVoxtralTTS":
        m = getattr(tts, "model", "")
        v = getattr(tts, "voice", "")
        return ("mistral", f"{m}|{v}")
    return (name.lower(), repr(tts))


def _rules_canonical(rules: list[SubstitutionRule]) -> list[dict[str, Any]]:
    return [{"find": r.find, "replace": r.replace, "regex": r.use_regex} for r in rules]


def _block_config_canonical(
    block_config: dict[BlockType, dict[str, Any]],
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for bt in sorted(block_config.keys(), key=lambda x: x.value):
        d = block_config[bt]
        rows.append([bt.value, bool(d["speak"]), float(d["pause_after"])])
    return rows


def _chapter_blocks_payload(page: Page) -> list[dict[str, str]]:
    return [{"type": b.block_type.value, "text": b.text} for b in page.blocks]


def compute_chapter_content_hash(
    page: Page,
    *,
    rules: list[SubstitutionRule],
    block_config: dict[BlockType, dict[str, Any]],
    engine_id: str,
    voice: str,
    speed: float,
) -> str:
    payload = {
        "blocks": _chapter_blocks_payload(page),
        "rules": _rules_canonical(rules),
        "block_config": _block_config_canonical(block_config),
        "engine": engine_id,
        "voice": voice,
        "speed": float(speed),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def _pause_after_block(
    block: Block, block_config: dict[BlockType, dict[str, Any]]
) -> float:
    cfg = block_config.get(
        block.block_type,
        {"speak": True, "pause_after": 0.3},
    )
    return float(cfg["pause_after"])


def infer_chapter_title(page: Page) -> str:
    for b in page.blocks:
        if b.block_type in (BlockType.DOCUMENT_TITLE, BlockType.PARAGRAPH_TITLE):
            t = b.text.strip()
            if t:
                return t[:200]
    href = getattr(page, "spine_href", None)
    if href:
        return Path(href).stem.replace("_", " ")[:200]
    return f"Chapter {page.index + 1}"


def _resample_linear(y: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out or y.size == 0:
        return y.astype(np.float32, copy=False)
    dur = len(y) / float(sr_in)
    n_out = max(1, int(round(dur * sr_out)))
    x_old = np.linspace(0.0, dur, num=len(y), endpoint=False, dtype=np.float64)
    x_new = np.linspace(0.0, dur, num=n_out, endpoint=False, dtype=np.float64)
    return np.interp(x_new, x_old, y.astype(np.float64)).astype(np.float32)


def _silence(sample_rate: int, seconds: float) -> np.ndarray:
    if seconds <= 0:
        return np.array([], dtype=np.float32)
    n = int(round(seconds * sample_rate))
    return np.zeros(max(0, n), dtype=np.float32)


def _write_wav_mono_f32(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    y = np.clip(np.asarray(audio, dtype=np.float32).reshape(-1), -1.0, 1.0)
    pcm = (y * 32767.0).astype(np.int16)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.tobytes())


def wav_duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def _check_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            check=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AudiobookError(
            "ffmpeg not found or failed to run. Install ffmpeg and ensure it is on PATH "
            "to export M4B audiobooks."
        ) from exc


def _ffmpeg_escape_path(p: Path) -> str:
    s = str(p.resolve())
    return s.replace("'", "'\\''")


def _write_concat_list(chapter_wavs: list[Path], dest: Path) -> None:
    lines = [f"file '{_ffmpeg_escape_path(w)}'" for w in chapter_wavs]
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_ffmetadata(
    dest: Path,
    *,
    title: str,
    author: str | None,
    chapter_titles: list[str],
    chapter_duration_sec: list[float],
) -> None:
    lines = [";FFMETADATA1", f"title={_ffmeta_escape(title)}"]
    if author:
        lines.append(f"artist={_ffmeta_escape(author)}")
        lines.append(f"album={_ffmeta_escape(title)}")
    else:
        lines.append(f"album={_ffmeta_escape(title)}")
    t_ms = 0
    for i, (ctitle, dur) in enumerate(zip(chapter_titles, chapter_duration_sec, strict=True)):
        start = t_ms
        end = t_ms + int(round(dur * 1000.0))
        t_ms = end
        lines.append("")
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={start}")
        lines.append(f"END={end}")
        lines.append(f"title={_ffmeta_escape(ctitle)}")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ffmeta_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")


def _run_ffmpeg_mux(
    *,
    concat_list: Path,
    ffmetadata: Path,
    cover_path: Path | None,
    output_m4b: Path,
) -> None:
    out_tmp = output_m4b.with_suffix(output_m4b.suffix + ".tmp")
    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-f",
        "ffmetadata",
        "-i",
        str(ffmetadata),
    ]
    if cover_path is not None:
        cmd.extend(["-i", str(cover_path)])
    cmd.extend(["-map_metadata", "1", "-map_chapters", "1", "-map", "0:a", "-c:a", "aac", "-b:a", "128k"])
    if cover_path is not None:
        cmd.extend(
            [
                "-map",
                "2:v:0",
                "-c:v:0",
                "copy",
                "-disposition:v:0",
                "attached_pic",
            ]
        )
    cmd.extend(["-movflags", "+faststart", "-f", "mp4", str(out_tmp)])
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=7200)
    except subprocess.CalledProcessError as e:
        err = (e.stderr or b"").decode("utf-8", errors="replace")[-2000:]
        raise AudiobookError(f"ffmpeg failed while encoding M4B:\n{err}") from e
    os.replace(out_tmp, output_m4b)


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_manifest(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _manifest_compatible(
    old: dict[str, Any],
    engine_id: str,
    voice_key: str,
    speed: float,
) -> bool:
    return (
        old.get("engine_id") == engine_id
        and str(old.get("voice", "")) == voice_key
        and abs(float(old.get("speed", -1.0)) - speed) < 1e-6
    )


def _hydrate_chapter_rows(
    old: dict[str, Any] | None,
    n_ch: int,
    engine_id: str,
    voice_key: str,
    speed: float,
) -> list[dict[str, Any] | None]:
    """Rebuild per-chapter manifest slots from disk. Uses ``index`` in each entry when present
    so a truncated save (only some chapters listed) still restores the right slots."""
    rows: list[dict[str, Any] | None] = [None] * n_ch
    if not old or not _manifest_compatible(old, engine_id, voice_key, speed):
        return rows
    raw = old.get("chapters")
    if not isinstance(raw, list):
        return rows
    by_idx: dict[int, dict[str, Any]] = {}
    for e in raw:
        if not isinstance(e, dict):
            continue
        idx = e.get("index")
        if isinstance(idx, int) and 0 <= idx < n_ch:
            by_idx[idx] = e
    for i in range(n_ch):
        if i in by_idx:
            rows[i] = by_idx[i]
    for i in range(min(len(raw), n_ch)):
        if rows[i] is not None:
            continue
        e = raw[i]
        if not isinstance(e, dict):
            continue
        idx = e.get("index")
        if isinstance(idx, int) and 0 <= idx < n_ch:
            if rows[idx] is None:
                rows[idx] = e
        else:
            rows[i] = e
    return rows


def _persist_manifest(
    manifest_path: Path,
    engine_id: str,
    voice_key: str,
    speed: float,
    chapter_rows: list[dict[str, Any] | None],
) -> None:
    _save_manifest(
        manifest_path,
        {
            "version": 1,
            "engine_id": engine_id,
            "voice": voice_key,
            "speed": speed,
            "chapters": chapter_rows,
        },
    )


def generate_audiobook(
    document: Document,
    tts: TTSEngine,
    output_path: Path,
    *,
    block_config: dict[BlockType, dict[str, Any]],
    substitution_rules: list[SubstitutionRule],
    metadata: AudiobookMetadata,
    work_dir: Path | None = None,
    progress_cb: Callable[[AudiobookProgress], None] | None = None,
    cancel_event: threading.Event | None = None,
    chapter_target_sr: int = 24000,
) -> None:
    """Synthesize all speakable EPUB spine chapters and mux to *output_path* (.m4b).

    Tempo is always native TTS (1.0×); in-app playback speed does not apply so the file
    stays compatible with standard audiobook players.
    """
    if document.doc_type != "epub":
        raise AudiobookError("Audiobook export is only supported for EPUB documents.")
    _check_ffmpeg()

    out = Path(output_path).expanduser().resolve()
    if out.suffix.lower() != ".m4b":
        out = out.with_suffix(".m4b")

    wd = work_dir if work_dir is not None else Path(str(out) + ".parts")
    wd.mkdir(parents=True, exist_ok=True)
    manifest_path = wd / MANIFEST_NAME

    engine_id, voice_key = tts_fingerprint(tts)
    speed = 1.0
    rules = substitution_rules

    pages = document.pages
    n_ch = len(pages)
    if n_ch == 0:
        raise AudiobookError("Document has no pages.")

    cancel_ev = cancel_event or threading.Event()
    import time as time_mod

    t0 = time_mod.perf_counter()

    def elapsed() -> float:
        return time_mod.perf_counter() - t0

    on_disk = _load_manifest(manifest_path)
    chapter_rows = _hydrate_chapter_rows(on_disk, n_ch, engine_id, voice_key, speed)

    chapter_wav_paths: list[Path] = []
    chapter_titles: list[str] = []
    chapter_durations: list[float] = []

    for ci, page in enumerate(pages):
        if cancel_ev.is_set():
            _emit(
                progress_cb,
                AudiobookProgress(
                    phase="cancelled",
                    chapter_index=ci,
                    total_chapters=n_ch,
                    chapter_title=infer_chapter_title(page),
                    block_index=0,
                    total_blocks=max(1, len(page.blocks)),
                    elapsed_sec=elapsed(),
                ),
            )
            return

        title = infer_chapter_title(page)
        chash = compute_chapter_content_hash(
            page,
            rules=rules,
            block_config=block_config,
            engine_id=engine_id,
            voice=voice_key,
            speed=speed,
        )
        wav_name = f"chapter_{ci:04d}.wav"
        wav_path = wd / wav_name

        cand = chapter_rows[ci]
        cached: dict[str, Any] | None = None
        if (
            cand
            and cand.get("content_hash") == chash
            and cand.get("wav") == wav_name
            and wav_path.is_file()
        ):
            try:
                if wav_duration_sec(wav_path) > 1e-6:
                    cached = cand
            except OSError:
                cached = None

        total_blocks = max(1, len(page.blocks))

        if cached is not None:
            dur = float(cached.get("duration_sec", wav_duration_sec(wav_path)))
            chapter_wav_paths.append(wav_path)
            chapter_titles.append(str(cached.get("title") or title))
            chapter_durations.append(dur)
            _emit(
                progress_cb,
                AudiobookProgress(
                    phase="synthesizing",
                    chapter_index=ci,
                    total_chapters=n_ch,
                    chapter_title=title,
                    block_index=total_blocks,
                    total_blocks=total_blocks,
                    elapsed_sec=elapsed(),
                    skipped_cached=True,
                ),
            )
            continue

        # Synthesize chapter
        chunks: list[np.ndarray] = []
        sr_out = int(chapter_target_sr)
        bi_done = 0
        for bi, block in enumerate(page.blocks):
            if cancel_ev.is_set():
                _emit(
                    progress_cb,
                    AudiobookProgress(
                        phase="cancelled",
                        chapter_index=ci,
                        total_chapters=n_ch,
                        chapter_title=title,
                        block_index=bi_done,
                        total_blocks=total_blocks,
                        elapsed_sec=elapsed(),
                    ),
                )
                tmp_partial = wd / f"{wav_name}.partial"
                for p in (tmp_partial, wav_path):
                    try:
                        if p.is_file():
                            p.unlink()
                    except OSError:
                        pass
                return

            _emit(
                progress_cb,
                AudiobookProgress(
                    phase="synthesizing",
                    chapter_index=ci,
                    total_chapters=n_ch,
                    chapter_title=title,
                    block_index=bi,
                    total_blocks=total_blocks,
                    elapsed_sec=elapsed(),
                ),
            )

            if not speak_heuristic(block, block_config):
                bi_done = bi + 1
                continue

            tts_text = block_tts_text(block_tts_parts(block, rules))
            if not tts_text.strip():
                bi_done = bi + 1
                continue

            try:
                result = tts.synthesize(tts_text)
            except Exception:
                logger.exception("audiobook: synthesis failed chapter %d block %d", ci, bi)
                bi_done = bi + 1
                continue

            raw = np.asarray(result.audio, dtype=np.float32).reshape(-1)
            sr_in = int(result.sample_rate) if result.sample_rate > 0 else sr_out
            if raw.size == 0:
                bi_done = bi + 1
                continue
            stretched = time_stretch(raw, sr_in, speed)
            audio = _resample_linear(stretched, sr_in, sr_out)
            chunks.append(audio)
            pause = _pause_after_block(block, block_config)
            chunks.append(_silence(sr_out, pause))
            bi_done = bi + 1

        if not chunks:
            chunks.append(_silence(sr_out, 0.1))

        chapter_audio = np.concatenate(chunks).astype(np.float32, copy=False)
        tmp_wav = wd / f"{wav_name}.tmp"
        try:
            _write_wav_mono_f32(tmp_wav, chapter_audio, sr_out)
            os.replace(tmp_wav, wav_path)
        except OSError:
            if tmp_wav.is_file():
                tmp_wav.unlink(missing_ok=True)
            raise

        dur = wav_duration_sec(wav_path)
        chapter_wav_paths.append(wav_path)
        chapter_titles.append(title)
        chapter_durations.append(dur)
        chapter_rows[ci] = {
            "index": ci,
            "title": title,
            "wav": wav_name,
            "duration_sec": dur,
            "content_hash": chash,
        }
        _persist_manifest(manifest_path, engine_id, voice_key, speed, chapter_rows)

    if cancel_ev.is_set():
        _emit(
            progress_cb,
            AudiobookProgress(
                phase="cancelled",
                chapter_index=n_ch - 1,
                total_chapters=n_ch,
                chapter_title="",
                block_index=0,
                total_blocks=1,
                elapsed_sec=elapsed(),
            ),
        )
        return

    concat_list = wd / CONCAT_LIST_NAME
    ffmeta = wd / FFMETADATA_NAME
    _write_concat_list(chapter_wav_paths, concat_list)
    _write_ffmetadata(
        ffmeta,
        title=metadata.title,
        author=metadata.author,
        chapter_titles=chapter_titles,
        chapter_duration_sec=chapter_durations,
    )

    cover_path: Path | None = None
    cover_tmpdir: Path | None = None
    if metadata.cover_bytes:
        cover_tmpdir = Path(tempfile.mkdtemp(prefix="projectwhy-cover-"))
        ext = ".jpg"
        if metadata.cover_mime:
            if "png" in metadata.cover_mime.lower():
                ext = ".png"
            elif "webp" in metadata.cover_mime.lower():
                ext = ".webp"
        cover_path = cover_tmpdir / f"cover{ext}"
        cover_path.write_bytes(metadata.cover_bytes)
    try:
        _emit(
            progress_cb,
            AudiobookProgress(
                phase="encoding",
                chapter_index=n_ch - 1,
                total_chapters=n_ch,
                chapter_title="",
                block_index=0,
                total_blocks=1,
                elapsed_sec=elapsed(),
            ),
        )
        _run_ffmpeg_mux(
            concat_list=concat_list,
            ffmetadata=ffmeta,
            cover_path=cover_path,
            output_m4b=out,
        )
    finally:
        if cover_tmpdir is not None:
            shutil.rmtree(cover_tmpdir, ignore_errors=True)

    _emit(
        progress_cb,
        AudiobookProgress(
            phase="done",
            chapter_index=n_ch - 1,
            total_chapters=n_ch,
            chapter_title="",
            block_index=0,
            total_blocks=1,
            elapsed_sec=elapsed(),
        ),
    )
