# karaoke-server

A local-first karaoke server. Point it at songs you own; it fetches the lyrics,
force-aligns them to the audio to produce **word-level (English) / character-level
(Chinese, Japanese)** karaoke timing, adds **hiragana furigana** over kanji for
Japanese, and can generate an **instrumental** track by removing the vocals. A
SQLite database tracks every song, its files, and its generated subtitles so a
UI can drive playback.

Everything runs on your own machine — no cloud services or API keys are needed
for the core path. Intended for songs you have purchased and are licensed to use.

## Features

- **Auto lyrics** by title (+ optional artist) from LRCLIB, with fallbacks and
  manual override. English, Chinese, and Japanese.
- **Word/character timing** — the downloaded lyrics are the ground truth for the
  *text*; a Whisper transcription supplies only the *timing*, sequence-aligned
  onto the real words (English) or characters (Chinese/Japanese). Instrumental
  gaps stay empty (no crawling highlight), and lyric lines a short clip/MV never
  reaches are trimmed automatically. Confidence-scored, with a stable-ts forced
  alignment fallback.
- **Furigana**: every kanji annotated with its hiragana reading (fugashi + UniDic),
  okurigana correctly excluded from the ruby span.
- **Vocal removal** (audio-separator / UVR models) generates an instrumental
  automatically at import (unless you upload your own); regenerate on demand.
- **Canonical subtitle JSON** for the UI, plus exports to enhanced LRC, LRC, SRT,
  and ASS (with `\k` karaoke sweeps and a furigana layer).
- **Resumable pipeline** backed by SQLite; survives restarts, no external broker.

## Requirements

- Python **3.11+**
- **ffmpeg** on your `PATH` (`ffmpeg -version` to check)
- Optional NVIDIA/Apple-silicon GPU for faster processing (CPU works fine)

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[ml]'      # core server + the audio ML pipeline
# or, API/DB only (SEPARATE and ALIGN stages will report they need the extras):
pip install -e .
```

The first run downloads the Whisper and separation models into the data
directory (a few GB); subsequent runs reuse them.

## Run

```bash
karaoke-server              # serves on http://127.0.0.1:8787
```

Then open `http://127.0.0.1:8787/docs` for interactive API docs.

### Quick start (curl)

```bash
# 1. create the song
ID=$(curl -s -X POST localhost:8787/api/v1/songs \
      -H 'Content-Type: application/json' \
      -d '{"title":"夜に駆ける","artist":"YOASOBI","language":"ja"}' | jq -r .id)

# 2. upload the original audio (this starts the pipeline)
curl -X POST localhost:8787/api/v1/songs/$ID/audio -F kind=original -F file=@song.mp3

# 3. watch progress
curl -N localhost:8787/api/v1/songs/$ID/events

# 4. (optional) regenerate the instrumental — it is generated automatically at import
curl -X POST localhost:8787/api/v1/songs/$ID/separate?force=true

# 5. fetch the karaoke subtitle for your UI
curl localhost:8787/api/v1/songs/$ID/subtitle?format=json
```

Full endpoint reference: **[docs/API.md](docs/API.md)**.

## How it works

```
upload original ─► INGEST ─► SEPARATE ─► LYRICS ─► ALIGN ─► ANNOTATE(ja) ─► RENDER ─► ready
                   (tags,    (vocals +   (fetch    (vocal   (furigana)      (json +
                    probe)    instrum.)   lyrics)   timing)                  lrc/ass/srt)

SEPARATE runs automatically and is best-effort: it is skipped when you upload
your own instrumental, and a failure never blocks lyrics/subtitles. Regenerate
later with POST /separate (add ?force=true to replace an uploaded instrumental).
```

The canonical output is `subtitle.json`; LRC/ASS/SRT are rendered from it on
demand. See [docs/API.md](docs/API.md#subtitle-json-format) for the schema.

## Configuration

Settings are environment variables prefixed `KARAOKE_` (or a `.env` file):

| variable | default | purpose |
|----------|---------|---------|
| `KARAOKE_DATA_DIR` | `~/.local/share/karaoke-server` | database + song files + model cache |
| `KARAOKE_HOST` / `KARAOKE_PORT` | `127.0.0.1` / `8787` | bind address |
| `KARAOKE_CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | comma-separated UI origins; `*` to allow any |
| `KARAOKE_DEVICE` | `auto` | `auto` \| `cpu` \| `cuda` \| `mps` |
| `KARAOKE_WHISPER_MODEL` | `large-v3-turbo` | alignment model (`small`/`medium` for weak CPUs) |
| `KARAOKE_SEPARATION_PRESET` | `fast` | `fast` (UVR MDX-NET) or `quality` (BS-Roformer) |
| `KARAOKE_ENABLE_SCRAPING_PROVIDERS` | `false` | allow ToS-gray lyric scrapers as a last resort |

### GPU notes

Alignment uses faster-whisper (ctranslate2); separation uses ONNX Runtime. To
use an NVIDIA GPU you may need the matching CUDA runtime libraries visible to
those libraries (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12` on `LD_LIBRARY_PATH`,
and `onnxruntime-gpu`). Without them the pipeline runs on CPU, which is the
supported default.

## Data layout

```
$KARAOKE_DATA_DIR/
├── karaoke.db
├── models/                       # downloaded ML models
└── songs/<song_id>/
    ├── original.<ext>            # your uploaded file (never modified)
    ├── instrumental.opus         # uploaded or generated
    ├── video.<ext>              # optional MV
    ├── cover.<ext>              # uploaded or extracted from audio tags
    ├── lyrics.raw.json           # selected raw lyrics
    ├── subtitle.json             # canonical timed subtitle
    └── subtitle.{lrc,ass,srt}    # exports
```

## Development

```bash
pip install -e '.[ml,dev]'
pytest            # unit + API tests (no GPU or network needed)
ruff check .
```

## Licensing & attribution

MIT licensed. The default pipeline uses only permissively licensed
models/libraries. The optional non-commercial MMS aligner is **not** installed
by default. You are responsible for holding the rights to any audio and lyrics
you process.
