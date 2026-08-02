"""Canonical timed-subtitle document.

`subtitle.json` is the source of truth for a song's karaoke track. Every other
format (LRC, enhanced LRC, ASS, SRT) is a lossy export rendered from it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


class Token(BaseModel):
    """One highlightable unit: a word (EN) or a character/small run (ZH/JA)."""

    text: str
    start: float
    end: float
    # Hiragana reading rendered above this token (Japanese kanji only).
    ruby: str | None = None
    ruby_source: Literal["auto", "manual"] | None = None
    # Aligner word probability for this token (0-1), if available.
    p: float | None = None


class Line(BaseModel):
    id: str
    start: float
    end: float
    text: str
    translation: str | None = None
    # Mean aligner confidence for the line.
    score: float | None = None
    # "aligned": timestamps from forced alignment.
    # "interpolated": alignment failed sanity checks; times come from LRC
    #   anchors or neighbor interpolation. UI should flag for review.
    alignment: Literal["aligned", "interpolated"] = "aligned"
    tokens: list[Token] = Field(default_factory=list)


class SubtitleDoc(BaseModel):
    schema_version: int = Field(default=SCHEMA_VERSION, alias="schema")
    lang: str = "unknown"
    title: str | None = None
    artist: str | None = None
    offset_ms: int = 0
    lines: list[Line] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    def dump_json(self) -> str:
        return self.model_dump_json(by_alias=True, indent=2, exclude_none=True)

    @classmethod
    def load_json(cls, raw: str) -> SubtitleDoc:
        return cls.model_validate_json(raw)
