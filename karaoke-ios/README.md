# karaoke-ios

A native iPadOS (SwiftUI + AVFoundation) LAN client for
[`karaoke-server`](../karaoke-server) — the iPad as the karaoke box: library on
screen, MV on the glass, lyrics wiping in time, queue for the next singer.

The server does all the work (lyric fetch, vocal separation, forced alignment);
this app browses what's there and plays it.

## What it does

- **Server setup once** — type the LAN address (`192.168.1.50`, port 8787
  assumed); it's pinged before being saved, then remembered.
- **Library** — cover-art grid, search over song and singer, tap a singer to
  filter to them, badges for songs the server is still processing.
- **Player** — MV or blurred cover-art background, transport (play/pause,
  ±10 s, restart, next), scrubber, and chrome that **fades after 4 s** so
  nothing covers the video while people sing.
- **Seamless original ⇄ karaoke toggle** — both tracks stream in parallel and
  crossfade over 120 ms at the same timestamp; no seek, no gap. The choice
  carries to the next song.
- **Karaoke lyrics** — per **word** (EN) / per **character** (ZH, JA) wipe
  drawn on a `Canvas` inside `TimelineView(.animation)`, straight off the
  playback clock, with **furigana** ruby, translations, and a dark halo. Rests
  draw nothing; long lines shrink to fit.
- **Queue** — long-press to add, reorder or delete in the queue sheet,
  auto-advance at end of song.
- **Mini-player** — leave the player with the down-chevron and the song keeps
  going under the library, live lyric line and all, so the next singer can
  queue up.
- **Lyric sync nudge** — ±0.1 s, debounced and persisted to the server, so the
  fix follows the song to every other client.

## Build & run

Prerequisites: Xcode 26+, an iPad on the **same LAN** as the server.

```bash
open karaoke-ios/karaoke.xcodeproj     # then ⌘R with the iPad selected
```

Command-line compile check (no signing needed):

```bash
xcodebuild -project karaoke.xcodeproj -scheme karaoke \
  -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
  build CODE_SIGNING_ALLOWED=NO
```

Running on a real iPad needs a signing team set on the target (Signing &
Capabilities → Team); the bundle id is `com.hashfront.karaoke`.

## Point it at the server

Bind karaoke-server to all interfaces so the iPad can reach it:

```bash
KARAOKE_HOST=0.0.0.0 karaoke-server
```

Then launch the app and enter the server's IP. A native client needs no CORS —
that only applies to the web/Electron UI.

### Server requirement: audio `Content-Type`

`GET /api/v1/songs/{id}/audio` has no file extension in its URL, so
AVFoundation identifies the container purely from the response's
`Content-Type`. karaoke-server currently sends `application/octet-stream` for
`.m4a` and `audio/opus` for Ogg-encapsulated Opus, and iOS rejects both with
"Cannot Open" (-11828). Chromium and ExoPlayer sniff the bytes instead, which
is why the desktop and Android clients never hit this.

Measured on iOS 26, same bytes each time:

| Body | `Content-Type` | iOS |
| --- | --- | --- |
| m4a | `application/octet-stream` | ✗ Cannot Open |
| m4a | `audio/mp4` | ✓ plays |
| opus | `audio/opus` | ✗ Cannot Open |
| opus | `audio/ogg` | ✓ plays |

So iOS **does** decode Opus — the server needs a correct header, not a
transcode. This client appends **`client=ios`** to its audio URLs, asking the
server to label the response with a real media type; requests without that
parameter stay exactly as they are, so web and Android are untouched. Until
karaoke-server honours it, this app cannot play anything.

The full spec — evidence, the exact change, backward-compatibility constraints
and acceptance tests — is in
[BACKEND_REQUIREMENTS.md](BACKEND_REQUIREMENTS.md).

`Info.plist` disables App Transport Security (`NSAllowsArbitraryLoads`) because
the LAN server is plain `http://`, and declares `NSLocalNetworkUsageDescription`
for the local-network permission prompt iOS shows on first connection. iOS will
ask once — answer **Allow**, or the library stays empty.

## Layout

```
karaoke/
├── API/{Models,APIClient,AppConfig}.swift    # schema mirrors, REST, server address
├── Player/
│   ├── PlaybackEngine.swift                  # dual-track crossfade + A/V sync
│   ├── PlayerSession.swift                   # current song, queue, lyric offset
│   └── VideoLayerView.swift                  # AVPlayerLayer behind the lyrics
└── Views/
    ├── LibraryView.swift                     # grid, search, singer filter
    ├── PlayerView.swift                      # singing screen + transport
    ├── LyricsCanvas.swift                    # per-frame token wipe
    ├── MiniPlayerBar.swift                   # mini-player, queue, settings sheets
    └── ServerSetupView.swift
```

### How playback stays in sync

Two `AVPlayer`s (original + instrumental) are started on the same host clock
tick via `setRate(_:time:atHostTime:)`, which needs
`automaticallyWaitsToMinimizeStalling = false`. The audible track is the master
clock; a 1 s timer pulls the silent track back if it drifts >0.4 s and the muted
MV if it drifts >0.8 s (wrap-aware when a short MV loops). The per-song
`video_offset_ms` shifts the picture for MVs with burned-in lyrics, exactly as
on desktop.

## Not (yet) ported from desktop

Upload/processing of new songs, offline caching of media, and library editing.
Songs are added from the desktop app; this client sings them.
