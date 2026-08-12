# Karaoke Player

Desktop karaoke player (Electron + React + TypeScript) for the local
[`karaoke-server`](../karaoke-server) backend.

## Features

- **Song library** — fuzzy search by song or singer, status filters, and an
  edit dialog to rename/re-tag, **replace the audio** (re-runs processing),
  **replace or regenerate the instrumental**, or delete a song and its files.
- **Full player** — MV video, play/pause, seek ±10 s/±30 s, restart, skip to next.
- **Seamless original ⇄ instrumental (karaoke) toggle** — both tracks play in
  parallel and swap with a 60 ms gain crossfade at the exact same timestamp.
  The instrumental is generated automatically at import, so karaoke mode is
  ready without any manual step.
- **Karaoke subtitles** — progressive highlight from the server's token-timed
  JSON: per **word** (English) / per **character** (Chinese, Japanese), with
  hiragana **furigana** ruby and optional translations. Text is **sized to the
  window** (grows in fullscreen) with a dark halo so it stays legible over any
  background, and only the current line is shown for a clean look.
- **Mini-player** — leave the player (Esc) and a compact bar stays over the
  library showing the **live lyrics** with controls: play/pause, **stop**,
  expand back to full screen.
- **Play queue** — client-side, auto-advance, persisted across restarts.
- **Cover art** — shown in the library and as the playback background for songs
  without an MV (uploaded, or auto-extracted from the audio tags by the server).
- **Lyric sync** — nudge subtitles ±0.1 s, persisted to the server per song.
- **Upload wizard** — create a song → drop original audio (and optionally your
  own instrumental, an MV, cover art, or `.lrc`/`.txt` lyrics) → the server
  fetches lyrics, removes vocals for an instrumental, and aligns word/character
  timing, streaming **live progress over SSE** → play when ready.

## Prerequisites

- Node.js 20+
- `karaoke-server` running on `127.0.0.1:8787` (start it first; the app shows a
  waiting screen until it is reachable)

To use a backend on another machine, set `VITE_KARAOKE_SERVER` (read at
build/dev-server start, e.g. in `.env.local`):

```bash
VITE_KARAOKE_SERVER=http://192.168.0.109:8787
```

That server must allow this app's origin, i.e. start it with
`KARAOKE_CORS_ORIGINS=http://localhost:5173,http://localhost:3000` (the
default) or a list including them.

## Development

```bash
npm install
npm run dev        # Vite on http://localhost:5173 + Electron with hot reload
KARAOKE_DEVTOOLS=1 npm run dev   # same, but opens DevTools on start
```

**Port matters:** karaoke-server only allows CORS from `localhost:5173` and
`localhost:3000`. The dev server uses `strictPort`, so if 5173 is taken, stop
the conflicting app (or temporarily change `server.port` to 3000 in
`vite.config.ts`).

## Packaging

```bash
npm run dist:mac   # dmg (run on macOS)
npm run dist:win   # NSIS installer (run on Windows)
```

Output lands in `release/`. In production the app serves its UI from an
embedded static server on `127.0.0.1:5173` (falling back to `3000`) so the
page origin stays within the backend's CORS allowlist.

## Keyboard shortcuts (player)

| Key | Action |
| --- | --- |
| Space | Play / pause |
| ← / → | Seek −10s / +10s (with Shift: ±30s) |
| r | Restart song |
| n | Next in queue |
| o | Toggle original / instrumental |
| [ / ] | Lyrics earlier / later (0.1 s) |
| f | Fullscreen |
| Esc | Back to library (playback keeps going in the mini-player) |

Pressing **Esc** returns to the library without stopping the song — the
mini-player keeps the lyrics scrolling and offers a **stop** button.

## Architecture notes

- `src/player/PlaybackEngine.ts` — owns all media elements. Both audio tracks
  are routed through Web Audio `GainNode`s; toggling crossfades gains so no
  element ever seeks. The instrumental element is the master clock; the muted
  track and the video are slaved with `playbackRate` nudges (hard resync above
  250 ms drift).
- `src/subtitles/` — one `requestAnimationFrame` loop reads the engine clock;
  per-token fill is written as a CSS variable (`clip-path` on a fill layer), so
  React only re-renders on line changes.
- `src/components/player/MiniPlayer.tsx` — reuses the same token renderer to
  keep live lyrics + transport visible over the library while a song plays.
- `electron/static-server.ts` — production-only static file server keeping the
  renderer on an allowed CORS origin.
