# Karaoke Server — API Reference

Base URL: `http://127.0.0.1:8787`
All application endpoints are under the `/api/v1` prefix.
Interactive docs (Swagger UI) are served at `/docs` when the server is running.

---

## The workflow at a glance

A song is created first as a metadata record, then files are attached to it by
id. Nothing is processed until an **original** audio file is uploaded.

```
1. POST /api/v1/songs                     -> create song, returns {id}
2. POST /api/v1/songs/{id}/audio          -> upload mp3 (kind=original)
        (auto-runs: ingest -> lyrics -> align -> annotate -> render)
3. (optional) POST /api/v1/songs/{id}/video    -> upload the MV
4. (optional) POST /api/v1/songs/{id}/audio?kind=instrumental  -> your own karaoke track
5. (optional) POST /api/v1/songs/{id}/separate -> generate instrumental by removing vocals
6. GET  /api/v1/songs/{id}/events         -> watch pipeline progress (SSE)
7. GET  /api/v1/songs/{id}/subtitle       -> timed karaoke lyrics for the UI
8. GET  /api/v1/songs/{id}/audio?track=instrumental -> stream for playback
```

Vocal removal (step 5) is **never automatic** — it is a manual action, because
it is expensive and many users already own an instrumental version.

---

## Song status values

| status         | meaning                                                        |
|----------------|----------------------------------------------------------------|
| `pending`      | created; no processing has produced a subtitle yet             |
| `processing`   | one or more pipeline stages are queued or running              |
| `ready`        | subtitle generated with acceptable alignment confidence        |
| `needs_review` | subtitle generated but confidence is low — check/fix timing    |
| `failed`       | the most recent pipeline chain ended in an error               |

---

## Songs

### Create a song
`POST /api/v1/songs`

Step 1 of the workflow. Creates the metadata record and returns its id.

Request body (JSON):
```json
{ "title": "夜に駆ける", "artist": "YOASOBI", "album": "THE BOOK", "language": "ja" }
```
- `title` (required)
- `artist`, `album` (optional)
- `language` (optional): `en` | `zh` | `ja` | `unknown` (default). If `unknown`,
  the language is auto-detected from the fetched lyrics.

