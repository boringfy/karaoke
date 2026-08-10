---
name: youtube-download
description: Download YouTube videos at full resolution with yt-dlp, for sourcing MVs into the karaoke pipeline. Use when fetching source video, or when troubleshooting yt-dlp returning only 360p, "This video is not available", or "This video is DRM protected".
---

# Downloading YouTube video at full resolution

For pulling MVs into `data/raw_videos/` as the video track for a song. As with
the rest of this project, intended for content you hold the rights to use.

## The one thing that matters

**A JavaScript runtime alone is not enough. yt-dlp also needs its EJS *solver
script*, and it will not fetch that unless you ask.**

Without it, every adaptive/DASH format is silently dropped and you fall through
to progressive format `18` — which caps at **360p by design**. The symptom looks
like a server-side quality restriction. It isn't.

## Prerequisites (one-time)

```bash
# yt-dlp — lives in the server venv
source /nvmex2/karaoke/karaoke-server/.venv/bin/activate
pip install -U yt-dlp

# deno — the JS runtime yt-dlp enables by default
brew install deno          # provides /home/linuxbrew/.linuxbrew/bin/deno

# ffmpeg must be on PATH for merging video+audio
```

If deno is not on `PATH`, either export it or pass `--js-runtimes node` (node
works equally well — the runtime choice is not the deciding factor).

## The working command

```bash
export PATH="/home/linuxbrew/.linuxbrew/bin:$PATH"
source /nvmex2/karaoke/karaoke-server/.venv/bin/activate
cd /nvmex2/karaoke/data/raw_videos

yt-dlp --remote-components ejs:github \
  -f "bv*+ba/b" --merge-output-format mp4 --no-progress \
  -o "%(uploader)s - %(title)s [%(id)s].%(ext)s" \
  "<URL>"
```

`--remote-components ejs:github` is the load-bearing flag. It downloads yt-dlp's
official challenge-solver script from their GitHub at runtime — remote code
executed each run, so enable it deliberately rather than by default.

Verify what you actually got:

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height \
  -of default=noprint_wrappers=1 "<file>.mp4"
```

## Why HD disappears

YouTube serves two kinds of stream:

| kind | what it is | max res | gated? |
|---|---|---|---|
| progressive (`18`) | video+audio muxed, plain HTTPS file | **360p** | no |
| adaptive / DASH (`137`+`140`, …) | video-only + audio-only, merged locally | 1080p+ | yes |

1080p exists **only** as adaptive. Adaptive stream URLs carry an obfuscated `n`
parameter that must be transformed by running the player's JavaScript. Unsolved,
yt-dlp drops those formats rather than hand you dead links — leaving `18` as the
only complete stream. Format `18` survives because it predates that machinery:
no signature transform, no PO token, no SABR.

So 360p is not a degraded 1080p. It's the only ungated format, and its ceiling
happens to be 360p.

## Diagnostic ladder

Always start here — it is cheap and settles most questions:

```bash
yt-dlp --remote-components ejs:github -F "<URL>"
```

- See `137` / `248` / `399` (1080p) and `140` / `251` (audio) → adaptive is
  working, just pick formats.
- See only `18` + `sb*` storyboards → **solver script missing**. Add
  `--remote-components ejs:github`.
- See only `sb*` storyboards, "Only images are available" → same cause, web
  client stripped entirely.

### Error messages that mislead

| message | what it usually means |
|---|---|
| `n challenge solving failed` | the real cause — solver script missing |
| `This video is not available` | downstream of the above, **not** a dead video |
| `This video is DRM protected` | came from the `tv` client only; a client-wide DRM experiment, not a property of the video |
| `formats have been skipped as they are missing a URL` | SABR-only experiment on the `android` client; use the web client path instead |

### Ruled out by controlled test

Both were tested from an ordinary datacenter IP and made **no difference** —
don't waste time on them:

- **yt-dlp version.** `2026.03.17` and `2026.07.04` failed identically.
- **Which JS runtime.** node and deno failed identically.

The deciding variable was the EJS solver script, nothing else.

## Format selection

`bv*+ba/b` picks the smallest-for-quality combination, typically `399+251`
(av01 + opus). That is efficient but AV1 playback is not universal.

For the Electron player, or anywhere you want maximum compatibility, force
H.264 + AAC instead:

```bash
-f "137+140"     # avc1 1080p + m4a — larger, plays anywhere
```

Useful extras:

- `-k` keeps the separate video/audio files after merging
- `--cookies-from-browser chrome` for content behind your own logged-in session
- `-F` before committing to a large download

## Wiring into the karaoke pipeline

Downloads land in `/nvmex2/karaoke/data/raw_videos/`. To attach one as a song's
MV, upload it to an existing song id:

```bash
curl -X POST "http://127.0.0.1:8787/api/v1/songs/<SONG_ID>/video" \
  -F "file=@/nvmex2/karaoke/data/raw_videos/<file>.mp4"
```

Then confirm `has_video` flipped:

```bash
curl -s "http://127.0.0.1:8787/api/v1/songs/<SONG_ID>" | jq '{title, has_video}'
```
