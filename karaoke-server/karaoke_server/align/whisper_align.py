"""Align known lyrics to audio; the downloaded lyric text is always ground
truth, Whisper only supplies timing.

Space-delimited languages use transcription-based alignment: a free Whisper
transcription is sequence-aligned against the downloaded words so each word
inherits its real sung time, instrumental gaps stay empty, and lyric lines a
short clip never reaches are trimmed off. CJK (and any case that yields no
usable anchors) falls back to stable-ts forced alignment.

Runs on the separated vocal stem when available (more accurate), otherwise on
the original mix. Heavy imports are local so the server runs without ML deps
installed; the stage fails with an instructive message instead of crashing at
import time.
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings

log = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model = None
_model_key: tuple[str, str, str] | None = None

# Sanity bounds: singing rate outside these marks a line as misaligned.
CJK_CHARS_PER_SEC = (0.5, 25.0)
EN_WORDS_PER_SEC = (0.3, 6.0)


class AlignmentUnavailable(RuntimeError):
    pass


@dataclass
class AlignedToken:
    text: str
    start: float
    end: float
    p: float | None = None


@dataclass
class AlignedLine:
    text: str
    start: float
    end: float
    tokens: list[AlignedToken] = field(default_factory=list)
    score: float | None = None
    alignment: str = "aligned"  # aligned | interpolated


def resolve_device() -> str:
    settings = get_settings()
    if settings.device != "auto":
        # ctranslate2 (faster-whisper) has no MPS backend; fall back to CPU.
        return "cpu" if settings.device == "mps" else settings.device
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def _load_model():
    global _model, _model_key
    settings = get_settings()
    device = resolve_device()
    compute = "float16" if device == "cuda" else settings.whisper_compute_type
    key = (settings.whisper_model, device, compute)
    with _model_lock:
        if _model is not None and _model_key == key:
            return _model
        try:
            import stable_whisper
        except ImportError as e:
            raise AlignmentUnavailable(
                "stable-ts / faster-whisper not installed. "
                "Install ML extras: pip install 'karaoke-server[ml]'"
            ) from e
        log.info("loading whisper model %s on %s (%s)", *key)
        _model = stable_whisper.load_faster_whisper(
            settings.whisper_model,
            device=device,
            compute_type=compute,
            download_root=str(settings.models_dir / "whisper"),
        )
        _model_key = key
        return _model


_CJK = re.compile(r"[一-鿿㐀-䶿぀-ゟ゠-ヿ豈-﫿々〆ヶー]")


def _is_cjk_lang(language: str | None, text: str) -> bool:
    if language in ("zh", "ja"):
        return True
    return bool(_CJK.search(text))


def _explode_cjk(tokens: list[AlignedToken]) -> list[AlignedToken]:
    """Split multi-char CJK aligner tokens into per-character tokens, dividing
    the token's duration equally among its characters."""
    out: list[AlignedToken] = []
    for tok in tokens:
        chars = [c for c in tok.text if not c.isspace()]
        if len(chars) <= 1:
            if chars:
                out.append(AlignedToken(chars[0], tok.start, tok.end, tok.p))
            continue
        dur = max(tok.end - tok.start, 0.0) / len(chars)
        for i, ch in enumerate(chars):
            out.append(
                AlignedToken(ch, tok.start + i * dur, tok.start + (i + 1) * dur, tok.p)
            )
    return out


def _line_ok(line: AlignedLine, cjk: bool, threshold: float) -> bool:
    if not line.tokens:
        return False
    dur = line.end - line.start
    if dur <= 0:
        return False
    if line.score is not None and line.score < threshold:
        return False
    rate = len(line.tokens) / dur
    lo, hi = CJK_CHARS_PER_SEC if cjk else EN_WORDS_PER_SEC
    return lo <= rate <= hi


def _interpolate_failed(lines: list[AlignedLine], anchors: list[float | None]) -> None:
    """Give failed lines timing from LRC anchors, or spread them evenly
    between their aligned neighbors."""
    n = len(lines)
    for i, line in enumerate(lines):
        if line.alignment == "aligned":
            continue
        anchor = anchors[i] if i < len(anchors) else None
        if anchor is not None:
            start = anchor
            end = anchors[i + 1] if i + 1 < len(anchors) and anchors[i + 1] else anchor + 4.0
        else:
            prev_end = next(
                (lines[j].end for j in range(i - 1, -1, -1) if lines[j].alignment == "aligned"),
                0.0,
            )
            next_start = next(
                (lines[j].start for j in range(i + 1, n) if lines[j].alignment == "aligned"),
                prev_end + 4.0,
            )
            start, end = prev_end, max(next_start, prev_end + 0.5)
        line.start, line.end = start, end
        # Distribute tokens evenly across the interpolated window.
        units = [t.text for t in line.tokens] or list(line.text.replace(" ", "")) or [line.text]
        step = (end - start) / len(units)
        line.tokens = [
            AlignedToken(u, start + k * step, start + (k + 1) * step, None)
            for k, u in enumerate(units)
        ]


