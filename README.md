# karaoke

A local-first karaoke stack for songs you own:

- **[karaoke-server](karaoke-server/)** — Python/FastAPI backend. Fetches lyrics,
  force-aligns them to the audio for word/character-level karaoke timing, adds
  furigana for Japanese, and can generate an instrumental by removing vocals.
- **[karaoke-player](karaoke-player/)** — Electron + React desktop player that
  drives the backend: library, seamless original⇄instrumental toggle, and
  progressive per-word lyric highlighting.

See each subproject's README for setup and usage.

## License

MIT — see [karaoke-server/LICENSE](karaoke-server/LICENSE). You are responsible
for holding the rights to any audio and lyrics you process.
