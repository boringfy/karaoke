# Backend requirement: correct `Content-Type` on audio responses

**Status:** required — the iPadOS client (`karaoke-ios`) cannot play a single
song until this lands.
**Component:** `karaoke-server`
**Size:** one mapping table plus one argument. No new endpoints, no new
parameters, no schema change, no transcoding.
**Date:** 2026-08-23

---

## Summary

`GET /api/v1/songs/{song_id}/audio` returns the right bytes with a
`Content-Type` that misidentifies them. Browser and Android clients sniff the
container from the bytes and don't care; iOS/AVFoundation trusts the header
alone, and refuses to open the stream.

Fix the header. **Do not add a transcoding path** — see [Non-goals](#non-goals).

## Symptom

Every song fails on iPadOS. `AVPlayerItem.status` becomes `.failed` with:

```
Error Domain=AVFoundationErrorDomain Code=-11828 "Cannot Open"
NSLocalizedFailureReason=This media format is not supported.
NSUnderlyingError=NSOSStatusErrorDomain Code=-12847
```

Both tracks fail, so playback has no clock and the song sits frozen at 0:00.

## Root cause

AVFoundation identifies a progressively-downloaded container from **either** the
URL's path extension **or** the response `Content-Type`. This endpoint offers
neither usable signal:

- the URL is `/api/v1/songs/{id}/audio?track=instrumental` — no extension;
- the header is `application/octet-stream` (for `.m4a`) or `audio/opus` (for
  `.opus`).

`FileResponse(path)` is called without `media_type`, so Starlette guesses from
the stored filename. Python's `mimetypes` has no entry for `.m4a`
(→ `application/octet-stream`), and maps `.opus` to `audio/opus`, which is the
media type for **raw Opus packets** — these files are Ogg-encapsulated (magic
bytes `OggS`), whose correct type is `audio/ogg`.

Chromium (Electron player) and ExoPlayer (Flutter client) sniff the bytes, which
is why this has gone unnoticed.

### Evidence

Measured on iOS 26 (iPad simulator), serving byte-identical copies of this
server's own files and varying only the header:

| Body | `Content-Type` | URL extension | Result |
| --- | --- | --- | --- |
| m4a | `application/octet-stream` | none | ✗ FAILED — Cannot Open |
| m4a | `audio/mp4` | none | ✓ READY — plays |
| opus | `audio/opus` | none | ✗ FAILED — Cannot Open |
| opus | `audio/ogg` | none | ✓ READY — plays |
| opus | `audio/ogg` | `.opus` | ✓ READY — plays |

The first and third rows are what the server sends today.

## Required change

In `karaoke_server/api/songs.py`, `stream_audio` (~line 333), currently:

```python
return FileResponse(path)
```

Pass a `media_type` derived from the file suffix:

```python
_AUDIO_MEDIA_TYPES = {
    ".m4a":  "audio/mp4",
    ".mp4":  "audio/mp4",
    ".aac":  "audio/aac",
    ".opus": "audio/ogg",    # Ogg-encapsulated, NOT audio/opus — see below
    ".ogg":  "audio/ogg",
    ".mp3":  "audio/mpeg",
    ".flac": "audio/flac",
    ".wav":  "audio/wav",
    ".aiff": "audio/aiff",
}

media_type = _AUDIO_MEDIA_TYPES.get(Path(path).suffix.lower())
return FileResponse(path, media_type=media_type)  # None keeps today's guess
```

Cover every extension in `media/storage.py::AUDIO_EXTS`, since an uploaded
instrumental keeps whatever format the user supplied.

### The one trap

`.opus` must map to **`audio/ogg`**, not `audio/opus`. `audio/opus` is
registered for raw Opus packets; the pipeline writes Ogg-encapsulated Opus
(`ffmpeg -c:a libopus` → `instrumental.opus`, magic bytes `OggS`). That exact
mislabel is what iOS rejects.

## Non-goals

**Do not add AAC/MP4 transcoding**, a `?codec=` parameter, or a converted-file
cache. The first draft of this document called for one, on the assumption that
iOS cannot decode Opus. That assumption was tested and is false — row 4 of the
evidence table shows iOS playing this server's own Opus file untouched, once it
is labelled `audio/ogg`. A transcoder would add CPU cost, disk cache, and cache
invalidation to solve a problem that a header solves.

## Backward compatibility (hard requirement)

Web and Android must keep working, byte for byte:

- **Response body unchanged.** Same file, same bytes.
- **Status codes unchanged.** 200 / 206 / 404 as today.
- **Range handling unchanged.** `FileResponse` still handles `Range`; seeking
  is unaffected.
- **No API surface change.** No new query parameters, endpoints, or response
  fields, so no client needs to know this happened.
- **Only one header's value changes**, and it changes from wrong to correct.
  Chromium and ExoPlayer sniff content regardless; a correct type is also
  closer to spec for them.

## Acceptance tests

1. Headers are right:

   ```bash
   ID=<any song id>
   curl -sI "http://<server>:8787/api/v1/songs/$ID/audio?track=original"     | grep -i content-type   # audio/mp4  (or the source's real type)
   curl -sI "http://<server>:8787/api/v1/songs/$ID/audio?track=instrumental" | grep -i content-type   # audio/ogg
   ```

2. Range requests still return `206` with a correct `Content-Range`:

   ```bash
   curl -s -o /dev/null -D - -r 0-1023 \
     "http://<server>:8787/api/v1/songs/$ID/audio?track=instrumental" | head -3
   ```

3. **Regression:** the Electron player and the Flutter client both still play a
   song end to end, and seeking still works in both.

4. iPadOS: `karaoke-ios` plays a song with both tracks and the
   original ⇄ karaoke toggle crossfades. (Verified working against a
   header-fixing reverse proxy in front of the live server.)

## Related

- Client that needs this: [`karaoke-ios`](README.md)
- Endpoint: `karaoke_server/api/songs.py::stream_audio`
- Encoder that produces the Opus files:
  `karaoke_server/media/ffmpeg.py::encode_opus`
- `/video` (`video/mp4`) and `/cover` (`image/*`) are already correct; no change
  needed there.