def _enforce_monotonic(lines: list[AlignedLine]) -> None:
    cursor = 0.0
    for line in lines:
        if line.start < cursor:
            line.start = cursor
        if line.end < line.start:
            line.end = line.start + 0.5
        for tok in line.tokens:
            if tok.start < line.start:
                tok.start = line.start
            if tok.end < tok.start:
                tok.end = tok.start
        cursor = line.start  # lines may overlap slightly; only order starts


def _align_forced(
    audio_path: Path,
    lines: list[str],
    language: str | None,
    anchors: list[float | None] | None = None,
) -> tuple[list[AlignedLine], float]:
    """Forced alignment via stable-ts (used for CJK and as a fallback). The
    lyric text is ground truth; Whisper only decides *when* each token is sung."""
    settings = get_settings()
    model = _load_model()
    text = "\n".join(lines)
    lang = language if language in ("en", "zh", "ja") else None

    kwargs = dict(language=lang, original_split=True, vad=True, regroup=False)
    try:
        result = model.align(str(audio_path), text, **kwargs)
    except TypeError:
        # Older stable-ts without some kwarg: retry with the minimal set.
        result = model.align(str(audio_path), text, language=lang, original_split=True)

    cjk = _is_cjk_lang(lang, text)
    aligned: list[AlignedLine] = []
    segments = list(result.segments)

    # original_split=True keeps one segment per input line; guard anyway.
    for i, src in enumerate(lines):
        if i < len(segments):
            seg = segments[i]
            toks = [
                AlignedToken(w.word.strip(), float(w.start), float(w.end), float(w.probability))
                for w in (seg.words or [])
                if w.word.strip()
            ]
            if cjk:
                toks = _explode_cjk(toks)
            ps = [t.p for t in toks if t.p is not None]
            line = AlignedLine(
                text=src,
                start=float(seg.start),
                end=float(seg.end),
                tokens=toks,
                score=round(sum(ps) / len(ps), 4) if ps else None,
            )
        else:
            line = AlignedLine(text=src, start=0.0, end=0.0, score=0.0)
        if not _line_ok(line, cjk, settings.line_confidence_threshold):
            line.alignment = "interpolated"
        aligned.append(line)

    _interpolate_failed(aligned, anchors or [None] * len(aligned))
    _enforce_monotonic(aligned)

    scores = [ln.score for ln in aligned if ln.alignment == "aligned" and ln.score is not None]
    aligned_ratio = (
        sum(1 for ln in aligned if ln.alignment == "aligned") / len(aligned) if aligned else 0.0
    )
    confidence = round((sum(scores) / len(scores) if scores else 0.0) * aligned_ratio, 4)
    return aligned, confidence


# --- Transcription-based alignment (primary for space-delimited languages) ---
#
# Downloaded lyrics are the source of truth for *text*; a free Whisper
# transcription supplies *timing* only. We sequence-align the two word streams
# so each downloaded word inherits its real sung time, leaving instrumental
# gaps empty, and trim lyric lines the (possibly short) audio never reaches.

_CREDIT = re.compile(r"作词|作詞|作曲|编曲|編曲|作曲家|lyricist|composer|arrang", re.I)
_NORM = re.compile(r"[^a-z0-9']")


def _norm_word(s: str) -> str:
    return _NORM.sub("", s.lower().replace("’", "'").replace("‘", "'"))


def _lyric_lines(lines: list[str]) -> list[str]:
    """Drop blank lines and metadata credit lines from downloaded lyrics."""
    return [ln.strip() for ln in lines if ln.strip() and not _CREDIT.search(ln)]


def _transcribe_words(audio_path: Path, lang: str | None) -> list[tuple[str, float, float, float]]:
    """Whisper transcription -> flat (norm_word, start, end, prob). Timing only;
    the decoded words themselves are never shown to the user."""
    model = _load_model()
    result = model.transcribe(
        str(audio_path), language=lang, word_timestamps=True, vad=False,
        regroup=False, verbose=None,
        # Off: prevents the tail from hallucinating a looped repeat of the
        # lyrics, which would mis-anchor against repeated choruses.
        condition_on_previous_text=False,
    )
    words: list[tuple[str, float, float, float]] = []
    for seg in result.segments:
        for w in seg.words or []:
            n = _norm_word(w.word)
            if n:
                words.append(
                    (n, float(w.start), float(w.end), float(getattr(w, "probability", 0.0) or 0.0))
                )
    return words


