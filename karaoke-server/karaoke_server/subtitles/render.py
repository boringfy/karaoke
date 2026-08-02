"""Write a subtitle doc's export renditions (LRC/ASS/SRT) into the song dir."""

from __future__ import annotations

from ..media import storage
from . import exporters
from .schema import SubtitleDoc


def write_exports(song, doc: SubtitleDoc) -> None:
    """Render all export formats next to subtitle.json and update the song's
    export paths. `song` is a db.models.Song (untyped to avoid an import cycle).
    Caller is responsible for committing the session."""
    d = storage.song_dir(song.id)
    lrc_path = d / "subtitle.lrc"
    ass_path = d / "subtitle.ass"
    storage.atomic_write_text(lrc_path, exporters.to_enhanced_lrc(doc))
    storage.atomic_write_text(ass_path, exporters.to_ass(doc))
    storage.atomic_write_text(d / "subtitle.srt", exporters.to_srt(doc))
    song.subtitle_lrc_path = str(lrc_path)
    song.subtitle_ass_path = str(ass_path)
