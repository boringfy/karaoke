"""Script-based language detection for lyrics (en / zh / ja).

Heuristic, dependency-free, and reliable for the three supported languages:
any kana => Japanese; Han without kana => Chinese; otherwise mostly-Latin =>
English.
"""

from __future__ import annotations


def _counts(text: str) -> tuple[int, int, int, int]:
    kana = han = latin = total = 0
    for ch in text:
        cp = ord(ch)
        if not ch.strip():
            continue
        total += 1
        if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF or cp == 0x30FC:
            kana += 1
        elif 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF:
            han += 1
        elif ("a" <= ch.lower() <= "z") or 0x00C0 <= cp <= 0x024F:
            latin += 1
    return kana, han, latin, total


def detect_language(text: str) -> str:
    kana, han, latin, total = _counts(text)
    if total == 0:
        return "unknown"
    cjk = kana + han
    if kana > 0 and kana >= 0.02 * total:
        return "ja"
    if han > 0 and han >= 0.25 * total:
        return "zh"
    if latin >= 0.5 * total:
        return "en"
    if cjk > latin:
        return "ja" if kana else "zh"
    return "unknown"


def latin_ratio(text: str) -> float:
    """Share of Latin letters among non-space chars — used to spot romanized
    lyrics returned for CJK songs."""
    _, _, latin, total = _counts(text)
    return latin / total if total else 0.0