def _align_by_transcription(
    audio_path: Path, lines: list[str], language: str | None
) -> tuple[list[AlignedLine], float]:
    lyr = _lyric_lines(lines)
    if not lyr:
        return [], 0.0
    wh = _transcribe_words(audio_path, language)
    if not wh:
        return [], 0.0

    # Flatten downloaded words: [line_idx, original, norm, start, end, prob|None]
    dl: list[list] = []
    for li, text in enumerate(lyr):
        for word in text.split():
            n = _norm_word(word)
            if n:
                dl.append([li, word, n, None, None, None])
    if not dl:
        return [], 0.0

    # difflib LCS blocks tolerate skipped verses / repeated choruses; within a
    # 'replace' block, pair words positionally so near-mishears still anchor.
    sm = difflib.SequenceMatcher(a=[d[2] for d in dl], b=[w[0] for w in wh], autojunk=False)
    anchored: list[int] = []

    def _anchor(i: int, j: int) -> None:
        dl[i][3], dl[i][4], dl[i][5] = wh[j][1], wh[j][2], wh[j][3]
        anchored.append(i)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                _anchor(i1 + k, j1 + k)
        elif tag == "replace":
            for k in range(min(i2 - i1, j2 - j1)):
                if difflib.SequenceMatcher(None, dl[i1 + k][2], wh[j1 + k][0]).ratio() >= 0.45:
                    _anchor(i1 + k, j1 + k)

    if not anchored:
        return [], 0.0

    # Determine the contiguous band of lyric lines the audio actually covers.
    # A short clip is a sub-range of the full lyrics; a line only counts as
    # really sung if a real fraction of *its own* words anchored (a lone stray
    # match from a repeated chorus or a hallucinated outro must not extend the
    # band). Keep the run of solid lines, stopping at the first big gap. This is
    # what "cut the lyrics short" means for clips.
    total: dict[int, int] = {}
    hits: dict[int, int] = {}
    for d in dl:
        total[d[0]] = total.get(d[0], 0) + 1
        if d[5] is not None:
            hits[d[0]] = hits.get(d[0], 0) + 1
    solid = sorted(li for li, n in total.items() if hits.get(li, 0) / n >= 0.4)
    if not solid:
        return [], 0.0
    kept_first = kept_last = solid[0]
    for li in solid[1:]:
        if li - kept_last <= 8:
            kept_last = li
        else:
            break
    dl = [d for d in dl if kept_first <= d[0] <= kept_last]

    # Interpolate un-anchored runs evenly between their bounding anchors.
    i = 0
    while i < len(dl):
        if dl[i][3] is None:
            j = i
            while j < len(dl) and dl[j][3] is None:
                j += 1
            prev_end = dl[i - 1][4] if i > 0 and dl[i - 1][4] is not None else 0.0
            next_start = dl[j][3] if j < len(dl) else prev_end + 0.5 * (j - i)
            step = (next_start - prev_end) / (j - i + 1)
            for k in range(i, j):
                dl[k][3] = prev_end + step * (k - i + 0.5)
                dl[k][4] = prev_end + step * (k - i + 1)
            i = j
        else:
            i += 1

    # Group into lines with monotonically non-decreasing token starts.
    cjk = _is_cjk_lang(language, "\n".join(lyr))
    by_line: dict[int, list[AlignedToken]] = {}
    cursor = 0.0
    for li, original, _n, s, e, p in dl:
        s = max(float(s), cursor)
        e = max(float(e), s)
        by_line.setdefault(li, []).append(AlignedToken(original, s, e, p))
        cursor = s

    aligned: list[AlignedLine] = []
    for li in sorted(by_line):
        toks = _explode_cjk(by_line[li]) if cjk else by_line[li]
        ps = [t.p for t in toks if t.p is not None]
        aligned.append(
            AlignedLine(
                text=lyr[li],
                start=toks[0].start,
                end=toks[-1].end,
                tokens=toks,
                score=round(sum(ps) / len(ps), 4) if ps else None,
                alignment="aligned",
            )
        )

    probs = [d[5] for d in dl if d[5] is not None]
    anchored_ratio = len(probs) / len(dl) if dl else 0.0
    mean_p = sum(probs) / len(probs) if probs else 0.0
    return aligned, round(anchored_ratio * mean_p, 4)


def align_lyrics(
    audio_path: Path,
    lines: list[str],
    language: str | None,
    anchors: list[float | None] | None = None,
) -> tuple[list[AlignedLine], float]:
    """Blocking (call from a worker thread). Returns (aligned lines, overall
    confidence 0-1).

    Space-delimited languages use transcription-based alignment (downloaded text
    + Whisper timing, trimmed to the audio). CJK falls back to stable-ts forced
    alignment, as does any case where transcription yields no usable anchors.
    """
    _load_model()  # surfaces AlignmentUnavailable early if ML deps are missing
    # Route on the declared language, not the text: downloaded credits may carry
    # stray CJK that would misclassify an English song.
    if language in ("zh", "ja"):
        cjk = True
    elif language == "en":
        cjk = False
    else:
        cjk = _is_cjk_lang(None, "\n".join(_lyric_lines(lines)))

    if not cjk:
        try:
            aligned, confidence = _align_by_transcription(audio_path, lines, language)
        except Exception:  # noqa: BLE001 - never let timing fall over the pipeline
            log.exception("transcription alignment failed; using forced alignment")
            aligned, confidence = [], 0.0
        if aligned:
            return aligned, confidence
        log.warning("transcription alignment produced nothing; using forced alignment")

    return _align_forced(audio_path, lines, language, anchors)
