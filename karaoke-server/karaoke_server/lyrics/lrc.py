"""Minimal LRC parser: extracts (timestamp_seconds, text) line anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass

_TS = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META = re.compile(r"^\[(ti|ar|al|by|offset|length|re|ve|tool|id):", re.IGNORECASE)


@dataclass
class LrcLine:
    time: float
    text: str


def parse_lrc(raw: str) -> list[LrcLine]:
    lines: list[LrcLine] = []
    offset_ms = 0
    m = re.search(r"^\[offset:([+-]?\d+)\]", raw, re.MULTILINE | re.IGNORECASE)
    if m:
        try:
            offset_ms = int(m.group(1))
        except ValueError:
            offset_ms = 0

    for rawline in raw.splitlines():
        if _META.match(rawline.strip()):
            continue
        stamps = list(_TS.finditer(rawline))
        if not stamps:
            continue
        text = rawline[stamps[-1].end():].strip()
        # Strip A2 word-timing tags if present.
        text = re.sub(r"<\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?>", "", text).strip()
        if not text:
            continue
        for s in stamps:
            mm, ss, frac = s.group(1), s.group(2), s.group(3)
            t = int(mm) * 60 + int(ss)
            if frac:
                t += int(frac) / (10 ** len(frac))
            t -= offset_ms / 1000.0
            lines.append(LrcLine(time=max(0.0, t), text=text))
    lines.sort(key=lambda x: x.time)
    return lines


def plain_lines(raw_text: str) -> list[str]:
    """Split plain (unsynced) lyrics into non-empty lines, dropping obvious
    section markers like [Chorus]."""
    out = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"[\[(（【].{0,30}[\])）】]", line):
            continue
        out.append(line)
    return out
