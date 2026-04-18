"""Headless MCP server: stdio JSON-RPC only. Spawns a separate Qt process for the reader."""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
import sys
import threading
import tempfile
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

_INSTR = """Drive the projectwhy-tts desktop reader. Call start_reader first (unless the reader is already running) to spawn the Qt window. After changing Qt/GUI code, call stop_reader then start_reader to reload. All page_index values are 0-based. Prefer get_document_info, get_reading_state, and list_page_blocks before navigation or playback."""

mcp = FastMCP(
    "projectwhy-tts",
    instructions=_INSTR,
    log_level="WARNING",
)

_proc: subprocess.Popen[str] | None = None
_bridge: "_BridgeClient | None" = None
_sock_path: str | None = None
_state_lock = asyncio.Lock()


class _BridgeClient:
    def __init__(self, path: str) -> None:
        self._path = path
        self._sock: socket.socket | None = None
        self._r: Any = None
        self._w: Any = None
        self._next_id = 1
        self._call_lock = threading.Lock()

    def connect(self) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise RuntimeError("Unix domain sockets required for projectwhy MCP controller")
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.connect(self._path)
        self._r = self._sock.makefile("r", encoding="utf-8", newline="\n")
        self._w = self._sock.makefile("w", encoding="utf-8", newline="\n")

    def close(self) -> None:
        for attr in ("_w", "_r", "_sock"):
            o = getattr(self, attr, None)
            if o is not None:
                try:
                    o.close()
                except OSError:
                    pass
                setattr(self, attr, None)

    def call(self, method: str, params: dict[str, Any]) -> Any:
        with self._call_lock:
            if self._w is None or self._r is None:
                raise ConnectionError("bridge not connected")
            req_id = self._next_id
            self._next_id += 1
            line = json.dumps({"id": req_id, "method": method, "params": params}, ensure_ascii=False) + "\n"
            self._w.write(line)
            self._w.flush()
            resp_line = self._r.readline()
            if not resp_line:
                raise ConnectionError("Qt worker closed connection")
            resp = json.loads(resp_line)
            if resp.get("id") != req_id:
                raise RuntimeError("RPC id mismatch")
            if "error" in resp:
                msg = resp["error"].get("message", str(resp["error"]))
                raise RuntimeError(msg)
            return resp["result"]


def _default_config_path(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if not p.is_file():
            raise FileNotFoundError(f"not a file: {p}")
        return p
    cwd = Path.cwd() / "config.toml"
    if cwd.is_file():
        return cwd.resolve()
    raise FileNotFoundError(
        "No config file found. Pass config_path to start_reader, set cwd to the project, "
        "or copy config.example.toml to config.toml."
    )


def _wait_worker_ready(proc: subprocess.Popen[str], stdout: Any) -> None:
    import time as time_mod

    t0 = time_mod.monotonic()
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"Qt worker exited early (code {proc.returncode})")
        if time_mod.monotonic() - t0 > 180.0:
            raise TimeoutError("Qt worker did not bind socket in time")
        line = stdout.readline()
        if not line:
            time_mod.sleep(0.05)
            continue
        if line.startswith("MCP_QT_WORKER_LISTENING"):
            return


def _clear_reader_sync() -> None:
    global _proc, _bridge, _sock_path
    if _bridge is not None:
        _bridge.close()
        _bridge = None
    if _proc is not None:
        if _proc.poll() is None:
            _proc.terminate()
            try:
                _proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                _proc.kill()
                _proc.wait(timeout=5)
        _proc = None
    if _sock_path:
        try:
            Path(_sock_path).unlink(missing_ok=True)
        except OSError:
            pass
        _sock_path = None


async def _forward(method: str, params: dict[str, Any]) -> Any:
    async with _state_lock:
        b = _bridge
        if b is None:
            raise RuntimeError("reader_not_running")
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: b.call(method, params))


