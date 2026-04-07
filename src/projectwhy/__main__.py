"""CLI entry: load config, models, and open PyQt6 main window."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Skip PaddleX model-host connectivity probing at import (can add several seconds).
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

from PyQt6.QtWidgets import QApplication

from projectwhy.config import load_config
from projectwhy.core.layout import load_layout_model
from projectwhy.gui.app import MainWindow, create_tts


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="projectwhy-tts reader")
    parser.add_argument("path", nargs="?", help="Path to PDF, EPUB, or text file")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config.toml (optional)",
    )
    args = parser.parse_args()

    cfg_path = args.config
    if cfg_path is None:
        cwd = Path.cwd() / "config.toml"
        if cwd.exists():
            cfg_path = cwd

    cfg = load_config(cfg_path)
    tts = create_tts(cfg)

    layout_model = load_layout_model(
        model_name=cfg.layout.model_name,
        model_dir=cfg.layout.model_dir or None,
        threshold=cfg.layout.confidence,
        device=cfg.layout.device,
        layout_nms=cfg.layout.layout_nms,
        enable_mkldnn=cfg.layout.enable_mkldnn,
    )

    app = QApplication(sys.argv)
    win = MainWindow(cfg, tts, layout_model, initial_path=args.path)
    win.resize(1200, 900)
    win.show()
    ret = app.exec()
    # PaddlePaddle's C++ threads cause SIGABRT during normal interpreter shutdown;
    # force-exit after Qt cleanup to avoid the crash.
    os._exit(ret)


if __name__ == "__main__":
    main()
