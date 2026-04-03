"""CLI entry: load config, models, and open PyQt6 main window."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

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

    weights = cfg.layout.model_path or None
    layout_model = load_layout_model(weights)

    app = QApplication(sys.argv)
    win = MainWindow(cfg, tts, layout_model, initial_path=args.path)
    win.resize(1200, 900)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