@mcp.tool()
async def start_reader(
    config_path: str | None = None,
    document_path: str | None = None,
) -> dict[str, Any]:
    """Spawn the Qt reader process (layout model + window). Safe to call again after stop_reader."""

    global _proc, _bridge, _sock_path

    async with _state_lock:
        if _proc is not None and _proc.poll() is None and _bridge is not None:
            return {"ok": True, "already_running": True, "socket": _sock_path}

        _clear_reader_sync()

        cfg = _default_config_path(config_path)
        sock = str(Path(tempfile.gettempdir()) / f"projectwhy-mcp-{uuid.uuid4().hex}.sock")
        cmd = [
            sys.executable,
            "-m",
            "projectwhy.mcp_qt_worker",
            "--socket",
            sock,
            "--config",
            str(cfg),
        ]
        if document_path:
            cmd.append(str(Path(document_path).expanduser().resolve()))

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=None,
            stdin=subprocess.DEVNULL,
            text=True,
        )
        _proc = proc
        _sock_path = sock
        stdout = proc.stdout
        assert stdout is not None

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _wait_worker_ready(proc, stdout))
    except Exception as e:
        async with _state_lock:
            if _proc is proc:
                _clear_reader_sync()
        return {"ok": False, "error": str(e)}

    def connect() -> _BridgeClient:
        c = _BridgeClient(sock)
        c.connect()
        return c

    try:
        client = await loop.run_in_executor(None, connect)
    except Exception as e:
        async with _state_lock:
            if _proc is proc:
                _clear_reader_sync()
        return {"ok": False, "error": str(e)}

    async with _state_lock:
        if _proc is not proc:
            client.close()
            return {"ok": False, "error": "start interrupted (reader was stopped)"}
        _bridge = client

    return {"ok": True, "already_running": False, "socket": sock, "config": str(cfg)}


@mcp.tool()
async def stop_reader() -> dict[str, Any]:
    """Terminate the Qt reader process (if running). Use before start_reader to pick up GUI code changes."""

    loop = asyncio.get_event_loop()
    async with _state_lock:
        b = _bridge
    if b is not None:
        try:
            await loop.run_in_executor(None, lambda: b.call("quit_app", {}))
        except (BrokenPipeError, ConnectionError, OSError, RuntimeError, json.JSONDecodeError):
            pass
    async with _state_lock:
        if _bridge is b:
            _clear_reader_sync()
    return {"ok": True}


@mcp.tool()
async def reader_status() -> dict[str, Any]:
    """Return whether the Qt reader subprocess is running."""

    async with _state_lock:
        alive = _proc is not None and _proc.poll() is None
        return {
            "ok": True,
            "running": alive,
            "pid": _proc.pid if alive and _proc else None,
        }


async def _maybe_forward(method: str, params: dict[str, Any]) -> Any:
    try:
        return await _forward(method, params)
    except RuntimeError as e:
        if str(e) == "reader_not_running":
            return {"ok": False, "error": "reader_not_running", "hint": "Call start_reader first."}
        raise


@mcp.tool()
async def ping() -> dict[str, Any]:
    """Check that the Qt GUI thread responds."""
    return await _maybe_forward("ping", {})


@mcp.tool()
async def get_document_info() -> dict[str, Any]:
    """Return whether a document is open, its path, type, page count, and cursor page."""
    return await _maybe_forward("get_document_info", {})


@mcp.tool()
async def get_reading_state() -> dict[str, Any]:
    """Return playback state: page, block, word, is_playing, audio position in seconds."""
    return await _maybe_forward("get_reading_state", {})


@mcp.tool()
async def open_document(path: str) -> dict[str, Any]:
    """Open a PDF, EPUB, or plain text file (absolute path or ~)."""
    return await _maybe_forward("open_document", {"path": path})


@mcp.tool()
async def play() -> dict[str, Any]:
    """Start or resume TTS playback from the current cursor."""
    return await _maybe_forward("play", {})


@mcp.tool()
async def pause() -> dict[str, Any]:
    """Pause TTS playback."""
    return await _maybe_forward("pause", {})


@mcp.tool()
async def stop() -> dict[str, Any]:
    """Stop playback and the prefetch worker."""
    return await _maybe_forward("stop", {})


