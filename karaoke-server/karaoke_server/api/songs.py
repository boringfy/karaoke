from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AUTO_STAGES, REALIGN_STAGES, Job, Song, SongStatus, Stage
from ..db.session import get_session
from ..media import storage
from ..pipeline.worker import enqueue_stages
from ..subtitles import exporters, render
from ..subtitles.schema import SubtitleDoc
from .schemas import (
    MessageOut,
    SongCreate,
    SongList,
    SongOut,
    SongUpdate,
    SubtitleOffset,
    UploadResult,
)

router = APIRouter(prefix="/songs", tags=["songs"])

_SUBTITLE_MEDIA_TYPES = {
    "json": "application/json",
    "lrc": "text/plain; charset=utf-8",
    "elrc": "text/plain; charset=utf-8",
    "srt": "text/plain; charset=utf-8",
    "ass": "text/plain; charset=utf-8",
}


async def _get_song(song_id: str, session: AsyncSession) -> Song:
    song = await session.get(Song, song_id)
    if song is None:
        raise HTTPException(404, "song not found")
    return song


def _song_out(song: Song) -> SongOut:
    out = SongOut.model_validate(song)
    out.has_original = bool(song.original_path and Path(song.original_path).exists())
    out.has_instrumental = bool(
        song.instrumental_path and Path(song.instrumental_path).exists()
    )
    out.has_video = bool(song.video_path and Path(song.video_path).exists())
    out.has_cover = bool(song.cover_path and Path(song.cover_path).exists())
    out.has_lyrics = bool(song.lyrics_path and Path(song.lyrics_path).exists())
    out.has_subtitle = bool(
        song.subtitle_json_path and Path(song.subtitle_json_path).exists()
    )
    return out


# ------------------------------------------------------------------ CRUD

@router.post("", response_model=SongOut, status_code=201)
async def create_song(body: SongCreate, session: AsyncSession = Depends(get_session)):
    """Step 1 of the workflow: create the song entry, get its id, then upload
    files against that id."""
    song = Song(
        title=body.title, artist=body.artist, album=body.album, language=body.language
    )
    session.add(song)
    await session.commit()
    return _song_out(song)


