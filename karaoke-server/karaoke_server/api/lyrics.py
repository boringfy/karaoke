from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import REALIGN_STAGES, LyricsCandidate, Song, Stage
from ..db.session import get_session
from ..lyrics.language import detect_language
from ..lyrics.lrc import parse_lrc
from ..media import storage
from ..pipeline.stages import _write_selected_lyrics
from ..pipeline.worker import enqueue_stages
from .schemas import CandidateOut, LyricsPut, LyricsSelect, MessageOut

router = APIRouter(prefix="/songs/{song_id}/lyrics", tags=["lyrics"])


async def _get_song(song_id: str, session: AsyncSession) -> Song:
    song = await session.get(Song, song_id)
    if song is None:
        raise HTTPException(404, "song not found")
    return song


@router.get("")
async def get_lyrics(song_id: str, session: AsyncSession = Depends(get_session)):
    """The currently selected raw lyrics (text + LRC if available)."""
    song = await _get_song(song_id, session)
    if not song.lyrics_path or not Path(song.lyrics_path).exists():
        raise HTTPException(404, "no lyrics selected yet")
    return Response(
        Path(song.lyrics_path).read_text(encoding="utf-8"),
        media_type="application/json",
    )


@router.get("/candidates", response_model=list[CandidateOut])
async def list_candidates(song_id: str, session: AsyncSession = Depends(get_session)):
    await _get_song(song_id, session)
    rows = (
        await session.execute(
            select(LyricsCandidate)
            .where(LyricsCandidate.song_id == song_id)
            .order_by(LyricsCandidate.score.desc())
        )
    ).scalars().all()
    return [CandidateOut.model_validate(r) for r in rows]


@router.post("/select", response_model=MessageOut, status_code=202)
async def select_candidate(
    song_id: str, body: LyricsSelect, session: AsyncSession = Depends(get_session)
):
    """Pick one of the fetched candidates; re-aligns the song against it."""
    song = await _get_song(song_id, session)
    cand = await session.get(LyricsCandidate, body.candidate_id)
    if cand is None or cand.song_id != song_id:
        raise HTTPException(404, "candidate not found for this song")
    for row in song.lyrics_candidates:
        row.selected = row.id == cand.id
    _write_selected_lyrics(song, cand)
    jobs = await enqueue_stages(session, song_id, list(REALIGN_STAGES))
    await session.commit()
    return MessageOut(
        detail="candidate selected", enqueued_stages=[j.stage for j in jobs]
    )


@router.put("", response_model=MessageOut, status_code=202)
async def put_lyrics(
    song_id: str, body: LyricsPut, session: AsyncSession = Depends(get_session)
):
    """Manual lyrics override (plain text and/or LRC); re-aligns the song."""
    if not body.text and not body.lrc:
        raise HTTPException(422, "provide `text`, `lrc`, or both")
    song = await _get_song(song_id, session)
    jobs = await _save_manual_lyrics(session, song, text=body.text, lrc=body.lrc)
    await session.commit()
    return MessageOut(detail="lyrics saved", enqueued_stages=[j.stage for j in jobs])


async def _save_manual_lyrics(
    session: AsyncSession, song: Song, *, text: str | None, lrc: str | None
) -> list:
    """Persist manual lyrics (text and/or LRC), deselect candidates, and
    enqueue re-alignment. Shared by the JSON PUT and the file upload."""
    if not text and lrc:
        text = "\n".join(line.text for line in parse_lrc(lrc))
    payload = {"provider": "manual", "text": text, "lrc": lrc}
    path = storage.song_dir(song.id) / "lyrics.raw.json"
    storage.atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
    song.lyrics_path = str(path)
    if song.language == "unknown":
        song.language = detect_language(text or "")
    for row in song.lyrics_candidates:
        row.selected = False
    return await enqueue_stages(session, song.id, list(REALIGN_STAGES))


@router.post("/upload", response_model=MessageOut, status_code=202)
async def upload_lyrics_file(
    song_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
):
    """Upload a lyrics file and use it for this song; re-aligns afterward.

    Format is chosen by extension:
      .lrc          synced lyrics — timestamps become alignment anchors
      .txt / (none) plain lyrics, one line per lyric line

    The file is decoded as UTF-8 (BOM tolerated).
    """
    song = await _get_song(song_id, session)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ("", ".lrc", ".txt", ".text"):
        raise HTTPException(
            415, f"unsupported lyrics extension {ext!r}; use .lrc or .txt"
        )
    raw = await file.read()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "lyrics file must be UTF-8 text") from None
    if not content.strip():
        raise HTTPException(422, "lyrics file is empty")

    # Treat as LRC when the extension says so or timestamps are present.
    is_lrc = ext == ".lrc" or bool(parse_lrc(content))
    if is_lrc and parse_lrc(content):
        jobs = await _save_manual_lyrics(session, song, text=None, lrc=content)
    else:
        jobs = await _save_manual_lyrics(session, song, text=content, lrc=None)
    await session.commit()
    return MessageOut(
        detail=f"lyrics uploaded from {file.filename or 'file'}",
        enqueued_stages=[j.stage for j in jobs],
    )


@router.post("/refetch", response_model=MessageOut, status_code=202)
async def refetch_lyrics(song_id: str, session: AsyncSession = Depends(get_session)):
    """Re-run the lyric search (then re-align if a match is found)."""
    song = await _get_song(song_id, session)
    if not song.original_path:
        raise HTTPException(409, "upload an original audio file first")
    jobs = await enqueue_stages(
        session, song_id, [Stage.lyrics, *REALIGN_STAGES]
    )
    await session.commit()
    return MessageOut(detail="refetch queued", enqueued_stages=[j.stage for j in jobs])
