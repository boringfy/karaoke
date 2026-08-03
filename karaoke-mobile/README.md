# karaoke-mobile

A Flutter (Android-first) LAN client for [`karaoke-server`](../karaoke-server).
The server does all the work (lyrics, separation, alignment); the tablet is a
thin client that browses the library and plays songs with a smooth karaoke
highlight.

## What it does

- Enter the server's LAN address once (persisted).
- Browse / search the song library with cover art.
- **Player**: MV or cover-art background, transport (play/pause, ±10 s, restart,
  scrub), and the **seamless original ⇄ karaoke (instrumental) toggle** —
  crossfaded, no seek, no gap.
- **Smooth karaoke lyrics**: current line only, per-word (EN) / per-character
  (CJK) wipe rendered on a `Ticker`-driven `CustomPainter` (60 fps), with
  furigana and a dark shadow so it stays readable over any background.

Not yet ported from desktop: upload/processing, play queue, lyric-sync editing,
mini-player. (Songs are added from the desktop app; this client plays them.)

## Why Flutter

Two `just_audio` players run in parallel and crossfade gains for the karaoke
toggle; `AudioPlayer.position` is wall-clock-interpolated, so a per-frame Ticker
drives a jitter-free lyric wipe. The MV plays muted via `video_player` and is
slaved to the audio clock.

## Build & run

Prerequisites: the [Flutter SDK](https://docs.flutter.dev/get-started/install)
and an Android tablet (USB or wireless debugging), on the **same LAN** as the
server.

```bash
cd karaoke-mobile

# Generate the android/ (and ios/) platform folders for this package.
flutter create --org com.boringfy --project-name karaoke_mobile .

flutter pub get
flutter run              # with the tablet connected
```

### Android: allow cleartext HTTP (required)

The LAN server is `http://` (not TLS), which Android blocks by default. After
`flutter create`, edit `android/app/src/main/AndroidManifest.xml` and add to the
`<application>` tag:

```xml
<application
    android:usesCleartextTraffic="true"
    ... >
```

(The `INTERNET` permission is included by Flutter's default manifest.) For a
tighter policy, use a `network_security_config.xml` that permits cleartext only
to your server's subnet instead of the blanket flag.

## Point it at the server

The server must be reachable on the LAN — bind it to all interfaces:

```bash
KARAOKE_HOST=0.0.0.0 karaoke-server        # or set it in ecosystem.config.cjs
```

Find the server's IP (`ip addr` / `ifconfig`), launch the app, and enter e.g.
`192.168.1.50:8787` (port defaults to 8787 if omitted). A native client doesn't
need CORS; that only applies to the web/Electron UI.

## Layout

```
lib/
├── config.dart               # persisted server URL
├── api/{models,client}.dart  # schema mirrors + REST client
├── player/playback_engine.dart  # dual-track crossfade + A/V sync
├── widgets/lyrics_view.dart  # Ticker-driven per-token karaoke wipe
└── screens/{server_setup,library,player}_screen.dart
```
