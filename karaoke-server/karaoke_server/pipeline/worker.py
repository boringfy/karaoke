"""SQLite-backed job queue.

Two in-process workers share one claim lock:
  heavy  — separate, align (concurrency 1: they monopolize CPU/GPU)
  io     — everything else

Jobs for a song run strictly in enqueue order (order_index); a failed stage
fails the rest of that song's queued chain. On startup, jobs left "running"
by a crash are re-queued; stages are idempotent so re-running is safe.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import get_settings
from ..db.models import HEAVY_STAGES, Job, JobState, Song, SongStatus, Stage, utcnow
from .stages import STAGE_FUNCS, StageContext, StageError

log = logging.getLogger(__name__)

POLL_INTERVAL = 1.0
# How often a running job refreshes heartbeat_at, so a wedged stage is visible
# in the jobs table instead of looking identical to one that just started.
HEARTBEAT_INTERVAL = 30.0


async def enqueue_stages(
    session: AsyncSession, song_id: str, stages: list[Stage]
) -> list[Job]:
    """Append jobs for `stages` to the song's chain, skipping stages that are
    already queued or running.

    Enqueueing is a retry: earlier FAILED jobs are superseded (marked skipped)
    so the claim loop's "a failed earlier stage fails the rest of the chain"
    rule can't instantly kill the fresh jobs. Without this, one failure made a
    song permanently unretryable."""
    await session.execute(
        update(Job)
        .where(Job.song_id == song_id, Job.state == JobState.failed.value)
        .values(state=JobState.skipped.value)
    )
    active = set(
        (
            await session.execute(
                select(Job.stage).where(
                    Job.song_id == song_id,
                    Job.state.in_([JobState.queued.value, JobState.running.value]),
                )
            )
        ).scalars()
    )
    max_idx = (
        await session.scalar(
            select(func.max(Job.order_index)).where(Job.song_id == song_id)
        )
    ) or 0
    jobs = []
    for i, stage in enumerate([s for s in stages if s.value not in active], start=1):
        job = Job(song_id=song_id, stage=stage.value, order_index=max_idx + i)
        session.add(job)
        jobs.append(job)
    song = await session.get(Song, song_id)
    if song and jobs and song.status in (SongStatus.pending.value, SongStatus.ready.value,
                                         SongStatus.needs_review.value, SongStatus.failed.value):
        song.status = SongStatus.processing.value
    return jobs


async def requeue_stale_running(sessions: async_sessionmaker[AsyncSession]) -> None:
    """Crash recovery: anything still 'running' at startup was orphaned."""
    async with sessions() as session:
        await session.execute(
            update(Job)
            .where(Job.state == JobState.running.value)
            .values(state=JobState.queued.value, heartbeat_at=None)
        )
        await session.commit()


class PipelineWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions
        self._claim_lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        await requeue_stale_running(self.sessions)
        heavy = {s.value for s in HEAVY_STAGES}
        io = {s.value for s in Stage} - heavy
        self._tasks = [
            asyncio.create_task(self._loop(heavy), name="worker-heavy"),
            asyncio.create_task(self._loop(io), name="worker-io"),
        ]

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _loop(self, stages: set[str]) -> None:
        while not self._stop.is_set():
            try:
                job_id = await self._claim(stages)
                if job_id is None:
                    await asyncio.sleep(POLL_INTERVAL)
                    continue
                await self._run(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - worker must never die
                log.exception("worker loop error")
                await asyncio.sleep(POLL_INTERVAL)

    async def _claim(self, stages: set[str]) -> str | None:
        async with self._claim_lock:
            async with self.sessions() as session:
                candidates = (
                    await session.execute(
                        select(Job)
                        .where(Job.state == JobState.queued.value, Job.stage.in_(stages))
                        .order_by(Job.created_at, Job.order_index)
                    )
                ).scalars().all()
                for job in candidates:
                    blocking = await session.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(
                            Job.song_id == job.song_id,
                            Job.order_index < job.order_index,
                            Job.state.notin_(
                                [JobState.done.value, JobState.skipped.value,
                                 JobState.failed.value]
                            ),
                        )
                    )
                    if blocking:
                        continue
                    # A failed earlier stage fails the rest of the chain.
                    failed_earlier = await session.scalar(
                        select(func.count())
                        .select_from(Job)
                        .where(
                            Job.song_id == job.song_id,
                            Job.order_index < job.order_index,
                            Job.state == JobState.failed.value,
                        )
                    )
                    if failed_earlier:
                        job.state = JobState.failed.value
                        job.error = "upstream stage failed"
                        job.finished_at = utcnow()
                        # Reflect the dead chain in the song status now — else the
                        # song is stuck showing "processing" forever (the UI polls
                        # status and never sees it flip to failed).
                        await self._update_song_status(session, job.song_id)
                        await session.commit()
                        continue
                    job.state = JobState.running.value
                    job.attempts += 1
                    job.started_at = utcnow()
                    job.heartbeat_at = utcnow()
                    await session.commit()
                    return job.id
        return None

    async def _heartbeat(self, job_id: str) -> None:
        """Refresh heartbeat_at while a job runs.

        Without this, heartbeat_at stays frozen at claim time, so a wedged job
        is indistinguishable from a freshly claimed one and nothing can tell
        that the queue has stopped moving.
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                async with self.sessions() as session:
                    await session.execute(
                        update(Job).where(Job.id == job_id).values(heartbeat_at=utcnow())
                    )
                    await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a failed heartbeat must not kill the job
            log.exception("heartbeat failed for job %s", job_id[:8])

    async def _run(self, job_id: str) -> None:
        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            song_id, stage = job.song_id, job.stage
        log.info("job %s: %s/%s starting", job_id[:8], song_id[:8], stage)

        ctx = StageContext(
            song_id=song_id, sessions=self.sessions, settings=get_settings()
        )
        error: str | None = None
        note: str | None = None
        timeout = get_settings().stage_timeout_sec
        heartbeat = asyncio.create_task(self._heartbeat(job_id))
        try:
            note = await asyncio.wait_for(STAGE_FUNCS[stage](ctx), timeout)
        except StageError as e:
            error = str(e)
        except TimeoutError:
            # The stage is stuck. Free the worker so the rest of the queue can
            # move; the job is marked failed and can be retried via /reprocess.
            log.error("job %s: %s exceeded %ss, abandoning", job_id[:8], stage, timeout)
            error = f"stage timed out after {timeout}s"
        except Exception as e:  # noqa: BLE001
            log.exception("job %s: %s crashed", job_id[:8], stage)
            error = f"{type(e).__name__}: {e}"
        finally:
            heartbeat.cancel()

        async with self.sessions() as session:
            job = await session.get(Job, job_id)
            assert job is not None
            job.finished_at = utcnow()
            job.progress = 1.0
            if error:
                job.state = JobState.failed.value
                job.error = error
            elif note == "skipped":
                job.state = JobState.skipped.value
            else:
                job.state = JobState.done.value
            await self._update_song_status(session, song_id)
            await session.commit()
        log.info("job %s: %s/%s -> %s", job_id[:8], song_id[:8], stage,
                 "failed: " + error if error else (note or "done"))

    async def _update_song_status(self, session: AsyncSession, song_id: str) -> None:
        song = await session.get(Song, song_id)
        if song is None:
            return
        jobs = (
            await session.execute(select(Job).where(Job.song_id == song_id))
        ).scalars().all()
        if any(j.state in (JobState.queued.value, JobState.running.value) for j in jobs):
            song.status = SongStatus.processing.value
            return
        # Did the most recent chain end in a failure?
        latest = max(jobs, key=lambda j: j.order_index, default=None)
        chain_failed = latest is not None and latest.state == JobState.failed.value
        rendered = song.subtitle_json_path is not None
        if chain_failed:
            song.status = SongStatus.failed.value
        elif song.embedded_lyrics:
            # No subtitle is expected — the MV carries the words. Without this
            # the song would sit at "pending" forever for want of a render.
            song.status = SongStatus.ready.value
        elif rendered:
            threshold = get_settings().song_review_threshold
            if song.alignment_confidence is not None and song.alignment_confidence < threshold:
                song.status = SongStatus.needs_review.value
            else:
                song.status = SongStatus.ready.value
        else:
            song.status = SongStatus.pending.value
