# Backend requirements for the iPadOS client

Two requirements, in the order they were found. The first is **implemented**;
the second is **open and blocking**, and it reverses a "non-goal" this document
previously stated. Read requirement 2 before acting on the non-goal in
requirement 1.

---

# Requirement 2 (OPEN, BLOCKING): offer Opus audio as AAC

**Status:** ❌ open — 20 of 37 songs cannot be played on the test iPad.
**Component:** `karaoke-server` — `karaoke_server/api/songs.py::stream_audio`

## The correction

Requirement 1 below says, in bold, *"do not add a transcoding path"*, on the
grounds that iOS decodes Opus once the header is right. **That is true only on
iOS 26.** It was measured on an iOS 26 simulator and wrongly generalised to
"iOS". Measured on the actual test device:

```
os = Version 18.1.1 (Build 22B91)      iPad Pro 13-inch (M4)
opus/ogg  | FAILED  Cannot Open
mp3       | READY   253.8
flac      | READY   344.6
m4a/aac   | READY   242.0
```

AVFoundation on iOS 18 cannot decode Ogg/Opus at all. The header fix in
requirement 1 was still necessary and correct — it is what makes mp3, flac and
m4a work — but it is not sufficient.

## Impact

`encode_opus()` is the default for generated instrumentals, so Opus dominates
the library. Of 37 songs, by served content type:

| | songs |
| --- | --- |
| both tracks Opus → **will not play at all** | 20 |
| one track Opus → plays, but no karaoke toggle | 16 |
| neither track Opus → fully fine | 1 |

## What is needed

`GET /api/v1/songs/{id}/audio` should be able to return AAC-in-MP4 for a client
that asks, e.g. `?codec=aac`:

- If the stored file is already playable as-is (mp3, flac, m4a/aac), serve it
  unchanged — do not re-encode.
- If it is Opus, serve an AAC/MP4 transcode. Transcode once and cache it beside
  the source (`instrumental.aac.m4a`), keyed so a replaced source invalidates it
  (mtime or the sha the pipeline already computes); later requests serve the
  cached file so `Range` and seeking keep working.
- `ffmpeg -i in.opus -vn -c:a aac -b:a 192k -movflags +faststart out.m4a`.
  `+faststart` matters: it moves the moov atom to the front for progressive
  HTTP playback.
- Write to a temp file and rename, so two concurrent requests cannot serve a
  half-written file.
- Content type `audio/mp4`, per requirement 1.

**Backward compatibility, same rule as before:** without `?codec=aac` the
response must stay exactly as it is today. Web and Android decode Opus happily
and must keep getting the original bytes — this is opt-in, for clients that
cannot.

## Acceptance tests

Use a song whose tracks are Opus (e.g. `可愛くてごめん`,
`06895e44f93c4dd889b0eb3602f0b75f`) and one already playable (`金曜日のおはよう`,
`d539bca4c6104d91bf986ecac44df2ca`, original is m4a).

As in requirement 1, read headers off a `GET` — `curl -I` sends HEAD and this
route answers 405.

```bash
OPUS=06895e44f93c4dd889b0eb3602f0b75f
M4A=d539bca4c6104d91bf986ecac44df2ca
API=http://<server>:8787/api/v1/songs
headers() { curl -s -o /dev/null -D - -r 0-1 "$1" | grep -i '^content-type'; }
```

1. **Opt-in only.** Without the parameter the response is untouched:
   `headers "$API/$OPUS/audio?track=original"` → `audio/ogg`, and the body hash
   matches what it was before the change.

2. **Opus is transcoded.** `headers "$API/$OPUS/audio?track=original&codec=aac"`
   → `audio/mp4`, and the body really is AAC:

   ```bash
   curl -s "$API/$OPUS/audio?track=original&codec=aac" -o /tmp/t.m4a
   ffprobe -v error -show_entries stream=codec_name -of csv=p=0 /tmp/t.m4a   # aac
   ```

3. **Playable formats are NOT re-encoded.** `headers "$API/$M4A/audio?track=original&codec=aac"`
   → `audio/mp4`, and the bytes are identical to the no-parameter response
   (compare `shasum`). Re-encoding an m4a would lose quality for nothing.

4. **Duration survives.** The transcode's duration matches the source within a
   second — a wrong duration desynchronises the lyric wipe.

5. **Range works on the transcode**, since seeking depends on it:
   `curl -s -o /dev/null -D - -r 0-1023 "$API/$OPUS/audio?track=original&codec=aac"`
   → `206` with a correct `Content-Range`.

6. **Cached, not re-encoded per request.** Time the first and second calls; the
   second should be immediate. Replacing the source audio must invalidate it.

7. **Regression:** the Electron player and the Flutter client still play a song
   and still seek. Neither sends `codec`, so neither should observe any change.

8. **Device:** on the iPad (iOS 18), `可愛くてごめん` plays, and songs with one
   Opus track regain the original ⇄ karaoke toggle.

## Alternative considered

Configuring the pipeline to stop producing Opus (`instrumental_bitrate = ""`
keeps WAV) fixes new songs only, leaves the existing 36 broken, and WAV is
several times the size over the LAN. Transcode-on-demand with a cache handles
the existing library and costs one encode per song, once.

---

# Requirement 1 (IMPLEMENTED): label served audio with its real container type

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
