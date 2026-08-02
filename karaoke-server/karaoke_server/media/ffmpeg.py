from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FfmpegError(RuntimeError):
    pass


def probe_duration(path: Path) -> float | None:
    """Return media duration in seconds via ffprobe, or None if unreadable."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        dur = json.loads(out).get("format", {}).get("duration")
        return float(dur) if dur is not None else None
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None


def encode_opus(src: Path, dest: Path, bitrate: str = "128k") -> None:
    """Encode any audio file to Opus for playback."""
    tmp = dest.with_suffix(dest.suffix + ".tmp.ogg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn",
             "-c:a", "libopus", "-b:a", bitrate, str(tmp)],
            capture_output=True, text=True, timeout=600, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise FfmpegError(e.stderr.strip()[-500:]) from e
    tmp.replace(dest)


def to_wav_mono16k(src: Path, dest: Path) -> None:
    """Decode to 16 kHz mono WAV (what Whisper/VAD consume)."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
            capture_output=True, text=True, timeout=600, check=True,
        )
    except subprocess.CalledProcessError as e:
        raise FfmpegError(e.stderr.strip()[-500:]) from e