Response `201`: the full song object (see [Song object](#song-object)).

```bash
curl -X POST http://127.0.0.1:8787/api/v1/songs \
  -H 'Content-Type: application/json' \
  -d '{"title":"Twinkle","artist":"Trad","language":"en"}'
```

### List songs
`GET /api/v1/songs`

Query params: `status`, `language`, `q` (fuzzy title/artist match),
`limit` (default 50, max 500), `offset`.

Response `200`:
```json
{ "total": 12, "items": [ { ...song... }, ... ] }
```

### Get one song
`GET /api/v1/songs/{id}` → `200` song object, `404` if missing.

### Update metadata
`PATCH /api/v1/songs/{id}`

Body: any subset of `title`, `artist`, `album`, `language`. Response `200`.

### Delete a song
`DELETE /api/v1/songs/{id}` → `204`. Removes the DB row and all files on disk.

---

## File uploads

### Upload audio
`POST /api/v1/songs/{id}/audio`  (multipart/form-data)

| field  | type | notes |
|--------|------|-------|
| `file` | file | audio file (`.mp3 .flac .wav .m4a .aac .ogg .opus .wma .aiff`) |
| `kind` | text | `original` (default) or `instrumental` |

- **`kind=original`** — the normal song, with vocals. Stored, de-duplicated by
  SHA-256, and the automatic pipeline is enqueued (ingest, lyrics, align,
  annotate, render). Re-uploading the exact same file to a *different* song
  returns `409`.
- **`kind=instrumental`** — a karaoke track you already own. Stored for
  playback; no processing is triggered. `instrumental_source` becomes
  `"uploaded"`. If the song has **no original** file, uploading an instrumental
  moves it straight to `ready` (it is playable without lyrics/subtitles).

Response `201`:
```json
{ "song_id": "…", "kind": "original", "path_name": "original.mp3",
  "sha256": "…", "enqueued_stages": ["ingest","lyrics","align","annotate","render"] }
```
Errors: `404` unknown song, `415` unsupported extension, `409` duplicate.

```bash
# original (triggers the pipeline)
curl -X POST http://127.0.0.1:8787/api/v1/songs/$ID/audio \
  -F kind=original -F file=@song.mp3

# your own instrumental (no processing)
curl -X POST http://127.0.0.1:8787/api/v1/songs/$ID/audio \
  -F kind=instrumental -F file=@song_karaoke.mp3
```

### Upload a music video (MV)
`POST /api/v1/songs/{id}/video`  (multipart/form-data)

`file`: video (`.mp4 .mkv .webm .mov .avi .ts`). Response `201` (same shape as
audio upload). Errors: `404`, `415`.

### Upload cover art
`POST /api/v1/songs/{id}/cover`  (multipart/form-data)

`file`: image (`.jpg .jpeg .png .webp .gif`) for library artwork and the
playback background when there is no MV. Response `201`. Errors: `404`, `415`.

Cover art embedded in the audio tags is extracted **automatically** during
ingest; a cover uploaded here takes precedence over the embedded one.

---

## Media playback

### Stream audio
`GET /api/v1/songs/{id}/audio?track=instrumental`

`track`: `instrumental` (default) or `original`. Serves the file with HTTP
range support for seeking. `404` if that track does not exist.

### Stream video
`GET /api/v1/songs/{id}/video` → the MV, or `404`.

### Get cover art
`GET /api/v1/songs/{id}/cover` → the cover image, or `404`.

### Get subtitle / timed lyrics
`GET /api/v1/songs/{id}/subtitle?format=json`

| format | description |
|--------|-------------|
| `json` | **canonical** karaoke document — per-line and per-token timing plus furigana ruby; this is what the UI renders |
| `lrc`  | plain line-level LRC |
| `elrc` | enhanced LRC with A2 word-timing tags (ruby dropped) |
| `srt`  | SubRip, line-level |
| `ass`  | Advanced SubStation Alpha karaoke (`\k` sweeps + furigana layer) |

`404` if the subtitle has not been generated yet. See
[Subtitle JSON](#subtitle-json-format) for the schema.

### Set subtitle timing offset
`PATCH /api/v1/songs/{id}/subtitle/offset`

```json
{ "offset_ms": -250 }
```

Persists a global lyric timing shift. Stored on the song record
(`subtitle_offset_ms` in the song object) **and** written into `subtitle.json`;
the LRC/ASS/SRT exports are re-rendered. Because the song record is the source
of truth, the offset survives re-alignment / reprocessing — the align stage
re-applies it to the regenerated subtitle. Positive values make subtitles
appear **later** relative to the audio. Range: ±60000 ms (`422` outside it).
Returns the stored value; `404` if the subtitle has not been generated yet.

---

## Lyrics

### Get selected lyrics
`GET /api/v1/songs/{id}/lyrics` → the raw selected lyrics (`lyrics.raw.json`),
or `404` if none selected.

### List fetched candidates
`GET /api/v1/songs/{id}/lyrics/candidates`

Response `200`: array of candidates, best score first:
```json
[ { "id":"…","provider":"lrclib","title":"…","artist":"…",
    "duration_sec":213.0,"is_synced":true,"score":0.94,"selected":true } ]
```

### Select a candidate
`POST /api/v1/songs/{id}/lyrics/select`

Body: `{ "candidate_id": "…" }`. Marks it selected and re-runs
align → annotate → render. Response `202` with `enqueued_stages`.

### Override lyrics manually
`PUT /api/v1/songs/{id}/lyrics`

Body (provide `text`, `lrc`, or both):
```json
{ "text": "line one\nline two", "lrc": "[00:01.00]line one\n[00:05.20]line two" }
```
Saves the lyrics, deselects any candidate, and re-aligns. If an `lrc` is
provided, its line timestamps are used as alignment anchors. Response `202`.

### Upload a lyrics file
`POST /api/v1/songs/{id}/lyrics/upload`  (multipart/form-data)

`file`: a lyrics file. Format is chosen by extension:
- `.lrc` — synced lyrics; the line timestamps become alignment anchors.
- `.txt` / no extension — plain lyrics, one line per lyric line.

The file is decoded as UTF-8 (a byte-order mark is tolerated). The lyrics are
saved, any selected candidate is deselected, and the song is re-aligned.
Response `202` with `enqueued_stages`. Errors: `415` (bad extension), `422`
(not UTF-8, or empty).

```bash
curl -X POST http://127.0.0.1:8787/api/v1/songs/$ID/lyrics/upload \
  -F file=@song.lrc
```

> Prefer sending lyrics as JSON? Use `PUT /api/v1/songs/{id}/lyrics` above.

### Re-fetch from providers
`POST /api/v1/songs/{id}/lyrics/refetch` → re-runs the provider search, then
re-aligns if a match is found. Response `202`.

---

## Processing controls

### Generate instrumental (remove vocals)
`POST /api/v1/songs/{id}/separate?force=false`

Manually run source separation on the **original** track. Produces an
instrumental (for playback) and a vocal stem (used to sharpen alignment), then
re-aligns the lyrics against the cleaner vocals.

- Requires an original file (`409` otherwise).
- If an instrumental was **uploaded**, this refuses to overwrite it unless
  `force=true` (`409`).
- `409` if a separation job is already queued or running.

Response `202`:
```json
{ "detail": "separation queued", "enqueued_stages": ["separate","align","annotate","render"] }
```

### Reprocess from a stage
`POST /api/v1/songs/{id}/reprocess?from=align`

Re-run the pipeline from a given stage onward. `from` ∈
`ingest | lyrics | align | annotate | render` (default `align`). Response `202`.

---

## Jobs & progress

### List jobs for a song
`GET /api/v1/songs/{id}/jobs` → array of job records in execution order:
```json
[ { "stage":"align","state":"done","progress":1.0,"error":null,"attempts":1,
    "created_at":"…","started_at":"…","finished_at":"…" } ]
```
Job `state`: `queued | running | done | failed | skipped`.

### Progress stream (Server-Sent Events)
`GET /api/v1/songs/{id}/events`

An SSE stream that emits the song status and per-stage states about once a
second while the pipeline is active, then sends an `end` event and closes.

```
data: {"status":"processing","alignment_confidence":null,
       "jobs":[{"stage":"ingest","state":"done","error":null},
               {"stage":"align","state":"running","error":null}]}

event: end
data: {}
```

```js
const es = new EventSource(`/api/v1/songs/${id}/events`);
es.onmessage = (e) => updateUI(JSON.parse(e.data));
es.addEventListener("end", () => es.close());
```

---

## Meta

- `GET /health` → `{ "status": "ok", "version": "…" }`
- `GET /config` → effective server settings (data dir, device, models, …)

---

## Song object

```json
{
  "id": "3f2c…",
  "title": "夜に駆ける",
  "artist": "YOASOBI",
  "album": "THE BOOK",
  "language": "ja",
  "duration_sec": 261.3,
  "status": "ready",
  "alignment_confidence": 0.87,
  "instrumental_source": "generated",
  "subtitle_offset_ms": 0,
  "has_original": true,
  "has_instrumental": true,
  "has_video": false,
  "has_cover": true,
  "has_lyrics": true,
  "has_subtitle": true,
  "created_at": "2026-07-22T06:00:00Z",
  "updated_at": "2026-07-22T06:03:00Z"
}
```

`instrumental_source`: `"uploaded"` (user provided) or `"generated"`
(produced by the separate stage); `null` if there is no instrumental.

---

## Subtitle JSON format

The canonical, versioned document the karaoke UI consumes. `start`/`end` are
seconds. `tokens` are the highlightable units — words for English, characters
(or small kanji runs with ruby) for Chinese/Japanese.

```json
{
  "schema": 1,
  "lang": "ja",
  "title": "夜に駆ける",
  "artist": "YOASOBI",
  "offset_ms": 0,
  "lines": [
    {
      "id": "L0000",
      "start": 61.42,
      "end": 65.90,
      "text": "君の名前を呼ぶ",
      "translation": null,
      "score": 0.91,
      "alignment": "aligned",
      "tokens": [
        { "text": "君",   "ruby": "きみ", "ruby_source": "auto", "start": 61.42, "end": 61.83, "p": 0.95 },
        { "text": "の",   "start": 61.83, "end": 62.01, "p": 0.97 },
        { "text": "名前", "ruby": "なまえ", "ruby_source": "auto", "start": 62.01, "end": 62.90, "p": 0.90 }
      ]
    }
  ]
}
```

Field notes:
- `alignment`: `"aligned"` (timestamps from forced alignment) or
  `"interpolated"` (alignment failed sanity checks; timing came from LRC
  anchors or neighbor interpolation — the UI should flag these for review).
- `score`: mean aligner confidence for the line (0–1); `p` is the per-token
  probability.
- `ruby`: hiragana reading, present only over kanji in Japanese songs.
  `ruby_source` is `"auto"` (from the tokenizer) or `"manual"` (a saved edit,
  preserved across re-annotation).
- `translation`: reserved slot for a future translation line; currently `null`.
