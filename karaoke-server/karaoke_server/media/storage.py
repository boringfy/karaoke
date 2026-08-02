"""File layout under the data directory + safe write helpers.

songs/<song_id>/
    original.<ext>       uploaded source audio (kept as-is)
    instrumental.<ext>   uploaded instrumental OR generated accompaniment
    vocals.wav           separated vocal stem (kept only while useful)
    video.<ext>          uploaded MV
    lyrics.raw.json      fetched candidates snapshot / selected raw lyrics
    subtitle.json        canonical timed subtitle (source of truth)
    subtitle.lrc / subtitle.ass   rendered exports
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from ..config import get_settings

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff"}
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".ts"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


def song_dir(song_id: str) -> Path:
    d = get_settings().songs_dir / song_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def atomic_write_text(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


async def save_upload(dest_dir: Path, stem: str, filename: str, stream) -> tuple[Path, str]:
    """Stream an UploadFile to <dest_dir>/<stem><ext> atomically.

    Returns (final_path, sha256). Any previous file with the same stem but a
    different extension is removed (re-upload replaces).
    """
    ext = Path(filename or "").suffix.lower() or ".bin"
    final = dest_dir / f"{stem}{ext}"
    sha = hashlib.sha256()
    fd, tmp_name = tempfile.mkstemp(dir=dest_dir, prefix=f".{stem}.", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as tmp:
            while chunk := await stream.read(1024 * 1024):
                sha.update(chunk)
                tmp.write(chunk)
        for old in dest_dir.glob(f"{stem}.*"):
            if old.suffix != ".part" and old != final:
                old.unlink(missing_ok=True)
        os.replace(tmp_name, final)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
    return final, sha.hexdigest()


def delete_song_files(song_id: str) -> None:
    d = get_settings().songs_dir / song_id
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
