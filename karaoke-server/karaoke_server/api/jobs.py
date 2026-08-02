from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Job, Song
from ..db.session import get_session, session_factory
from .schemas import JobOut

router = APIRouter(tags=["jobs"])

TERMINAL_SONG_STATUSES = {"ready", "needs_review", "failed", "pending"}


@router.get("/songs/{song_id}/jobs", response_model=list[JobOut])
async def list_jobs(song_id: str, session: AsyncSession = Depends(get_session)):
    if await session.get(Song, song_id) is None:
        raise HTTPException(404, "song not found")
    rows = (
        await session.execute(
            select(Job).where(Job.song_id == song_id).order_by(Job.order_index)
        )
    ).scalars().all()
    return [JobOut.model_validate(r) for r in rows]


@router.get("/songs/{song_id}/events")
async def job_events(song_id: str, request: Request):
    """Server-Sent Events: pushes song status + job states ~1/s while the
    pipeline is active; closes after the song reaches a terminal state."""
    sessions = session_factory()
    async with sessions() as session:
        if await session.get(Song, song_id) is None:
            raise HTTPException(404, "song not found")

    async def gen():
        last_payload = None
        idle_terminal_ticks = 0
        while not await request.is_disconnected():
            async with sessions() as session:
                song = await session.get(Song, song_id)
                if song is None:
                    break
                jobs = (
                    await session.execute(
                        select(Job)
                        .where(Job.song_id == song_id)
                        .order_by(Job.order_index)
                    )
                ).scalars().all()
                payload = json.dumps(
                    {
                        "status": song.status,
                        "alignment_confidence": song.alignment_confidence,
                        "jobs": [
                            {
                                "stage": j.stage,
                                "state": j.state,
                                "error": j.error,
                            }
                            for j in jobs
                        ],
                    },
                    ensure_ascii=False,
                )
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            if song.status in TERMINAL_SONG_STATUSES:
                idle_terminal_ticks += 1
                if idle_terminal_ticks >= 3:
                    yield "event: end\ndata: {}\n\n"
                    break
            else:
                idle_terminal_ticks = 0
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
