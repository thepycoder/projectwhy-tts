# projectwhy-tts

Local PDF/EPUB reader with Kokoro TTS, DocLayout-YOLO layout analysis, and word-level highlights (PyQt6).

## Setup

```bash
cd projectwhy-tts
uv venv
uv sync
# Optional OpenAI TTS:
uv sync --extra openai
```

Copy `config.example.toml` to `config.toml` and adjust.

## Run

```bash
uv run projectwhy path/to/book.pdf
uv run projectwhy path/to/book.epub
```

First run downloads Kokoro weights (via Hugging Face) and the layout model (~40MB).

## Requirements

- Python 3.11+
- Audio device (speakers) for playback
- Optional: CUDA for faster layout + Kokoro (CPU works)

## License

Dependencies include models and libraries under their respective licenses (see each provider).