@mcp.tool()
async def next_page() -> dict[str, Any]:
    """Go to the next document page (stops playback first)."""
    return await _maybe_forward("next_page", {})


@mcp.tool()
async def prev_page() -> dict[str, Any]:
    """Go to the previous document page (stops playback first)."""
    return await _maybe_forward("prev_page", {})


@mcp.tool()
async def go_to_page(page_index: int) -> dict[str, Any]:
    """Jump to a page by 0-based index."""
    return await _maybe_forward("go_to_page", {"page_index": page_index})


@mcp.tool()
async def go_to_position(page_index: int, block_index: int) -> dict[str, Any]:
    """Jump to page_index and block_index (0-based), honoring speakable-block snapping like the GUI."""
    return await _maybe_forward(
        "go_to_position",
        {"page_index": page_index, "block_index": block_index},
    )


@mcp.tool()
async def next_block() -> dict[str, Any]:
    """Move the cursor to the next speakable block."""
    return await _maybe_forward("next_block", {})


@mcp.tool()
async def prev_block() -> dict[str, Any]:
    """Move the cursor to the previous speakable block."""
    return await _maybe_forward("prev_block", {})


@mcp.tool()
async def play_from_word(page_index: int, block_index: int, word_index: int) -> dict[str, Any]:
    """Start reading from a specific word (0-based page, block, word indices). PDF, EPUB, or plain."""
    return await _maybe_forward(
        "play_from_word",
        {"page_index": page_index, "block_index": block_index, "word_index": word_index},
    )


@mcp.tool()
async def play_from_block(page_index: int, block_index: int) -> dict[str, Any]:
    """Start reading from the start of a layout block (0-based indices). PDF, EPUB, or plain."""
    return await _maybe_forward(
        "play_from_block",
        {"page_index": page_index, "block_index": block_index},
    )


@mcp.tool()
async def list_page_blocks(
    page_index: int | None = None,
    text_max_chars: int = 400,
) -> dict[str, Any]:
    """List layout blocks on a page (default: current page). Each entry includes type, text, bbox."""
    params: dict[str, Any] = {"text_max_chars": text_max_chars}
    if page_index is not None:
        params["page_index"] = page_index
    return await _maybe_forward("list_page_blocks", params)


@mcp.tool()
async def list_voices() -> dict[str, Any]:
    """Return TTS voice ids (and labels if the engine provides them)."""
    return await _maybe_forward("list_voices", {})


@mcp.tool()
async def set_voice(voice: str) -> dict[str, Any]:
    """Set the active TTS voice (engine-specific id; see list_voices)."""
    return await _maybe_forward("set_voice", {"voice": voice})


@mcp.tool()
async def set_playback_speed(speed: float) -> dict[str, Any]:
    """Set playback speed (same discrete choices as the GUI combo when possible)."""
    return await _maybe_forward("set_playback_speed", {"speed": speed})


@mcp.tool()
async def set_inspector_visible(visible: bool = True) -> dict[str, Any]:
    """Show or hide the Inspector dock (Layout, Detail, and Pipeline tabs)."""
    return await _maybe_forward("set_inspector_visible", {"visible": visible})


@mcp.tool()
async def screenshot(output_path: str | None = None) -> dict[str, Any]:
    """Save a PNG of the main window; returns the absolute path. Default: temp file under /tmp."""
    params: dict[str, Any] = {}
    if output_path is not None:
        params["output_path"] = output_path
    return await _maybe_forward("screenshot", params)


@mcp.tool()
async def quit_app() -> dict[str, Any]:
    """Close the Qt reader window and end the reader process (MCP controller keeps running)."""

    loop = asyncio.get_event_loop()
    async with _state_lock:
        b = _bridge
    if b is None:
        return {"ok": False, "error": "reader_not_running", "hint": "Call start_reader first."}
    try:
        r = await loop.run_in_executor(None, lambda: b.call("quit_app", {}))
    except (BrokenPipeError, ConnectionError, OSError, RuntimeError, json.JSONDecodeError) as e:
        r = {"ok": False, "error": str(e)}
    async with _state_lock:
        if _bridge is b:
            _clear_reader_sync()
    return r


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
