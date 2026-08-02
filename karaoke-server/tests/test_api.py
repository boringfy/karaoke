"""API integration tests with the pipeline worker disabled (jobs stay queued;
we assert on what gets enqueued)."""

from __future__ import annotations

import io
import struct
import wave

import httpx
import pytest_asyncio


def make_wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        n = int(8000 * seconds)
        w.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return buf.getvalue()


@pytest_asyncio.fixture
async def client(settings, monkeypatch):
    from karaoke_server.pipeline.worker import PipelineWorker

    async def no_start(self):
        return None

    monkeypatch.setattr(PipelineWorker, "start", no_start)

    from karaoke_server.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _create_song(client) -> str:
    r = await client.post(
        "/api/v1/songs",
        json={"title": "Test Song", "artist": "Test Singer", "language": "en"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_song_crud_and_upload_flow(client):
    song_id = await _create_song(client)

    # Empty song: no files yet.
    r = await client.get(f"/api/v1/songs/{song_id}")
    body = r.json()
    assert body["status"] == "pending"
    assert body["has_original"] is False

    # Upload original audio -> auto pipeline enqueued.
    r = await client.post(
        f"/api/v1/songs/{song_id}/audio",
        files={"file": ("song.wav", make_wav(), "audio/wav")},
        data={"kind": "original"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["enqueued_stages"] == [
        "ingest", "lyrics", "align", "annotate", "render",
    ]

    # Jobs visible and queued (worker is disabled in tests).
    r = await client.get(f"/api/v1/songs/{song_id}/jobs")
    stages = [j["stage"] for j in r.json()]
    assert stages == ["ingest", "lyrics", "align", "annotate", "render"]
    assert all(j["state"] == "queued" for j in r.json())

    # Upload an instrumental: stored, no pipeline.
    r = await client.post(
        f"/api/v1/songs/{song_id}/audio",
        files={"file": ("inst.wav", make_wav(), "audio/wav")},
        data={"kind": "instrumental"},
    )
    assert r.status_code == 201
    assert r.json()["enqueued_stages"] == []

    r = await client.get(f"/api/v1/songs/{song_id}")
    body = r.json()
    assert body["has_original"] and body["has_instrumental"]
    assert body["instrumental_source"] == "uploaded"

    # Stream the instrumental back.
    r = await client.get(f"/api/v1/songs/{song_id}/audio?track=instrumental")
    assert r.status_code == 200
    assert r.content[:4] == b"RIFF"


async def test_duplicate_original_rejected(client):
    song1 = await _create_song(client)
    r = await client.post(
        "/api/v1/songs", json={"title": "Other", "artist": "Someone"}
    )
    song2 = r.json()["id"]
    wav = make_wav(2.0)
    r = await client.post(
        f"/api/v1/songs/{song1}/audio",
        files={"file": ("a.wav", wav, "audio/wav")},
        data={"kind": "original"},
    )
    assert r.status_code == 201
    r = await client.post(
        f"/api/v1/songs/{song2}/audio",
        files={"file": ("b.wav", wav, "audio/wav")},
        data={"kind": "original"},
    )
    assert r.status_code == 409


async def test_video_upload_and_bad_extension(client):
    song_id = await _create_song(client)
    r = await client.post(
        f"/api/v1/songs/{song_id}/video",
        files={"file": ("mv.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
    )
    assert r.status_code == 201
    r = await client.get(f"/api/v1/songs/{song_id}")
    assert r.json()["has_video"] is True

    r = await client.post(
        f"/api/v1/songs/{song_id}/audio",
        files={"file": ("notes.txt", b"hi", "text/plain")},
        data={"kind": "original"},
    )
    assert r.status_code == 415


async def test_instrumental_only_song_becomes_ready(client):
    """A song with only an instrumental (no original) must be playable, not
    stuck pending forever."""
    song_id = await _create_song(client)
    r = await client.post(
        f"/api/v1/songs/{song_id}/audio",
        files={"file": ("inst.wav", make_wav(), "audio/wav")},
        data={"kind": "instrumental"},
    )
    assert r.status_code == 201
    assert r.json()["enqueued_stages"] == []
    r = await client.get(f"/api/v1/songs/{song_id}")
    body = r.json()
    assert body["status"] == "ready"
    assert body["has_instrumental"] and not body["has_original"]


async def test_cover_upload_and_serve(client):
    song_id = await _create_song(client)
    # 1x1 PNG.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000d4944415478da6360000002000154a24f9f0000000049454e44ae426082"
    )
    r = await client.post(
        f"/api/v1/songs/{song_id}/cover",
        files={"file": ("art.png", png, "image/png")},
    )
    assert r.status_code == 201
    r = await client.get(f"/api/v1/songs/{song_id}")
    assert r.json()["has_cover"] is True
    r = await client.get(f"/api/v1/songs/{song_id}/cover")
    assert r.status_code == 200
    assert r.content[:8] == png[:8]


async def test_cover_bad_extension_and_404(client):
    song_id = await _create_song(client)
    r = await client.get(f"/api/v1/songs/{song_id}/cover")
    assert r.status_code == 404
    r = await client.post(
        f"/api/v1/songs/{song_id}/cover",
        files={"file": ("art.bmp", b"BM", "image/bmp")},
    )
    assert r.status_code == 415


async def test_separate_requires_original(client):
    song_id = await _create_song(client)
    r = await client.post(f"/api/v1/songs/{song_id}/separate")
    assert r.status_code == 409


async def test_manual_lyrics_enqueues_realign(client):
    song_id = await _create_song(client)
    r = await client.post(
        f"/api/v1/songs/{song_id}/audio",
        files={"file": ("song.wav", make_wav(3.0), "audio/wav")},
        data={"kind": "original"},
    )
    assert r.status_code == 201
    r = await client.put(
        f"/api/v1/songs/{song_id}/lyrics",
        json={"lrc": "[00:01.00]hello world\n[00:02.00]goodbye"},
    )
    assert r.status_code == 202, r.text
    # align/annotate/render were already queued by the upload, so no dupes.
    r = await client.get(f"/api/v1/songs/{song_id}/lyrics")
    assert r.status_code == 200
    assert "hello world" in r.text


async def test_upload_lrc_file(client):
    song_id = await _create_song(client)
    lrc = "[ti:Twinkle]\n[00:01.00]twinkle twinkle\n[00:03.00]little star\n"
    r = await client.post(
        f"/api/v1/songs/{song_id}/lyrics/upload",
        files={"file": ("song.lrc", lrc.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 202, r.text
    assert r.json()["enqueued_stages"] == ["align", "annotate", "render"]
    # Stored and readable back, with the LRC preserved.
    r = await client.get(f"/api/v1/songs/{song_id}/lyrics")
    body = r.json()
    assert "twinkle twinkle" in body["text"]
    assert body["lrc"] is not None and "[00:01.00]" in body["lrc"]


async def test_upload_plain_txt_file(client):
    song_id = await _create_song(client)
    text = "line one\nline two\nline three"
    r = await client.post(
        f"/api/v1/songs/{song_id}/lyrics/upload",
        files={"file": ("song.txt", text.encode("utf-8"), "text/plain")},
    )
    assert r.status_code == 202
    r = await client.get(f"/api/v1/songs/{song_id}/lyrics")
    body = r.json()
    assert body["text"] == text
    assert body["lrc"] is None


async def test_upload_lyrics_bom_and_bad_ext(client):
    song_id = await _create_song(client)
    # UTF-8 BOM tolerated.
    r = await client.post(
        f"/api/v1/songs/{song_id}/lyrics/upload",
        files={"file": ("l.txt", "﻿歌詞".encode("utf-8-sig"), "text/plain")},
    )
    assert r.status_code == 202
    # Wrong extension rejected.
    r = await client.post(
        f"/api/v1/songs/{song_id}/lyrics/upload",
        files={"file": ("l.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 415


async def test_subtitle_404_before_processing(client):
    song_id = await _create_song(client)
    r = await client.get(f"/api/v1/songs/{song_id}/subtitle")
    assert r.status_code == 404


async def test_subtitle_offset_update(client):
    from karaoke_server.db.models import Song
    from karaoke_server.db.session import session_factory
    from karaoke_server.media import storage
    from karaoke_server.subtitles.schema import Line, SubtitleDoc, Token

    song_id = await _create_song(client)

    # No subtitle yet -> 404.
    r = await client.patch(
        f"/api/v1/songs/{song_id}/subtitle/offset", json={"offset_ms": 100}
    )
    assert r.status_code == 404

    # Plant a minimal subtitle.json as if alignment had run.
    doc = SubtitleDoc(
        lang="en",
        lines=[
            Line(
                id="l1", start=1.0, end=2.0, text="hi",
                tokens=[Token(text="hi", start=1.0, end=2.0)],
            )
        ],
    )
    path = storage.song_dir(song_id) / "subtitle.json"
    storage.atomic_write_text(path, doc.dump_json())
    async with session_factory()() as session:
        song = await session.get(Song, song_id)
        song.subtitle_json_path = str(path)
        await session.commit()

    r = await client.patch(
        f"/api/v1/songs/{song_id}/subtitle/offset", json={"offset_ms": -250}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"offset_ms": -250}

    # Persisted into subtitle.json...
    r = await client.get(f"/api/v1/songs/{song_id}/subtitle")
    assert r.json()["offset_ms"] == -250

    # ...and onto the song record, so re-alignment can re-apply it.
    r = await client.get(f"/api/v1/songs/{song_id}")
    assert r.json()["subtitle_offset_ms"] == -250

    # ...and the exports were re-rendered with the offset tag.
    r = await client.get(
        f"/api/v1/songs/{song_id}/subtitle", params={"format": "lrc"}
    )
    assert "[offset:-250]" in r.text

    # Out-of-range values rejected.
    r = await client.patch(
        f"/api/v1/songs/{song_id}/subtitle/offset", json={"offset_ms": 999_999}
    )
    assert r.status_code == 422


async def test_delete_song(client):
    song_id = await _create_song(client)
    r = await client.delete(f"/api/v1/songs/{song_id}")
    assert r.status_code == 204
    r = await client.get(f"/api/v1/songs/{song_id}")
    assert r.status_code == 404
