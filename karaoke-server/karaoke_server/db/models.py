from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class SongStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    needs_review = "needs_review"
    failed = "failed"


class Stage(enum.StrEnum):
    ingest = "ingest"
    lyrics = "lyrics"
    separate = "separate"
    align = "align"
    annotate = "annotate"
    render = "render"


# Stage dependency graph: a stage may run once all its dependencies are done.
# SEPARATE runs automatically as part of the import chain (before ALIGN, so
# alignment uses the cleaner vocal stem). It skips itself when the user has
# supplied their own instrumental, so no vocals are removed unnecessarily.
STAGE_DEPS: dict[Stage, list[Stage]] = {
    Stage.ingest: [],
    Stage.lyrics: [Stage.ingest],
    Stage.separate: [Stage.ingest],
    Stage.align: [Stage.lyrics, Stage.separate],
    Stage.annotate: [Stage.align],
    Stage.render: [Stage.annotate],
}

# Stages enqueued automatically when an original audio file is uploaded.
# SEPARATE generates the instrumental up front (unless one was uploaded). It
# runs right after INGEST — before LYRICS — so the instrumental is produced even
# if lyrics can't be found, and so ALIGN can use the cleaner vocal stem. It is
# best-effort: a separation failure degrades to "skipped" and never blocks the
# subtitle pipeline.
AUTO_STAGES: list[Stage] = [
    Stage.ingest, Stage.separate, Stage.lyrics, Stage.align, Stage.annotate, Stage.render
]

# Stages re-run after lyrics change or separation completes.
REALIGN_STAGES: list[Stage] = [Stage.align, Stage.annotate, Stage.render]

# Stages that monopolize CPU/GPU run on the "heavy" worker (concurrency 1);
# everything else runs on the "io" worker.
HEAVY_STAGES = {Stage.separate, Stage.align}


class JobState(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"  # e.g. annotate for non-Japanese songs


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str | None] = mapped_column(String(512))
    artist: Mapped[str | None] = mapped_column(String(512))
    album: Mapped[str | None] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(8), default="unknown")  # en|zh|ja|unknown

    duration_sec: Mapped[float | None] = mapped_column(Float)
    original_path: Mapped[str | None] = mapped_column(Text)
    original_format: Mapped[str | None] = mapped_column(String(16))
    instrumental_path: Mapped[str | None] = mapped_column(Text)
    # How the instrumental came to exist: "uploaded" by the user, or
    # "generated" by the SEPARATE stage.
    instrumental_source: Mapped[str | None] = mapped_column(String(16))
    vocals_path: Mapped[str | None] = mapped_column(Text)
    video_path: Mapped[str | None] = mapped_column(Text)
    cover_path: Mapped[str | None] = mapped_column(Text)
    lyrics_path: Mapped[str | None] = mapped_column(Text)
    subtitle_json_path: Mapped[str | None] = mapped_column(Text)
    subtitle_lrc_path: Mapped[str | None] = mapped_column(Text)
    subtitle_ass_path: Mapped[str | None] = mapped_column(Text)
    # User's lyric sync adjustment (positive = subtitles later). Source of
    # truth: re-applied to subtitle.json whenever alignment regenerates it.
    subtitle_offset_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # The MV already burns karaoke lyrics into the picture. Skip the whole
    # lyrics/alignment chain and render no subtitle overlay, so the player does
    # not draw a second set of words on top of the ones in the video.
    embedded_lyrics: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    # Shifts the MV against the audio. Positive runs the video ahead, which
    # pulls lyrics burned into the picture earlier. subtitle_offset_ms cannot
    # do this: it moves our own overlay, not the video's own frames.
    video_offset_ms: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    status: Mapped[str] = mapped_column(String(16), default=SongStatus.pending.value)
    alignment_confidence: Mapped[float | None] = mapped_column(Float)
    source_hash: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    jobs: Mapped[list[Job]] = relationship(
        back_populates="song", cascade="all, delete-orphan", lazy="selectin"
    )
    lyrics_candidates: Mapped[list[LyricsCandidate]] = relationship(
        back_populates="song", cascade="all, delete-orphan", lazy="selectin"
    )


class LyricsCandidate(Base):
    __tablename__ = "lyrics_candidates"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    provider_track_id: Mapped[str | None] = mapped_column(String(128))
    title: Mapped[str | None] = mapped_column(String(512))
    artist: Mapped[str | None] = mapped_column(String(512))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    is_synced: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    raw_lrc: Mapped[str | None] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    song: Mapped[Song] = relationship(back_populates="lyrics_candidates")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    song_id: Mapped[str] = mapped_column(ForeignKey("songs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(16), index=True)
    # Position in the song's job chain; jobs run in ascending order.
    order_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    state: Mapped[str] = mapped_column(String(16), default=JobState.queued.value, index=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    input_hash: Mapped[str | None] = mapped_column(String(64))
    tool_versions: Mapped[dict | None] = mapped_column(JSON)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    song: Mapped[Song] = relationship(back_populates="jobs")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
