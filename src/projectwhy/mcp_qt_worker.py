"""Qt + layout subprocess for MCP: listens on a Unix socket for JSON tool calls."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import queue
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtWidgets import QApplication

from projectwhy.config import load
from projectwhy.core.layout import load_layout_model
from projectwhy.mcp_tool_handlers import McpQtContext, dispatch_tool


class QtInvoker(QObject):
    """Run callables on the Qt GUI thread (via a QTimer pump)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._q: queue.Queue[tuple[Callable[[], Any], concurrent.futures.Future[Any]]] = queue.Queue()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._drain)

    def start(self) -> None:
        self._timer.start()

    def call(self, fn: Callable[[], Any], *, timeout: float = 120.0) -> Any:
        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._q.put((fn, fut))
        return fut.result(timeout=timeout)

    def _drain(self) -> None:
        while True:
            try:
                fn, fut = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(fn())
            except Exception as e:
                fut.set_exception(e)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="projectwhy MCP Qt worker (internal)")
    p.add_argument("--socket", required=True, help="Unix domain socket path to bind")
    p.add_argument("--config", type=Path, required=True, help="Path to config.toml")
    p.add_argument("path", nargs="?", help="Optional document to open on startup")
    return p.parse_args(argv)


def _serve_socket(sock_path: str, ctx: McpQtContext) -> None:
    if not hasattr(socket, "AF_UNIX"):
        raise RuntimeError("Unix domain sockets required for MCP Qt worker")

    path = Path(sock_path)
    if path.exists():
        path.unlink()

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(1)
    print(f"MCP_QT_WORKER_LISTENING {sock_path}", flush=True)

    conn, _ = srv.accept()
    srv.close()
    if path.exists():
        path.unlink()

    f_in = conn.makefile("r", encoding="utf-8", newline="\n")
    f_out = conn.makefile("w", encoding="utf-8", newline="\n")

    try:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = req.get("id")
            method = req.get("method")
            params = req.get("params") or {}
            if rid is None or not isinstance(method, str):
                continue
            try:

                def work() -> Any:
                    return dispatch_tool(ctx, method, params if isinstance(params, dict) else {})

                result = ctx.invoker.call(work)
                json.dump({"id": rid, "result": result}, f_out)
                f_out.write("\n")
                f_out.flush()
            except Exception as e:
                json.dump({"id": rid, "error": {"message": str(e)}}, f_out)
                f_out.write("\n")
                f_out.flush()
    finally:
        f_in.close()
        f_out.close()
        conn.close()


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )

    raw_argv = sys.argv[1:] if argv is None else argv
    args = _parse_args(raw_argv)
    cfg_path = args.config
    if not cfg_path.is_file():
        print(f"config not found: {cfg_path}", file=sys.stderr)
        sys.exit(1)

    cfg = load(cfg_path)

    from projectwhy.gui.app import MainWindow, create_tts

    tts = create_tts(cfg)
    layout_model = load_layout_model(
        model_name=cfg.layout.model_name,
        model_dir=cfg.layout.model_dir or None,
        threshold=cfg.layout.confidence,
        device=cfg.layout.device or None,
        layout_nms=cfg.layout.layout_nms,
        enable_mkldnn=cfg.layout.enable_mkldnn,
    )

    app = QApplication(sys.argv)
    invoker = QtInvoker(parent=app)
    win = MainWindow(
        cfg,
        tts,
        layout_model,
        initial_path=args.path,
        config_path=cfg_path,
    )
    invoker.start()
    ctx = McpQtContext(app=app, window=win, invoker=invoker)

    win.resize(1200, 900)
    win.show()

    def _kick_socket() -> None:
        threading.Thread(
            target=_serve_socket,
            args=(args.socket, ctx),
            name="projectwhy-mcp-socket",
            daemon=True,
        ).start()

    QTimer.singleShot(0, _kick_socket)

    ret = app.exec()
    os._exit(ret)


if __name__ == "__main__":
    main()
