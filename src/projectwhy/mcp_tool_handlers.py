"""Shared sync handlers for MCP tools (run on the Qt GUI thread)."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from projectwhy.core.models import Block, ReadingState


@dataclass
class McpQtContext:
    app: Any
    window: Any
    invoker: Any


def _reading_state_dict(st: ReadingState) -> dict[str, Any]:
    return {
        "page_index": st.page_index,
        "block_index": st.block_index,
        "word_index": st.word_index,
        "is_playing": st.is_playing,
        "position_sec": st.position_sec,
    }


def _block_dict(block: Block, index: int, *, text_max: int) -> dict[str, Any]:
    t = block.text
    truncated = len(block.text) > text_max
    if truncated:
        t = block.text[:text_max] + "…"
    return {
        "index": index,
        "type": block.block_type.value,
        "text": t,
        "text_truncated": truncated,
        "word_count": len(block.words),
        "bbox": {
            "x1": block.bbox.x1,
            "y1": block.bbox.y1,
            "x2": block.bbox.x2,
            "y2": block.bbox.y2,
        },
    }


def handle_ping(ctx: McpQtContext) -> dict[str, Any]:
    _ = ctx.window.windowTitle()
    return {"ok": True, "pong": "pong"}


def handle_get_document_info(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"open": False}
    doc = w.session.document
    return {
        "open": True,
        "path": doc.path,
        "doc_type": doc.doc_type,
        "page_count": len(doc.pages),
        "current_page_index": w.session.page_index,
        "playback_worker_active": w.session.is_active,
    }


def handle_get_reading_state(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    return {"ok": True, "state": _reading_state_dict(w.session.get_state())}


def handle_open_document(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    path = params["path"]
    p = Path(str(path)).expanduser()
    if not p.is_file():
        return {"ok": False, "error": f"not a file: {path}"}
    w = ctx.window
    w.open_path(str(p.resolve()))
    if w.session is None:
        return {"ok": False, "error": "failed to open (see logs or any error dialog)"}
    doc = w.session.document
    return {
        "ok": True,
        "path": doc.path,
        "doc_type": doc.doc_type,
        "page_count": len(doc.pages),
    }


def handle_play(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w._controls.play_clicked.emit()
    return {"ok": True}


def handle_pause(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w._controls.pause_clicked.emit()
    return {"ok": True}


def handle_stop(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w.session.stop()
    return {"ok": True}


def handle_next_page(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w._controls.next_page_clicked.emit()
    return {"ok": True, "page_index": w.session.page_index}


def handle_prev_page(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w._controls.prev_page_clicked.emit()
    return {"ok": True, "page_index": w.session.page_index}


def handle_go_to_page(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    page_index = int(params["page_index"])
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    doc = w.session.document
    if page_index < 0 or page_index >= len(doc.pages):
        return {"ok": False, "error": f"page_index out of range 0..{len(doc.pages) - 1}"}
    w.session.stop()
    w.session.go_to_page(page_index)
    w._refresh_page_view()
    return {"ok": True, "page_index": w.session.page_index}


def handle_go_to_position(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    page_index = int(params["page_index"])
    block_index = int(params["block_index"])
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    doc = w.session.document
    if page_index < 0 or page_index >= len(doc.pages):
        return {"ok": False, "error": f"page_index out of range 0..{len(doc.pages) - 1}"}
    w.session.stop()
    w.session.go_to_position(page_index, block_index)
    w._refresh_page_view()
    return {
        "ok": True,
        "page_index": w.session.page_index,
        "block_index": w.session.block_index,
    }


def handle_next_block(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w._controls.next_block_clicked.emit()
    return {"ok": True, "block_index": w.session.block_index}


def handle_prev_block(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    w._controls.prev_block_clicked.emit()
    return {"ok": True, "block_index": w.session.block_index}


def handle_play_from_word(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    ok = w.session.play_from_word(
        int(params["page_index"]),
        int(params["block_index"]),
        int(params["word_index"]),
    )
    w._refresh_page_view()
    return {"ok": bool(ok)}


def handle_play_from_block(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    ok = w.session.play_from_block(int(params["page_index"]), int(params["block_index"]))
    w._refresh_page_view()
    return {"ok": bool(ok)}


def handle_list_page_blocks(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    w = ctx.window
    if w.session is None:
        return {"ok": False, "error": "no_document"}
    doc = w.session.document
    page_index = params.get("page_index")
    text_max_chars = int(params.get("text_max_chars", 400))
    pi = w.session.page_index if page_index is None else int(page_index)
    if pi < 0 or pi >= len(doc.pages):
        return {"ok": False, "error": f"page_index out of range 0..{len(doc.pages) - 1}"}
    page = w.session._ensure_page(pi)
    blocks = [_block_dict(b, i, text_max=text_max_chars) for i, b in enumerate(page.blocks)]
    return {"ok": True, "page_index": pi, "blocks": blocks}


def handle_list_voices(ctx: McpQtContext) -> dict[str, Any]:
    w = ctx.window
    tts = w.tts
    names = tts.get_voices()
    labels_fn = getattr(tts, "voice_labels", None)
    labels = labels_fn() if callable(labels_fn) else None
    cur = getattr(tts, "voice", None)
    return {"ok": True, "voices": names, "labels": labels, "current": cur}


def handle_set_voice(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    voice = str(params["voice"])
    w = ctx.window
    if w.session is not None:
        w.session.set_voice(voice)
    if w.cfg.tts.engine == "mistral":
        w.cfg.tts.mistral.voice_id = voice
    elif w.cfg.tts.engine == "openai":
        w.cfg.tts.openai.voice = voice
    else:
        w.cfg.tts.voice = voice
    w._apply_voice_combo(w.tts)
    return {"ok": True}


def handle_set_playback_speed(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    w = ctx.window
    w._controls.speed_changed.emit(float(params["speed"]))
    return {"ok": True, "speed": float(w.cfg.reading.playback_speed)}


def handle_screenshot(ctx: McpQtContext, params: dict[str, Any]) -> dict[str, Any]:
    w = ctx.window
    output_path = params.get("output_path")
    if output_path:
        path = Path(str(output_path)).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        fd, name = tempfile.mkstemp(prefix="projectwhy-mcp-", suffix=".png")
        os.close(fd)
        path = Path(name).resolve()
    pm = w.grab()
    if not pm.save(str(path), "PNG"):
        return {"ok": False, "error": f"failed to save PNG: {path}"}
    return {"ok": True, "path": str(path)}


def handle_quit_app(ctx: McpQtContext) -> dict[str, Any]:
    if ctx.app is not None:
        ctx.app.quit()
    return {"ok": True}


def dispatch_tool(ctx: McpQtContext, method: str, params: dict[str, Any]) -> Any:
    if method == "ping":
        return handle_ping(ctx)
    if method == "get_document_info":
        return handle_get_document_info(ctx)
    if method == "get_reading_state":
        return handle_get_reading_state(ctx)
    if method == "open_document":
        return handle_open_document(ctx, params)
    if method == "play":
        return handle_play(ctx)
    if method == "pause":
        return handle_pause(ctx)
    if method == "stop":
        return handle_stop(ctx)
    if method == "next_page":
        return handle_next_page(ctx)
    if method == "prev_page":
        return handle_prev_page(ctx)
    if method == "go_to_page":
        return handle_go_to_page(ctx, params)
    if method == "go_to_position":
        return handle_go_to_position(ctx, params)
    if method == "next_block":
        return handle_next_block(ctx)
    if method == "prev_block":
        return handle_prev_block(ctx)
    if method == "play_from_word":
        return handle_play_from_word(ctx, params)
    if method == "play_from_block":
        return handle_play_from_block(ctx, params)
    if method == "list_page_blocks":
        return handle_list_page_blocks(ctx, params)
    if method == "list_voices":
        return handle_list_voices(ctx)
    if method == "set_voice":
        return handle_set_voice(ctx, params)
    if method == "set_playback_speed":
        return handle_set_playback_speed(ctx, params)
    if method == "screenshot":
        return handle_screenshot(ctx, params)
    if method == "quit_app":
        return handle_quit_app(ctx)
    raise ValueError(f"unknown tool: {method}")
