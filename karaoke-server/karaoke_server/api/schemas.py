from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SongCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    artist: str | None = Field(default=None, max_length=512)
    album: str | None = Field(default=None, max_length=512)
    language: Literal["en", "zh", "ja", "unknown"] = "unknown"
    # Set when the MV already has karaoke lyrics burned in: the lyrics chain is
    # skipped and the player draws no subtitle overlay.
    embedded_lyrics: bool = False


class SongUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    artist: str | None = None
    album: str | None = None
    language: Literal["en", "zh", "ja", "unknown"] | None = None
    embedded_lyrics: bool | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    stage: str
    state: str
    progress: float
    error: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SongOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str | None
    artist: str | None
    album: str | None
    language: str
    duration_sec: float | None
    status: str
    alignment_confidence: float | None
    instrumental_source: str | None
    subtitle_offset_ms: int = 0
    embedded_lyrics: bool = False
    has_original: bool = False
    has_instrumental: bool = False
    has_video: bool = False
    has_cover: bool = False
    has_lyrics: bool = False
    has_subtitle: bool = False
    created_at: datetime
    updated_at: datetime


class SongList(BaseModel):
    total: int
    items: list[SongOut]


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    provider_track_id: str | None
    title: str | None
    artist: str | None
    duration_sec: float | None
    is_synced: bool
    score: float
    selected: bool


class LyricsSelect(BaseModel):
    candidate_id: str


class LyricsPut(BaseModel):
    """Manual lyrics override: plain text, LRC, or both."""

    text: str | None = None
    lrc: str | None = None


class UploadResult(BaseModel):
    song_id: str
    kind: str
    path_name: str
    sha256: str
    enqueued_stages: list[str] = []


class MessageOut(BaseModel):
    detail: str
    enqueued_stages: list[str] = []


class SubtitleOffset(BaseModel):
    """Global lyric timing shift; positive = subtitles appear later."""

    offset_ms: int = Field(ge=-60_000, le=60_000)
