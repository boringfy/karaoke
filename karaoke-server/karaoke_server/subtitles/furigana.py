"""Furigana (ruby) annotation for Japanese lyrics.

fugashi (MeCab) + unidic-lite supplies katakana readings; we convert to
hiragana and trim okurigana so ruby covers only the kanji span:

    走る   -> [走(はし)][る]          (trailing okurigana trimmed)
    打ち合わせ -> [打(う)][ち][合(あ)][わせ]  (interior kana matched piecewise)

Tokens made only of kana / latin / digits / symbols get no ruby.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import jaconv

_KANJI = re.compile(r"[一-鿿㐀-䶿豈-﫿々〆ヶ]")
_KANA_RUN = re.compile(r"[぀-ゟ゠-ヿー]+")


@dataclass
class RubySeg:
    """A run of text that is either one kanji block with a reading, or plain
    text with no ruby."""

    text: str
    ruby: str | None = None


def has_kanji(text: str) -> bool:
    return bool(_KANJI.search(text))


@lru_cache(maxsize=1)
def _tagger():
    from fugashi import Tagger

    return Tagger()


def _reading_hira(word) -> str | None:
    """Hiragana reading of a fugashi token's surface form."""
    f = word.feature
    kana = getattr(f, "kana", None) or getattr(f, "pron", None)
    if not kana or kana == "*":
        return None
    return jaconv.kata2hira(kana)


def _split_token(surface: str, reading: str) -> list[RubySeg]:
    """Partition one token into kanji/kana runs and distribute the reading.

    Builds a regex from the surface: kana runs match themselves (in hiragana
    space), each kanji run becomes a lazy capture group consuming its share of
    the reading. Falls back to whole-token ruby when the match fails (rare:
    irregular readings)."""
    runs: list[tuple[str, bool]] = []  # (run_text, is_kanji_run)
    for part in re.split(f"({_KANA_RUN.pattern})", surface):
        if not part:
            continue
        runs.append((part, not _KANA_RUN.fullmatch(part)))

    pattern = ""
    for text, is_kanji in runs:
        if is_kanji:
            pattern += "(.+?)"
        else:
            pattern += re.escape(jaconv.kata2hira(text))
    m = re.fullmatch(pattern, reading)
    if not m:
        return [RubySeg(text=surface, ruby=reading)]

    segs: list[RubySeg] = []
    group = 0
    for text, is_kanji in runs:
        if is_kanji:
            group += 1
            segs.append(RubySeg(text=text, ruby=m.group(group)))
        else:
            segs.append(RubySeg(text=text))
    return segs


def ruby_segments(text: str) -> list[RubySeg]:
    """Annotate a Japanese line, returning contiguous segments whose
    concatenated text equals the input exactly (whitespace preserved)."""
    segs: list[RubySeg] = []
    pos = 0
    for word in _tagger()(text):
        surface = word.surface
        # Preserve any text the tokenizer skipped (spaces, etc.).
        idx = text.find(surface, pos)
        if idx > pos:
            segs.append(RubySeg(text=text[pos:idx]))
        pos = idx + len(surface) if idx >= 0 else pos

        if not has_kanji(surface):
            segs.append(RubySeg(text=surface))
            continue
        reading = _reading_hira(word)
        if not reading:
            segs.append(RubySeg(text=surface))
            continue
        segs.extend(_split_token(surface, reading))
    if pos < len(text):
        segs.append(RubySeg(text=text[pos:]))

    # Merge adjacent no-ruby segments for a compact result.
    merged: list[RubySeg] = []
    for seg in segs:
        if merged and seg.ruby is None and merged[-1].ruby is None:
            merged[-1].text += seg.text
        else:
            merged.append(RubySeg(seg.text, seg.ruby))
    return merged
