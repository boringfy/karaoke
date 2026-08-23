# Backend requirement: label served audio with its real container type

**Status:** ✅ **implemented** in karaoke-server, commit *"Label served audio
with its real container type"* (2026-08-23), and verified from the iPad against
the live server.

**As shipped, it differs from the request below in one way:** this document
asked for the corrected header to be opt-in behind `?client=ios`, to guarantee
byte-identical responses for web and Android. The server instead corrects the
header for *every* client, and covers backward compatibility by leaving the
body, status codes and range handling untouched (with regression tests). That
is the better end state — one correct answer rather than two — so the client no
longer sends `client=ios`. The opt-in design is kept below as the record of
what was asked and why.
**Component:** `karaoke-server` — `karaoke_server/api/songs.py::stream_audio`
**Size:** one optional query parameter and one mapping table. No new endpoints,
no response-body change, no schema change, no transcoding.
**Date:** 2026-08-23

---

## Summary

`GET /api/v1/songs/{song_id}/audio` returns the right bytes under a
`Content-Type` that misidentifies them. Browsers and Android sniff the container
from the bytes and don't care; iOS/AVFoundation trusts the header alone and
refuses to open the stream.

Add an **opt-in** query parameter, `client=ios`, that makes the server label the
response with a real audio media type. Without the parameter the response stays
byte-for-byte and header-for-header what it is today.

**Do not add a transcoding path** — see [Non-goals](#non-goals).

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
is why this went unnoticed.

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

Rows 1 and 3 are what the server sends today.

## Required change

In `karaoke_server/api/songs.py`, `stream_audio` (~line 333):

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
    ".wma":  "audio/x-ms-wma",
}


@router.get("/{song_id}/audio")
async def stream_audio(
    song_id: str,
    track: Literal["original", "instrumental"] = "instrumental",
    client: str | None = Query(
        default=None,
        description="Set to 'ios' for clients that need an explicit audio "
                    "media type (AVFoundation cannot sniff the container).",
    ),
    session: AsyncSession = Depends(get_session),
):
    ...
    # Existing lookup and 404 handling stay exactly as they are.
    if client == "ios":
        return FileResponse(path, media_type=_AUDIO_MEDIA_TYPES.get(Path(path).suffix.lower()))
    return FileResponse(path)          # unchanged for every other client
```

Cover every extension in `media/storage.py::AUDIO_EXTS`, since an uploaded
instrumental keeps whatever format the user supplied. An unknown suffix should
fall through to today's behaviour (`media_type=None`) rather than error.

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
is labelled `audio/ogg`. A transcoder would add CPU cost, a disk cache, and
cache invalidation to solve what a header solves.

## Backward compatibility (hard requirement)

Web and Android must keep working, byte for byte. The opt-in parameter
guarantees it:

- **A request without `client=ios` is completely unchanged** — same bytes, same
  headers, same status codes. Existing clients cannot observe this change.
- **Response body never changes**, with or without the parameter. Only the
  `Content-Type` header value differs.
- **Range handling unchanged.** `FileResponse` still serves `Range` requests;
  seeking is unaffected on both paths.
- **No breaking API surface.** The parameter is optional; unknown values behave
  like absent ones. No response field is added or removed.

## Acceptance tests

1. The parameter is opt-in and the default path is untouched.

   **Do not use `curl -I` here.** It sends `HEAD`, the route is `GET`-only, and
   the resulting `405` with a JSON error body looks exactly like a broken fix.
   Read the headers off a `GET` instead:

   ```bash
   ID=<any song id>
   BASE=http://<server>:8787/api/v1/songs/$ID/audio
   headers() { curl -s -o /dev/null -D - -r 0-99 "$1" | grep -i '^content-type'; }

   headers "$BASE?track=instrumental"            # unchanged from before the fix
   headers "$BASE?track=instrumental&client=ios" # audio/ogg
   headers "$BASE?track=original&client=ios"     # audio/mp4
   ```

2. Range requests still return `206` with a correct `Content-Range`, on both
   paths:

   ```bash
   curl -s -o /dev/null -D - -r 0-1023 "$BASE?track=instrumental&client=ios" | head -3
   ```

3. Bodies are identical with and without the parameter:

   ```bash
   curl -s "$BASE?track=instrumental"            | shasum
   curl -s "$BASE?track=instrumental&client=ios" | shasum   # same hash
   ```

4. **Regression:** the Electron player and the Flutter client each still play a
   song end to end, and seeking still works in both.

5. iPadOS: `karaoke-ios` plays a song with both tracks, and the
   original ⇄ karaoke toggle crossfades.

## Is `HEAD` worth supporting?

Not for this client. Measured against a logging proxy while the iPad played a
song, AVFoundation issued **7 GETs and zero HEADs**, opening with a
`Range: bytes=0-1` probe before requesting the body. So the route staying
`GET`-only cannot break playback, and no change is required. It is only a trap
for humans running the acceptance tests with `curl -I` (see test 1).

## Client side

`karaoke-ios` sends no special parameter: the server labels audio correctly for
everyone, so `audioURL(_:track:)` requests the plain URL. The client cannot play
against a karaoke-server older than the commit above.

Verified from the iPad simulator directly against the live server — no proxy in
the path — playing MV, audio and karaoke lyrics.

## Related

- Client that needs this: [`karaoke-ios`](README.md)
- Endpoint: `karaoke_server/api/songs.py::stream_audio`
- Encoder that produces the Opus files:
  `karaoke_server/media/ffmpeg.py::encode_opus`
- `/video` (`video/mp4`) and `/cover` (`image/*`) are already correct; no change
  needed there.
