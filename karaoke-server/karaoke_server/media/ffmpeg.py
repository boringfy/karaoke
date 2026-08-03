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


# Audio codecs that stream-copy cleanly into a simple container (lossless, fast).
_AUDIO_CODEC_EXT = {
    "flac": ".flac", "aac": ".m4a", "alac": ".m4a", "opus": ".opus",
    "vorbis": ".ogg", "mp3": ".mp3", "ac3": ".ac3", "pcm_s16le": ".wav",
}


def probe_video(path: Path) -> tuple[str, str] | None:
    """(codec_name, pix_fmt) of the first video stream, or None if unreadable
    or there is no video stream."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,pix_fmt", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        streams = json.loads(out).get("streams", [])
        if not streams:
            return None
        return streams[0].get("codec_name", ""), streams[0].get("pix_fmt", "")
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None


def transcode_video_h264(src: Path, dest: Path) -> None:
    """Re-encode a video to 8-bit H.264 MP4 at native resolution.

    8-bit H.264 is the one format every playback surface hardware-decodes
    (Chromium on the desktop, MediaCodec on tablets); HEVC-10bit and AV1
    sources fall back to software decoding and stutter. Audio is stripped —
    playback audio always comes from the original/instrumental tracks. Runs
    niced so it doesn't starve the alignment/separation stages.
    """
    tmp = dest.with_suffix(dest.suffix + ".part.mp4")
    try:
        subprocess.run(
            ["nice", "-n", "10", "ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-map", "0:v:0", "-vf", "format=yuv420p", "-c:v", "libx264",
             "-profile:v", "high", "-crf", "20", "-preset", "fast", "-an",
             "-movflags", "+faststart", str(tmp)],
            capture_output=True, text=True, timeout=3600, check=True,
        )
    except subprocess.SubprocessError as e:
        tmp.unlink(missing_ok=True)
        stderr = getattr(e, "stderr", "") or str(e)
        raise FfmpegError(stderr.strip()[-500:]) from e
    tmp.replace(dest)


# Audio codecs every playback surface decodes (Chromium, Android MediaCodec).
# Anything else (alac, wma, big-endian aiff pcm...) gets a lossless FLAC copy.
PLAYABLE_AUDIO_CODECS = {
    "flac", "opus", "vorbis", "mp3", "aac",
    "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le", "pcm_u8",
}


def transcode_audio_flac(src: Path, dest: Path) -> None:
    """Re-encode audio losslessly to FLAC for playback compatibility."""
    tmp = dest.with_suffix(dest.suffix + ".part.flac")
    try:
        subprocess.run(
            ["nice", "-n", "10", "ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-vn", "-c:a", "flac", str(tmp)],
            capture_output=True, text=True, timeout=1800, check=True,
        )
    except subprocess.SubprocessError as e:
        tmp.unlink(missing_ok=True)
        stderr = getattr(e, "stderr", "") or str(e)
        raise FfmpegError(stderr.strip()[-500:]) from e
    tmp.replace(dest)


def probe_audio_codec(path: Path) -> str | None:
    """Codec name of the first audio stream, or None if there is no audio."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True,
        ).stdout
        streams = json.loads(out).get("streams", [])
        return streams[0].get("codec_name") if streams else None
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None


def extract_audio(src: Path, dest_dir: Path, stem: str = "original") -> Path:
    """Extract the first audio stream from a video into <dest_dir>/<stem>.<ext>.

    Stream-copies when the codec maps to a simple container (fast, lossless);
    otherwise re-encodes to Opus. Returns the written path. Raises FfmpegError
    if the file has no audio stream.
    """
    codec = probe_audio_codec(src)
    if codec is None:
        raise FfmpegError(f"no audio stream found in {src.name}")
    ext = _AUDIO_CODEC_EXT.get(codec)
    if ext:
        dest = dest_dir / f"{stem}{ext}"
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(src),
                 "-map", "0:a:0", "-vn", "-c:a", "copy", str(tmp)],
                capture_output=True, text=True, timeout=600, check=True,
            )
            tmp.replace(dest)
            return dest
        except subprocess.CalledProcessError:
            tmp.unlink(missing_ok=True)  # fall through to a re-encode
    dest = dest_dir / f"{stem}.opus"
    encode_opus(src, dest)
    return dest


COVER_MAX_SIDE = 1024


def probe_image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of an image, or None if unreadable."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout
        streams = json.loads(out).get("streams", [])
        if not streams:
            return None
        w, h = streams[0].get("width"), streams[0].get("height")
        return (int(w), int(h)) if w and h else None
    except (subprocess.SubprocessError, ValueError, json.JSONDecodeError):
        return None


def scale_cover(src: Path, dest: Path) -> None:
    """Normalize uploaded cover art: cap the long side at COVER_MAX_SIDE and
    re-encode as JPEG. Uploads are often camera photos or full-res scans of
    several MB; covers render at ~48px in lists and as a blurred background,
    so 1024px is plenty and keeps the library snappy."""
    # Fit inside a square box, keeping aspect ratio. Callers only invoke this
    # for images larger than the box, so no upscaling can occur.
    scale = f"scale={COVER_MAX_SIDE}:{COVER_MAX_SIDE}:force_original_aspect_ratio=decrease"
    tmp = dest.with_suffix(dest.suffix + ".part.jpg")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-frames:v", "1", "-vf", scale, "-qscale:v", "3", str(tmp)],
            capture_output=True, text=True, timeout=120, check=True,
        )
    except subprocess.SubprocessError as e:
        tmp.unlink(missing_ok=True)
        stderr = getattr(e, "stderr", "") or str(e)
        raise FfmpegError(stderr.strip()[-500:]) from e
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
