"""Pipeline stage implementations.

Each stage is `async def stage(ctx) -> str | None`, returning an optional
human-readable note ("skipped" to mark the job skipped instead of done).
Heavy work runs in threads via asyncio.to_thread. Raise StageError for
expected, user-fixable failures.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import Settings
from ..db.models import LyricsCandidate, Song
from ..lyrics.language import detect_language
from ..lyrics.lrc import parse_lrc, plain_lines
from ..lyrics.providers import fetch_candidates
from ..media import ffmpeg, storage
from ..media.cover import extract_embedded_cover
from ..subtitles import render
from ..subtitles.furigana import ruby_segments
from ..subtitles.schema import Line, SubtitleDoc, Token

log = logging.getLogger(__name__)


class StageError(RuntimeError):
    """Expected failure with a message meant for the user."""


@dataclass
class StageContext:
    song_id: str
    sessions: async_sessionmaker[AsyncSession]
    settings: Settings

    async def get_song(self, session: AsyncSession) -> Song:
        song = await session.get(Song, self.song_id)
        if song is None:
            raise StageError("song no longer exists")
        return song


# --------------------------------------------------------------------------- ingest

async def stage_ingest(ctx: StageContext) -> str | None:
    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        if not song.original_path:
            raise StageError("no original audio uploaded")
        path = Path(song.original_path)
        if not path.exists():
            raise StageError(f"original file missing on disk: {path}")

        duration = await asyncio.to_thread(ffmpeg.probe_duration, path)
        if duration is None:
            raise StageError("ffprobe could not read the uploaded audio")
        song.duration_sec = duration

        def read_tags() -> dict[str, str]:
            import mutagen

            f = mutagen.File(path, easy=True)
            if not f:
                return {}
            get = lambda k: (f.tags.get(k) or [None])[0] if f.tags else None  # noqa: E731
            return {
                "title": get("title"),
                "artist": get("artist"),
                "album": get("album"),
            }

        tags = await asyncio.to_thread(read_tags)
        song.title = song.title or tags.get("title") or path.stem
        song.artist = song.artist or tags.get("artist")
        song.album = song.album or tags.get("album")

        # Extract embedded cover art unless the user already provided one.
        if not (song.cover_path and Path(song.cover_path).exists()):
            art = await asyncio.to_thread(extract_embedded_cover, path)
            if art:
                data, ext = art
                cover = storage.song_dir(song.id) / f"cover{ext}"
                cover.write_bytes(data)
                song.cover_path = str(cover)
        await session.commit()
    return None


# --------------------------------------------------------------------------- lyrics

async def stage_lyrics(ctx: StageContext) -> str | None:
    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        if song.embedded_lyrics:
            return "skipped"
        if not song.title:
            raise StageError("song has no title; set one, then refetch lyrics")
        expected = song.language if song.language != "unknown" else None
        candidates = await fetch_candidates(
            song.title, song.artist, song.duration_sec, expected
        )
        if not candidates:
            raise StageError(
                "no lyrics found on any provider; upload lyrics manually via "
                "PUT /api/v1/songs/{id}/lyrics"
            )

        await session.execute(
            delete(LyricsCandidate).where(
                LyricsCandidate.song_id == song.id, LyricsCandidate.selected.is_(False)
            )
        )
        already_selected = await session.scalar(
            select(LyricsCandidate).where(
                LyricsCandidate.song_id == song.id, LyricsCandidate.selected.is_(True)
            )
        )
        best_row = None
        for i, c in enumerate(candidates):
            row = LyricsCandidate(
                song_id=song.id,
                provider=c.provider,
                provider_track_id=c.provider_track_id,
                title=c.title,
                artist=c.artist,
                duration_sec=c.duration_sec,
                is_synced=c.is_synced,
                raw_text=c.plain,
                raw_lrc=c.lrc,
                score=c.score,
                selected=False,
            )
            session.add(row)
            if i == 0:
                best_row = row

        # Auto-select the best hit unless the user already picked one.
        if already_selected is None and best_row is not None:
            best_row.selected = True
            _write_selected_lyrics(song, best_row)
        await session.commit()
    return None


def _write_selected_lyrics(song: Song, cand: LyricsCandidate) -> None:
    """Persist the chosen lyrics as lyrics.raw.json and update song fields."""
    d = storage.song_dir(song.id)
    text = cand.raw_text or ""
    if not text and cand.raw_lrc:
        text = "\n".join(line.text for line in parse_lrc(cand.raw_lrc))
    payload = {
        "provider": cand.provider,
        "provider_track_id": cand.provider_track_id,
        "text": text,
        "lrc": cand.raw_lrc,
    }
    path = d / "lyrics.raw.json"
    storage.atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
    song.lyrics_path = str(path)
    if song.language == "unknown":
        song.language = detect_language(text or (cand.raw_lrc or ""))


def load_lyrics(song: Song) -> tuple[list[str], list[float | None]]:
    """Return (lines, per-line LRC anchor times or None).

    Japanese lyrics are normalized to shinjitai glyphs here: Chinese lyric
    sites deliver Japanese text with Simplified codepoints (热 for 熱), which
    break furigana and weaken alignment."""
    if not song.lyrics_path or not Path(song.lyrics_path).exists():
        raise StageError("no lyrics selected; fetch or upload lyrics first")
    payload = json.loads(Path(song.lyrics_path).read_text(encoding="utf-8"))

    def _norm(text: str) -> str:
        if song.language == "ja":
            from ..lyrics.script import to_japanese_kanji

            return to_japanese_kanji(text)
        return text

    lrc_raw = payload.get("lrc")
    if lrc_raw:
        parsed = parse_lrc(lrc_raw)
        if parsed:
            return [_norm(line.text) for line in parsed], [line.time for line in parsed]
    lines = plain_lines(payload.get("text") or "")
    if not lines:
        raise StageError("selected lyrics are empty")
    return [_norm(ln) for ln in lines], [None] * len(lines)


# --------------------------------------------------------------------------- separate

async def stage_separate(ctx: StageContext) -> str | None:
    from ..media.separate import separate_track

    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        if not song.original_path:
            raise StageError("no original audio uploaded")
        # The user supplied their own instrumental — don't generate one over it.
        if song.instrumental_source == "uploaded" and (
            song.instrumental_path and Path(song.instrumental_path).exists()
        ):
            return "skipped"
        src = Path(song.original_path)
    out_dir = storage.song_dir(ctx.song_id)

    try:
        vocals_wav, instrumental_wav = await asyncio.to_thread(separate_track, src, out_dir)
        settings = ctx.settings
        if settings.instrumental_bitrate:
            opus = out_dir / "instrumental.opus"
            await asyncio.to_thread(
                ffmpeg.encode_opus, instrumental_wav, opus, settings.instrumental_bitrate
            )
            instrumental_final = opus
            instrumental_wav.unlink(missing_ok=True)
        else:
            instrumental_final = instrumental_wav
    except Exception:  # noqa: BLE001
        # Best-effort: since SEPARATE runs before LYRICS/ALIGN, a failure here
        # must not block the subtitle pipeline. Degrade to "skipped"; the user
        # can retry via POST /separate or upload their own instrumental.
        log.exception("separation failed for %s; continuing without an instrumental", ctx.song_id)
        return "skipped"

    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        song.instrumental_path = str(instrumental_final)
        song.instrumental_source = "generated"
        song.vocals_path = str(vocals_wav)
        await session.commit()
    return None


# --------------------------------------------------------------------------- align

async def stage_align(ctx: StageContext) -> str | None:
    from ..align.whisper_align import align_lyrics

    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        if song.embedded_lyrics:
            return "skipped"
        lines, anchors = load_lyrics(song)
        # Prefer the clean vocal stem; fall back to the original mix.
        audio = None
        if song.vocals_path and Path(song.vocals_path).exists():
            audio = Path(song.vocals_path)
        elif song.original_path and Path(song.original_path).exists():
            audio = Path(song.original_path)
        if audio is None:
            raise StageError("no audio available to align against")
        language = song.language if song.language != "unknown" else None
        title, artist, song_lang = song.title, song.artist, song.language
        saved_offset_ms = song.subtitle_offset_ms

    aligned, confidence = await asyncio.to_thread(
        align_lyrics, audio, lines, language, anchors
    )

    doc = SubtitleDoc(
        lang=song_lang,
        title=title,
        artist=artist,
        # Re-apply the user's sync adjustment so re-alignment never loses it.
        offset_ms=saved_offset_ms,
        lines=[
            Line(
                id=f"L{i:04d}",
                start=round(ln.start, 3),
                end=round(ln.end, 3),
                text=ln.text,
                score=ln.score,
                alignment=ln.alignment,  # type: ignore[arg-type]
                tokens=[
                    Token(
                        text=t.text,
                        start=round(t.start, 3),
                        end=round(t.end, 3),
                        p=round(t.p, 4) if t.p is not None else None,
                    )
                    for t in ln.tokens
                ],
            )
            for i, ln in enumerate(aligned)
        ],
    )
    out = storage.song_dir(ctx.song_id) / "subtitle.json"
    storage.atomic_write_text(out, doc.dump_json())

    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        song.subtitle_json_path = str(out)
        song.alignment_confidence = confidence
        # The vocal stem has served its purpose unless the user wants it.
        if not ctx.settings.keep_vocal_stem and song.vocals_path:
            Path(song.vocals_path).unlink(missing_ok=True)
            song.vocals_path = None
        await session.commit()
    return None


# --------------------------------------------------------------------------- annotate

def _explode_to_chars(tokens: list[Token]) -> list[Token]:
    """Flatten tokens to one-per-character, splitting each token's duration
    evenly. Makes annotation idempotent: re-running on already-merged tokens
    (e.g. reprocess?from=annotate) starts from a clean per-character pool."""
    out: list[Token] = []
    for tok in tokens:
        chars = [c for c in tok.text if not c.isspace()]
        if len(chars) <= 1:
            out.append(tok.model_copy())
            continue
        dur = max(tok.end - tok.start, 0.0) / len(chars)
        for i, ch in enumerate(chars):
            out.append(
                Token(
                    text=ch,
                    start=round(tok.start + i * dur, 3),
                    end=round(tok.start + (i + 1) * dur, 3),
                    p=tok.p,
                )
            )
    return out


def _apply_furigana(doc: SubtitleDoc) -> None:
    """Regroup each line's per-character tokens into ruby segments.

    Alignment produces one token per character for Japanese; furigana
    segments cover one or more characters. Each segment consumes as many
    tokens as it has non-space characters and inherits their time range.
    Manual ruby edits (ruby_source == "manual") are preserved by text match.
    """
    for line in doc.lines:
        manual = {
            (t.text, t.ruby)
            for t in line.tokens
            if t.ruby_source == "manual" and t.ruby is not None
        }
        segs = ruby_segments(line.text)
        new_tokens: list[Token] = []
        pool = _explode_to_chars(line.tokens)
        ok = True
        for seg in segs:
            need = len([c for c in seg.text if not c.isspace()])
            if need == 0:
                continue
            if need > len(pool):
                ok = False
                break
            used, pool = pool[:need], pool[need:]
            ps = [t.p for t in used if t.p is not None]
            ruby = seg.ruby
            source: str | None = "auto" if ruby else None
            for m_text, m_ruby in manual:
                if m_text == seg.text:
                    ruby, source = m_ruby, "manual"
            new_tokens.append(
                Token(
                    text=seg.text,
                    ruby=ruby,
                    ruby_source=source,  # type: ignore[arg-type]
                    start=used[0].start,
                    end=used[-1].end,
                    p=round(sum(ps) / len(ps), 4) if ps else None,
                )
            )
        if ok and new_tokens:
            line.tokens = new_tokens


async def stage_annotate(ctx: StageContext) -> str | None:
    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        if song.embedded_lyrics:
            return "skipped"
        if song.language != "ja":
            return "skipped"
        if not song.subtitle_json_path:
            raise StageError("no subtitle.json; run align first")
        path = Path(song.subtitle_json_path)

    doc = SubtitleDoc.load_json(path.read_text(encoding="utf-8"))
    await asyncio.to_thread(_apply_furigana, doc)
    storage.atomic_write_text(path, doc.dump_json())
    return None


# --------------------------------------------------------------------------- render

async def stage_render(ctx: StageContext) -> str | None:
    async with ctx.sessions() as session:
        song = await ctx.get_song(session)
        if song.embedded_lyrics:
            return "skipped"
        if not song.subtitle_json_path or not Path(song.subtitle_json_path).exists():
            raise StageError("no subtitle.json to render")
        doc = SubtitleDoc.load_json(
            Path(song.subtitle_json_path).read_text(encoding="utf-8")
        )
        render.write_exports(song, doc)
        await session.commit()
    return None


STAGE_FUNCS = {
    "ingest": stage_ingest,
    "lyrics": stage_lyrics,
    "separate": stage_separate,
    "align": stage_align,
    "annotate": stage_annotate,
    "render": stage_render,
}
