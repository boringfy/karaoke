"""Extract embedded cover artwork from audio files (mutagen).

Handles the three common containers: ID3 (mp3) APIC frames, FLAC/Ogg
`.pictures`, and MP4/M4A `covr` atoms. Returns raw image bytes + a file
extension, or None when no artwork is embedded.
"""

from __future__ import annotations

from pathlib import Path

_MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _ext_for_mime(mime: str | None) -> str:
    return _MIME_EXT.get((mime or "").lower(), ".jpg")


def extract_embedded_cover(path: Path) -> tuple[bytes, str] | None:
    import mutagen

    try:
        f = mutagen.File(path)
    except Exception:  # noqa: BLE001 - corrupt/odd files shouldn't fail ingest
        return None
    if f is None:
        return None

    # FLAC / OggOpus / OggVorbis expose a list of Picture objects.
    pictures = getattr(f, "pictures", None)
    if pictures:
        pic = pictures[0]
        return bytes(pic.data), _ext_for_mime(getattr(pic, "mime", None))

    tags = getattr(f, "tags", None)
    if tags is None:
        return None

    # ID3 (mp3): one or more APIC:* frames.
    for key in list(tags.keys()):
        if key.startswith("APIC"):
            apic = tags[key]
            return bytes(apic.data), _ext_for_mime(getattr(apic, "mime", None))

    # MP4 / M4A: covr atom holds MP4Cover bytes with an imageformat flag.
    if "covr" in tags:
        cover = tags["covr"][0]
        # MP4Cover.FORMAT_PNG == 14, FORMAT_JPEG == 13.
        ext = ".png" if getattr(cover, "imageformat", 13) == 14 else ".jpg"
        return bytes(cover), ext

    return None