@router.get("", response_model=SongList)
async def list_songs(
    session: AsyncSession = Depends(get_session),
    status: str | None = None,
    language: str | None = None,
    q: str | None = Query(default=None, description="fuzzy title/artist filter"),
    limit: int = Query(default=50, le=500),
    offset: int = 0,
):
    stmt = select(Song)
    if status:
        stmt = stmt.where(Song.status == status)
    if language:
        stmt = stmt.where(Song.language == language)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Song.title.ilike(like), Song.artist.ilike(like)))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        (await session.execute(stmt.order_by(Song.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return SongList(total=total or 0, items=[_song_out(s) for s in rows])


@router.get("/{song_id}", response_model=SongOut)
async def get_song(song_id: str, session: AsyncSession = Depends(get_session)):
    return _song_out(await _get_song(song_id, session))


@router.patch("/{song_id}", response_model=SongOut)
async def update_song(
    song_id: str, body: SongUpdate, session: AsyncSession = Depends(get_session)
):
    song = await _get_song(song_id, session)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(song, field, value)
    await session.commit()
    return _song_out(song)


@router.delete("/{song_id}", status_code=204)
async def delete_song(song_id: str, session: AsyncSession = Depends(get_session)):
    song = await _get_song(song_id, session)
    await session.delete(song)
    await session.commit()
    storage.delete_song_files(song_id)
    return Response(status_code=204)


# ------------------------------------------------------------------ uploads

@router.post("/{song_id}/audio", response_model=UploadResult, status_code=201)
async def upload_audio(
    song_id: str,
    file: UploadFile = File(...),
    kind: Literal["original", "instrumental"] = Form("original"),
    session: AsyncSession = Depends(get_session),
):
    """Step 2: upload an audio file for the song.

    kind=original      the normal song, with vocals — triggers the automatic
                       pipeline (metadata, lyrics fetch, alignment, subtitle)
    kind=instrumental  a karaoke version you already have — stored for
                       playback; no vocal removal needed
    """
    song = await _get_song(song_id, session)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in storage.AUDIO_EXTS:
        raise HTTPException(
            415, f"unsupported audio extension {ext!r}; use one of "
            f"{sorted(storage.AUDIO_EXTS)}"
        )
    dest = storage.song_dir(song_id)
    path, sha = await storage.save_upload(dest, kind, file.filename or "", file)

    enqueued: list[str] = []
    if kind == "original":
        dupe = await session.scalar(
            select(Song).where(Song.source_hash == sha, Song.id != song_id)
        )
        if dupe:
            path.unlink(missing_ok=True)
            raise HTTPException(
                409, f"this exact file is already uploaded as song {dupe.id}"
            )
        song.original_path = str(path)
        song.original_format = ext.lstrip(".")
        song.source_hash = sha
        jobs = await enqueue_stages(session, song_id, AUTO_STAGES)
        enqueued = [j.stage for j in jobs]
    else:
        song.instrumental_path = str(path)
        song.instrumental_source = "uploaded"
        # An instrumental with no original is directly playable (no lyrics
        # pipeline will run), so promote it out of `pending` to `ready`.
        if not song.original_path and song.status == SongStatus.pending.value:
            song.status = SongStatus.ready.value
    await session.commit()
    return UploadResult(
        song_id=song_id, kind=kind, path_name=path.name, sha256=sha,
        enqueued_stages=enqueued,
    )


@router.post("/{song_id}/video", response_model=UploadResult, status_code=201)
async def upload_video(
    song_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload a music video (MV) for the song."""
    song = await _get_song(song_id, session)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in storage.VIDEO_EXTS:
        raise HTTPException(
            415, f"unsupported video extension {ext!r}; use one of "
            f"{sorted(storage.VIDEO_EXTS)}"
        )
    dest = storage.song_dir(song_id)
    path, sha = await storage.save_upload(dest, "video", file.filename or "", file)
    song.video_path = str(path)
    await session.commit()
    return UploadResult(song_id=song_id, kind="video", path_name=path.name, sha256=sha)


@router.post("/{song_id}/cover", response_model=UploadResult, status_code=201)
async def upload_cover(
    song_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload cover artwork for the song (library art / playback background).

    A user-uploaded cover takes precedence over any art embedded in the audio
    tags, which is otherwise extracted automatically during ingest.
    """
    song = await _get_song(song_id, session)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in storage.IMAGE_EXTS:
        raise HTTPException(
            415, f"unsupported image extension {ext!r}; use one of "
            f"{sorted(storage.IMAGE_EXTS)}"
        )
    dest = storage.song_dir(song_id)
    path, sha = await storage.save_upload(dest, "cover", file.filename or "", file)
    song.cover_path = str(path)
    await session.commit()
    return UploadResult(song_id=song_id, kind="cover", path_name=path.name, sha256=sha)


# ------------------------------------------------------------------ media serving

@router.get("/{song_id}/audio")
async def stream_audio(
    song_id: str,
    track: Literal["original", "instrumental"] = "instrumental",
    session: AsyncSession = Depends(get_session),
):
    """Range-request capable audio streaming for the player."""
    song = await _get_song(song_id, session)
    path = song.original_path if track == "original" else song.instrumental_path
    if not path or not Path(path).exists():
        raise HTTPException(404, f"no {track} audio for this song")
    return FileResponse(path)


@router.get("/{song_id}/video")
async def stream_video(song_id: str, session: AsyncSession = Depends(get_session)):
    song = await _get_song(song_id, session)
    if not song.video_path or not Path(song.video_path).exists():
        raise HTTPException(404, "no video for this song")
    return FileResponse(song.video_path)


@router.get("/{song_id}/cover")
async def get_cover(song_id: str, session: AsyncSession = Depends(get_session)):
    """Serve the song's cover artwork (uploaded or extracted from tags)."""
    song = await _get_song(song_id, session)
    if not song.cover_path or not Path(song.cover_path).exists():
        raise HTTPException(404, "no cover art for this song")
    return FileResponse(song.cover_path)


@router.get("/{song_id}/subtitle")
async def get_subtitle(
    song_id: str,
    format: Literal["json", "lrc", "elrc", "srt", "ass"] = "json",
    session: AsyncSession = Depends(get_session),
):
    """Timed lyrics. `json` is the canonical format for the karaoke UI
    (word/char tokens + furigana ruby); the rest are standard exports."""
    song = await _get_song(song_id, session)
    if not song.subtitle_json_path or not Path(song.subtitle_json_path).exists():
        raise HTTPException(404, "subtitle not generated yet")
    raw = Path(song.subtitle_json_path).read_text(encoding="utf-8")
    if format == "json":
        return Response(raw, media_type="application/json")
    doc = SubtitleDoc.load_json(raw)
    return PlainTextResponse(
        exporters.EXPORTERS[format](doc), media_type=_SUBTITLE_MEDIA_TYPES[format]
    )


@router.patch("/{song_id}/subtitle/offset", response_model=SubtitleOffset)
async def set_subtitle_offset(
    song_id: str,
    body: SubtitleOffset,
    session: AsyncSession = Depends(get_session),
):
    """Shift lyric timing globally (player sync adjustment).

    Persists offset_ms into subtitle.json and re-renders the LRC/ASS/SRT
    exports so every format stays consistent. Positive values make subtitles
    appear later relative to the audio.
    """
    song = await _get_song(song_id, session)
    if not song.subtitle_json_path or not Path(song.subtitle_json_path).exists():
        raise HTTPException(404, "subtitle not generated yet")
    path = Path(song.subtitle_json_path)
    doc = SubtitleDoc.load_json(path.read_text(encoding="utf-8"))
    doc.offset_ms = body.offset_ms
    # The DB column is the durable source of truth: alignment re-applies it
    # whenever subtitle.json is regenerated.
    song.subtitle_offset_ms = body.offset_ms
    storage.atomic_write_text(path, doc.dump_json())
    render.write_exports(song, doc)
    await session.commit()
    return SubtitleOffset(offset_ms=doc.offset_ms)


# ------------------------------------------------------------------ processing

@router.post("/{song_id}/separate", response_model=MessageOut, status_code=202)
async def generate_instrumental(
    song_id: str,
    force: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Manually trigger vocal removal on the original track.

    Generates instrumental + vocal stem, then re-runs alignment against the
    cleaner vocals. Refuses to overwrite a user-uploaded instrumental unless
    force=true.
    """
    song = await _get_song(song_id, session)
    if not song.original_path or not Path(song.original_path).exists():
        raise HTTPException(409, "upload an original audio file first")
    if song.instrumental_source == "uploaded" and not force:
        raise HTTPException(
            409,
            "an uploaded instrumental already exists; pass ?force=true to "
            "replace it with a generated one",
        )
    active = await session.scalar(
        select(func.count()).select_from(Job).where(
            Job.song_id == song_id,
            Job.stage == Stage.separate.value,
            Job.state.in_(["queued", "running"]),
        )
    )
    if active:
        raise HTTPException(409, "separation already in progress")

    stages = [Stage.separate]
    if song.lyrics_path:
        stages += REALIGN_STAGES
    jobs = await enqueue_stages(session, song_id, stages)
    await session.commit()
    return MessageOut(
        detail="separation queued", enqueued_stages=[j.stage for j in jobs]
    )


@router.post("/{song_id}/reprocess", response_model=MessageOut, status_code=202)
async def reprocess(
    song_id: str,
    from_stage: Literal["ingest", "lyrics", "align", "annotate", "render"] = Query(
        "align", alias="from"
    ),
    session: AsyncSession = Depends(get_session),
):
    """Re-run the automatic pipeline from a given stage onward."""
    song = await _get_song(song_id, session)
    if not song.original_path:
        raise HTTPException(409, "upload an original audio file first")
    chain = [s for s in AUTO_STAGES]
    idx = chain.index(Stage(from_stage))
    jobs = await enqueue_stages(session, song_id, chain[idx:])
    await session.commit()
    return MessageOut(detail="reprocess queued", enqueued_stages=[j.stage for j in jobs])
