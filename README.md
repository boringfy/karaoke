# karaoke

A local-first karaoke stack for songs you **own**. Point it at your audio (or a
music video); it fetches the lyrics, force-aligns them to the vocals for
word/character-level karaoke timing, removes the vocals to make an instrumental,
and plays it all back with a progressive highlight — no cloud services or API
keys for the core path.

Two pieces:

- **[karaoke-server](karaoke-server/)** — Python / FastAPI backend. The whole
  pipeline: lyric fetch, vocal separation, timing, furigana, subtitle export.
- **[karaoke-player](karaoke-player/)** — Electron + React desktop app that
  drives the backend and plays the result.

## What it does

- **Auto lyrics** from LRCLIB by title/artist (English, Chinese, Japanese), with
  manual override (`.lrc` / `.txt` / paste).
- **Karaoke timing** — the downloaded lyric text is ground truth; Whisper is used
  only for *timing*, aligned onto each word (English) or character (CJK). Rests
  stay empty (no crawling highlight) and short clips are trimmed to what's sung.
- **Instrumental** generated automatically at import (vocal removal), or upload
  your own; a **seamless original ⇄ karaoke toggle** crossfades between them.
- **Furigana** over kanji for Japanese; optional translations.
- **Desktop player** — searchable library, MV or cover-art background, play
  queue, per-song lyric-sync nudge, a persistent mini-player with live lyrics,
  and viewport-scaled subtitles that stay readable over any background.

## Quick start

1. **Start the backend** (see [karaoke-server/README](karaoke-server/README.md)):

   ```bash
   cd karaoke-server
   python -m venv .venv && . .venv/bin/activate
   pip install -e '.[ml]'
   karaoke-server                 # http://127.0.0.1:8787  (API docs at /docs)
   ```

2. **Start the player** (see [karaoke-player/README](karaoke-player/README.md)):

   ```bash
   cd karaoke-player
   npm install
   npm run dev                    # Electron + Vite on http://localhost:5173
   ```

3. In the app, **Add a song**, drop in the audio (and optionally an MV/cover),
   and watch it process — lyrics → instrumental → timing → ready to sing.

Prefer the API directly? The server README has a `curl` walkthrough.

## License

MIT — see [LICENSE](LICENSE). You are responsible for holding the rights to any
audio and lyrics you process.
