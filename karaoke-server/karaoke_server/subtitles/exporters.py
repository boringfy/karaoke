"""Lossy exports of the canonical SubtitleDoc: LRC, enhanced LRC, SRT, ASS."""

from __future__ import annotations

from .schema import Line, SubtitleDoc


def _lrc_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    m, s = divmod(seconds, 60)
    return f"{int(m):02d}:{s:05.2f}"


def _srt_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _ass_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    cs = round(seconds * 100)
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _header_tags(doc: SubtitleDoc) -> list[str]:
    tags = []
    if doc.title:
        tags.append(f"[ti:{doc.title}]")
    if doc.artist:
        tags.append(f"[ar:{doc.artist}]")
    if doc.offset_ms:
        tags.append(f"[offset:{doc.offset_ms}]")
    return tags


def to_lrc(doc: SubtitleDoc) -> str:
    """Plain line-level LRC."""
    out = _header_tags(doc)
    for line in doc.lines:
        out.append(f"[{_lrc_ts(line.start)}]{line.text}")
    return "\n".join(out) + "\n"


def to_enhanced_lrc(doc: SubtitleDoc) -> str:
    """LRC with A2-extension word timing: [line]<t>word<t>word...<t_end>.

    Ruby annotations have no LRC representation and are dropped.
    """
    out = _header_tags(doc)
    for line in doc.lines:
        if line.tokens:
            parts = [f"[{_lrc_ts(line.start)}]"]
            for tok in line.tokens:
                parts.append(f"<{_lrc_ts(tok.start)}>{tok.text}")
            parts.append(f"<{_lrc_ts(line.tokens[-1].end)}>")
            out.append("".join(parts))
        else:
            out.append(f"[{_lrc_ts(line.start)}]{line.text}")
    return "\n".join(out) + "\n"


def to_srt(doc: SubtitleDoc) -> str:
    out = []
    for i, line in enumerate(doc.lines, start=1):
        out.append(str(i))
        out.append(f"{_srt_ts(line.start)} --> {_srt_ts(line.end)}")
        out.append(line.text)
        out.append("")
    return "\n".join(out) + "\n"


_ASS_HEADER = """\
[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: K,Arial,72,&H00FFFFFF,&H000AA7F5,&H00222222,&H88000000,0,0,0,0,100,100,0,0,1,3,0,2,60,60,60,1
Style: Furi,Arial,36,&H00FFFFFF,&H000AA7F5,&H00222222,&H88000000,0,0,0,0,100,100,0,0,1,2,0,2,60,60,150,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_karaoke_text(line: Line) -> str:
    """Render a line as {\\k<centisec>} karaoke syllables.

    Gaps between tokens are absorbed into a leading \\k on the next token so the
    sweep stays in sync with the audio.
    """
    if not line.tokens:
        return line.text
    parts = []
    cursor = line.start
    for tok in line.tokens:
        gap_cs = max(0, round((tok.start - cursor) * 100))
        if gap_cs:
            parts.append(f"{{\\k{gap_cs}}}")
        dur_cs = max(1, round((tok.end - tok.start) * 100))
        parts.append(f"{{\\k{dur_cs}}}{tok.text}")
        cursor = tok.end
    return "".join(parts)


def _ass_furigana_text(line: Line) -> str | None:
    """Ruby layer: readings spaced to sit above the main line.

    Uses a second small-font Dialogue line (renders in any ASS player, no
    Aegisub karaoke templater required). Tokens without ruby contribute
    full-width spaces to keep readings roughly positioned over their kanji.
    """
    if not any(tok.ruby for tok in line.tokens):
        return None
    parts = []
    cursor = line.start
    for tok in line.tokens:
        gap_cs = max(0, round((tok.start - cursor) * 100))
        if gap_cs:
            parts.append(f"{{\\k{gap_cs}}}")
        dur_cs = max(1, round((tok.end - tok.start) * 100))
        text = tok.ruby if tok.ruby else "　" * max(1, len(tok.text))
        parts.append(f"{{\\k{dur_cs}}}{text}")
        cursor = tok.end
    return "".join(parts)


def to_ass(doc: SubtitleDoc) -> str:
    out = [_ASS_HEADER.format(title=doc.title or "karaoke")]
    for line in doc.lines:
        start, end = _ass_ts(line.start), _ass_ts(line.end)
        furi = _ass_furigana_text(line)
        if furi:
            out.append(f"Dialogue: 1,{start},{end},Furi,,0,0,0,,{furi}")
        out.append(f"Dialogue: 0,{start},{end},K,,0,0,0,,{_ass_karaoke_text(line)}")
    return "\n".join(out) + "\n"


EXPORTERS = {
    "lrc": to_lrc,
    "elrc": to_enhanced_lrc,
    "srt": to_srt,
    "ass": to_ass,
}
