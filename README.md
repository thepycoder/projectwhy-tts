# projectwhy-tts

Local PDF/EPUB reader with Kokoro TTS, PP-DocLayout (PaddleOCR) region detection, and word-level highlights (PyQt6).

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

First run downloads Kokoro weights (via Hugging Face) and the PP-DocLayout weights (via PaddleX cache under `~/.paddlex`, size depends on S/M/L variant).

On some Linux CPU builds, Paddle oneDNN can fail; the example config sets `enable_mkldnn = false`. You can set `PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True` to skip PaddleX’s model-host connectivity check at import time.

## Requirements

- Python 3.11+
- Audio device (speakers) for playback
- [pytsmod](https://github.com/KAIST-MACLab/PyTSMod) (bundled) when using playback speed other than 1.0× for pitch-preserving tempo (WSOLA)
- Optional: GPU for faster layout (`[layout] device = "gpu"`) and Kokoro TTS (CPU works for both)

## License

Dependencies include models and libraries under their respective licenses (see each provider).
