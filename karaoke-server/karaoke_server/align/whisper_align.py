"""Align known lyrics to audio; the downloaded lyric text is always ground
truth, Whisper only supplies timing.

All languages use transcription-based alignment first: a free Whisper
transcription is sequence-aligned against the downloaded lyrics so each unit
inherits its real sung time, instrumental gaps stay empty, and lyric lines a
short clip never reaches are trimmed off. Space-delimited languages match at
the word level; CJK matches at the character level (katakana folded to
hiragana so kana spelling differences still anchor). Any case that yields no
usable anchors falls back to stable-ts forced alignment.

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
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from ..media import ffmpeg

log = logging.getLogger(__name__)

_model_lock = threading.Lock()
_model = None
_model_key: tuple[str, str, str] | None = None

# Sanity bounds: singing rate outside these marks a line as misaligned.
CJK_CHARS_PER_SEC = (0.5, 25.0)
EN_WORDS_PER_SEC = (0.3, 6.0)

# Assumed singing rates for lines whose timing had to be interpolated from LRC
# anchors. Deliberately conservative (slightly slower than typical singing):
# a wipe that runs a touch long is far less jarring than one still half done
# when the line has been fully sung. Used to cap the token spread so a line
# followed by a held note or instrumental break doesn't crawl across the gap.
INTERP_CJK_RATE = 2.5  # chars / sec
INTERP_WORD_RATE = 2.0  # words / sec


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
    if line.end - line.start <= 0:
        return False
    if line.score is not None and line.score < threshold:
        return False
    # Rate over the token span, not the segment window: segment ends absorb
    # trailing melisma / VAD padding, which would deflate the rate and reject
    # perfectly aligned lines.
    span = line.tokens[-1].end - line.tokens[0].start
    if span <= 0:
        return False
    rate = len(line.tokens) / span
    lo, hi = CJK_CHARS_PER_SEC if cjk else EN_WORDS_PER_SEC
    return lo <= rate <= hi


def _interpolate_failed(
    lines: list[AlignedLine], anchors: list[float | None], cjk: bool
) -> None:
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
        # Distribute tokens evenly, but only over a plausible singing duration:
        # the anchor window runs to the *next* line and may contain a held note
        # or an instrumental break the wipe must not crawl across. The line
        # itself stays displayed for the full window (line.end untouched).
        units = [t.text for t in line.tokens] or list(line.text.replace(" ", "")) or [line.text]
        rate = INTERP_CJK_RATE if cjk else INTERP_WORD_RATE
        tok_end = min(end, start + max(2.0, len(units) / rate))
        step = (tok_end - start) / len(units)
        line.tokens = [
            AlignedToken(u, start + k * step, start + (k + 1) * step, None)
            for k, u in enumerate(units)
        ]


def _cap_final_token(toks: list[AlignedToken]) -> None:
    """Cap the last token's duration relative to the line's median token.

    Aligner segment tails absorb held notes *and* VAD padding / silence. A slow
    fill on a genuinely held final note is desirable karaoke behavior (it says
    "keep holding"), so real holds of a few seconds survive the 3x-median cap;
    ten seconds of absorbed silence does not.
    """
    if not toks:
        return
    durs = sorted(t.end - t.start for t in toks)
    median = durs[len(durs) // 2]
    cap = toks[-1].start + max(1.0, 3 * median)
    if toks[-1].end > cap:
        toks[-1].end = cap


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
            _cap_final_token(toks)
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

    _interpolate_failed(aligned, anchors or [None] * len(aligned), cjk)
    _enforce_monotonic(aligned)

    scores = [ln.score for ln in aligned if ln.alignment == "aligned" and ln.score is not None]
    aligned_ratio = (
        sum(1 for ln in aligned if ln.alignment == "aligned") / len(aligned) if aligned else 0.0
    )
    confidence = round((sum(scores) / len(scores) if scores else 0.0) * aligned_ratio, 4)
    return aligned, confidence


# --- Transcription-based alignment (primary path for all languages) ---
#
# Downloaded lyrics are the source of truth for *text*; a free Whisper
# transcription supplies *timing* only. We sequence-align the two unit streams
# (words for space-delimited languages, characters for CJK) so each downloaded
# unit inherits its real sung time, leaving instrumental gaps empty, and trim
# lyric lines the (possibly short) audio never reaches.

_CREDIT = re.compile(
    r"作词|作詞|作曲|编曲|編曲|作曲家|制作|製作|监制|監製|出品|发行|發行"
    r"|混音|录音|錄音|母带|母帶|企划|企劃|プロデュ"
    r"|lyricist|composer|arrang|produc|mixed by|mastered", re.I,
)
_NORM = re.compile(r"[^a-z0-9']")


def _norm_word(s: str) -> str:
    return _NORM.sub("", s.lower().replace("’", "'").replace("‘", "'"))


_CJK_PUNCT = set("、。，．・「」『』（）【】《》！？…〜～”“‘’\"'!?,.:;()[]<>-—/｜|")


def _fold_kana(ch: str) -> str:
    # Katakana -> hiragana: U+30A1..U+30F6 maps down by 0x60 (covers ヴ->ゔ).
    # ー (U+30FC) is outside the range and stays as-is; Whisper emits it too,
    # so both streams carry it consistently.
    o = ord(ch)
    return chr(o - 0x60) if 0x30A1 <= o <= 0x30F6 else ch


@lru_cache(maxsize=8192)
def _fold_simplified(ch: str) -> str:
    """Fold a CJK ideograph to Simplified via OpenCC — FOR MATCHING ONLY.

    Whisper's Chinese output freely mixes Traditional and Simplified forms
    while lyrics are usually one or the other; the mismatched codepoints
    (讀 vs 读) would never anchor. Folding BOTH streams through the same
    transform keeps matching consistent without touching display text."""
    o = ord(ch)
    if not (0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF):
        return ch
    try:

        conv = _fold_simplified_cc()
        out = conv.convert(ch)
        return out if len(out) == 1 else ch
    except Exception:  # noqa: BLE001 - matching still works unfolded
        return ch


@lru_cache(maxsize=1)
def _fold_simplified_cc():
    from opencc import OpenCC

    return OpenCC("t2s")


def _norm_char(ch: str) -> str:
    """Normalize one character for matching: NFKC, lowercase, katakana folded
    to hiragana, CJK ideographs folded to Simplified (both streams get the
    same fold, so it only ever helps matching). Spaces and punctuation
    normalize to '' (never match)."""
    ch = unicodedata.normalize("NFKC", ch).lower()
    if not ch:
        return ""
    ch = ch[0]  # NFKC can expand (e.g. ㍿); keep the leading char
    if ch.isspace() or ch in _CJK_PUNCT:
        return ""
    return _fold_simplified(_fold_kana(ch))


def _lyric_lines(lines: list[str]) -> list[str]:
    """Drop blank lines and metadata credit lines from downloaded lyrics."""
    return [ln.strip() for ln in lines if ln.strip() and not _CREDIT.search(ln)]


def _lyric_units(lyr: list[str], cjk: bool) -> list[list]:
    """Flatten lyrics to [line_idx, original, norm, start, end, prob] rows.

    Word mode: one row per whitespace-separated word (rows that normalize to
    nothing are dropped, as before). Char mode: one row per non-space character.
    Punctuation rows are kept with norm='' — they can never anchor, but they
    must become tokens because the furigana stage consumes exactly one token
    per character of the line text.
    """
    dl: list[list] = []
    for li, text in enumerate(lyr):
        if cjk:
            for ch in text:
                if ch.isspace():
                    continue
                dl.append([li, ch, _norm_char(ch), None, None, None])
        else:
            for word in text.split():
                n = _norm_word(word)
                if n:
                    dl.append([li, word, n, None, None, None])
    return dl


def _transcribe_units(
    audio_path: Path, lang: str | None, cjk: bool
) -> list[tuple[str, float, float, float]]:
    """Whisper transcription -> flat (norm_unit, start, end, prob). Timing only;
    the decoded text itself is never shown to the user. In char mode each
    Whisper word is exploded into per-character timings (even split)."""
    model = _load_model()
    result = model.transcribe(
        str(audio_path), language=lang, word_timestamps=True, vad=False,
        regroup=False, verbose=None,
        # Off: prevents the tail from hallucinating a looped repeat of the
        # lyrics, which would mis-anchor against repeated choruses.
        condition_on_previous_text=False,
    )
    units: list[tuple[str, float, float, float]] = []
    for seg in result.segments:
        for w in seg.words or []:
            s, e = float(w.start), float(w.end)
            p = float(getattr(w, "probability", 0.0) or 0.0)
            if cjk:
                chars = [c for c in (_norm_char(ch) for ch in w.word) if c]
                if not chars:
                    continue
                dur = max(e - s, 0.0) / len(chars)
                for i, c in enumerate(chars):
                    units.append((c, s + i * dur, s + (i + 1) * dur, p))
            else:
                n = _norm_word(w.word)
                if n:
                    units.append((n, s, e, p))
    return units


@lru_cache(maxsize=4)
def _speech_regions(audio_path: Path) -> tuple[tuple[float, float], ...]:
    """VAD-detected vocal stretches, as absolute (start, end) second pairs.
    Empty when the audio can't be read (callers then fall back to plain
    interpolation)."""
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        sr = 16000
        audio = decode_audio(str(audio_path), sampling_rate=sr)
        return tuple(
            (t["start"] / sr, t["end"] / sr)
            for t in get_speech_timestamps(audio, VadOptions())
        )
    except Exception:  # noqa: BLE001 - VAD is an optimization, never fatal
        log.exception("VAD failed for %s; interpolating without it", audio_path)
        return ()


def _place_in_speech(
    lo: float, hi: float, n: int, speech: tuple[tuple[float, float], ...]
) -> list[tuple[float, float]]:
    """Lay out `n` un-anchored units in (lo, hi), keeping them on the parts
    where the VAD hears singing.

    Without this, a run of unmatched lines gets smeared evenly across the
    whole window — so a bridge that follows a 20 s instrumental break appears
    on screen while the track is still instrumental. Units are distributed
    over the *speech* portion of the window instead; the silence between
    those stretches is simply skipped."""
    if n <= 0:
        return []
    if hi <= lo:
        return [(lo, lo)] * n
    spans = [(max(s, lo), min(e, hi)) for s, e in speech if e > lo and s < hi]
    spans = [(s, e) for s, e in spans if e > s]
    total = sum(e - s for s, e in spans)
    if not spans or total <= 0.05:
        # No vocals detected in the window: fall back to an even spread, but
        # cap it to a plausible singing pace so the run doesn't crawl.
        step = (hi - lo) / (n + 1)
        return [(lo + step * (k + 0.5), lo + step * (k + 1)) for k in range(n)]

    def at(fraction: float) -> float:
        """Map [0,1] over cumulative speech time back to the timeline."""
        target = fraction * total
        acc = 0.0
        for s, e in spans:
            d = e - s
            if acc + d >= target:
                return s + (target - acc)
            acc += d
        return spans[-1][1]

    return [(at(k / n), at((k + 1) / n)) for k in range(n)]


def _align_by_transcription(
    audio_path: Path,
    lines: list[str],
    language: str | None,
    anchors: list[float | None] | None = None,
) -> tuple[list[AlignedLine], float]:
    # Filter blank/credit lines, keeping each surviving line's LRC anchor.
    lyr: list[str] = []
    lyr_anchors: list[float | None] = []
    for i, raw in enumerate(lines):
        text = raw.strip()
        if not text or _CREDIT.search(text):
            continue
        lyr.append(text)
        lyr_anchors.append(anchors[i] if anchors and i < len(anchors) else None)
    if not lyr:
        return [], 0.0
    # Route on the declared language, not the text: downloaded credits may
    # carry stray CJK that would misclassify an English song.
    if language in ("zh", "ja"):
        cjk = True
    elif language == "en":
        cjk = False
    else:
        cjk = _is_cjk_lang(None, "\n".join(lyr))

    wh = _transcribe_units(audio_path, language, cjk)
    if not wh:
        return [], 0.0

    # Flatten downloaded lyrics: [line_idx, original, norm, start, end, prob|None]
    dl = _lyric_units(lyr, cjk)
    if not dl:
        return [], 0.0

    # Only rows with a non-empty norm take part in matching (char mode keeps
    # punctuation rows with norm='' so they still become tokens later).
    midx = [i for i, d in enumerate(dl) if d[2]]
    if not midx:
        return [], 0.0

    # difflib LCS blocks tolerate skipped verses / repeated choruses; within a
    # 'replace' block, pair units positionally so near-mishears still anchor.
    sm = difflib.SequenceMatcher(
        a=[dl[i][2] for i in midx], b=[w[0] for w in wh], autojunk=False
    )
    anchored: list[int] = []
    jmap: dict[int, int] = {}  # transcript unit -> lyric line it anchored to

    def _anchor(mi: int, j: int) -> None:
        i = midx[mi]
        dl[i][3], dl[i][4], dl[i][5] = wh[j][1], wh[j][2], wh[j][3]
        anchored.append(i)
        jmap[j] = dl[i][0]

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                _anchor(i1 + k, j1 + k)
        elif tag == "replace":
            # Single-char units never clear the 0.45 ratio, so this pairing is
            # effectively word-mode only; kana folding already put same-sound
            # CJK chars into 'equal' blocks.
            for k in range(min(i2 - i1, j2 - j1)):
                if (
                    difflib.SequenceMatcher(
                        None, dl[midx[i1 + k]][2], wh[j1 + k][0]
                    ).ratio()
                    >= 0.45
                ):
                    _anchor(i1 + k, j1 + k)

    if not anchored:
        return [], 0.0

    # Keep only the lyric lines the audio actually covers. A line counts as
    # really sung ("solid") when a real fraction of *its own* units anchored —
    # a lone stray match from a repeated chorus or a hallucinated outro doesn't
    # qualify. Solid lines may form SEVERAL bands, not one: a TV-size / short
    # edit often skips a middle verse of the full lyrics and then sings the
    # finale, so stopping at the first gap would wrongly drop the ending.
    # Small gaps between solid lines (mis-heard but sung lines) are bridged;
    # big gaps (the skipped verse) are dropped. Unmatchable punctuation rows
    # are excluded so they don't dilute a line's anchored ratio.
    total: dict[int, int] = {}
    hits: dict[int, int] = {}
    for i in midx:
        d = dl[i]
        total[d[0]] = total.get(d[0], 0) + 1
        if d[5] is not None:
            hits[d[0]] = hits.get(d[0], 0) + 1
    solid = sorted(li for li, n in total.items() if hits.get(li, 0) / n >= 0.4)
    if not solid:
        return [], 0.0
    keep: set[int] = set(solid)
    for a, b in zip(solid, solid[1:], strict=False):
        if b - a <= 8:
            keep.update(range(a + 1, b))
    # Transcript units whose anchor survived the trim; the rest are free for
    # the out-of-order recovery pass below.
    used_j = {j for j, li in jmap.items() if li in keep}
    dl = [d for d in dl if d[0] in keep]

    # Fill in un-anchored runs (units the transcript never matched). Spreading
    # them evenly across the whole gap would drag lyrics through instrumental
    # breaks — the classic "words on screen while nobody sings" bug — so they
    # are placed only where the VAD hears vocals.
    speech = _speech_regions(audio_path)
    i = 0
    while i < len(dl):
        if dl[i][3] is None:
            j = i
            while j < len(dl) and dl[j][3] is None:
                j += 1
            prev_end = dl[i - 1][4] if i > 0 and dl[i - 1][4] is not None else 0.0
            next_start = dl[j][3] if j < len(dl) else prev_end + 0.5 * (j - i)
            for k, (s, e) in enumerate(
                _place_in_speech(prev_end, next_start, j - i, speech)
            ):
                dl[i + k][3], dl[i + k][4] = s, e
            i = j
        else:
            i += 1

    # Group into lines with monotonically non-decreasing token starts.
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
                # Nothing in this line was actually heard — its timing came
                # from surrounding anchors, so report the weaker trust level
                # instead of passing guesswork off as heard timing.
                alignment="aligned" if ps else "interpolated",
            )
        )

    _recover_reordered(aligned, lyr, wh, used_j, cjk)
    _recover_gaps(aligned, lyr, audio_path, language, cjk)
    _recover_from_anchors(aligned, lyr, lyr_anchors, cjk, audio_path)
    aligned.sort(key=lambda ln: (ln.start, ln.end))

    probs = [d[5] for d in dl if d[5] is not None]
    matchable = sum(1 for d in dl if d[2])
    anchored_ratio = len(probs) / matchable if matchable else 0.0
    mean_p = sum(probs) / len(probs) if probs else 0.0
    return aligned, round(anchored_ratio * mean_p, 4)


def _recover_from_anchors(
    aligned: list[AlignedLine],
    lyr: list[str],
    anchors: list[float | None],
    cjk: bool,
    audio_path: Path,
) -> None:
    """Last resort for lines every audio-based pass missed: place them at
    their synced-LRC timestamp.

    Some deliveries defeat ASR outright (e.g. 曹操's low spoken-style opening
    hook, which Whisper hears as streaming-site watermark boilerplate). When
    the lyric candidate carries LRC times, those are trustworthy for the
    recording they were synced to — so a missing line is emitted at its LRC
    anchor, but only when (a) the LRC timeline plausibly fits this recording
    (last anchor within the audio; a full-song LRC over a TV-size clip is
    rejected wholesale) and (b) the anchor window is not already covered.
    Marked "interpolated": timing is per-line, not heard per-character."""
    if not aligned or not any(a is not None for a in anchors):
        return
    covered = [(ln.start, ln.end) for ln in aligned]
    last_anchor = max(a for a in anchors if a is not None)
    total = ffmpeg.probe_duration(Path(audio_path)) if Path(audio_path).exists() else None
    horizon = total if total else max(e for _, e in covered) + 60.0
    if last_anchor > horizon + 5.0:
        return  # LRC timeline is for a different edit of the song
    for li, text in enumerate(lyr):
        a = anchors[li] if li < len(anchors) else None
        if a is None or a < 0:
            continue
        nxt = next(
            (anchors[j] for j in range(li + 1, len(anchors)) if anchors[j] is not None),
            None,
        )
        end = min(nxt, a + 8.0) if nxt is not None and nxt > a else a + 4.0
        if end - a < 0.5:
            continue
        if any(a < ce - 0.25 and end > cs + 0.25 for cs, ce in covered):
            continue
        rows = _lyric_units([text], cjk)
        if not rows:
            continue
        rate = INTERP_CJK_RATE if cjk else INTERP_WORD_RATE
        tok_end = min(end, a + max(2.0, len(rows) / rate))
        step = (tok_end - a) / len(rows)
        toks = [
            AlignedToken(r[1], a + k * step, a + (k + 1) * step, None)
            for k, r in enumerate(rows)
        ]
        aligned.append(
            AlignedLine(
                text=text,
                start=round(a, 3),
                end=round(end, 3),
                tokens=toks,
                score=None,
                alignment="interpolated",
            )
        )
        covered.append((a, end))


def _recover_gaps(
    aligned: list[AlignedLine],
    lyr: list[str],
    audio_path: Path,
    language: str | None,
    cjk: bool,
) -> None:
    """Re-transcribe large spans the subtitle doesn't cover.

    Whisper reliably hallucinates boilerplate (fake 作詞/作曲 credit lines)
    across quiet song intros — even on a clean vocal stem, even with VAD —
    swallowing softly-sung opening lines. Starting the decode window at the
    VAD-detected vocal onset snaps the decoder out of it. Each gap window is
    transcribed separately and fed through the same text-matching recovery as
    reordered sections, so only stretches that genuinely match lyric lines
    produce subtitles (hallucinations match nothing and are dropped).
    """
    if not aligned or not Path(audio_path).exists():
        return
    # Measure coverage by what was actually HEARD. Interpolated lines are
    # guesses about exactly the stretches this pass needs to investigate — if
    # they counted as coverage they would hide the hole they were invented to
    # span (a hallucinated credit line over an instrumental break makes the
    # real lyrics unanchorable, and the guesses then mask the break).
    heard = [ln for ln in aligned if ln.alignment == "aligned"]
    if not heard:
        return
    spans = sorted((ln.start, ln.end) for ln in heard)
    gaps: list[tuple[float, float]] = []
    if spans[0][0] > 12.0:
        gaps.append((0.0, spans[0][0] + 1.0))
    prev_end = spans[0][1]
    for s, e in spans[1:]:
        if s - prev_end > 15.0:
            gaps.append((max(0.0, prev_end - 1.0), s + 1.0))
        prev_end = max(prev_end, e)
    total = ffmpeg.probe_duration(Path(audio_path))
    if total and total - prev_end > 12.0:
        gaps.append((max(0.0, prev_end - 1.0), total))

    for gs, ge in gaps[:4]:
        try:
            units = _transcribe_window(audio_path, language, cjk, gs, ge)
        except Exception:  # noqa: BLE001 - recovery is strictly best-effort
            log.exception("gap re-transcription failed for %.1f-%.1fs", gs, ge)
            continue
        if not units:
            continue
        # Guesses inside this window are about to be re-decided on evidence:
        # set them aside so their lines can be timed from the re-transcription.
        stale = sorted(
            (
                ln
                for ln in aligned
                if ln.alignment == "interpolated"
                and ln.start >= gs - 1.0
                and ln.end <= ge + 1.0
            ),
            key=lambda ln: ln.start,
        )
        for ln in stale:
            aligned.remove(ln)
        placed: set[str] = set()
        if stale:
            # These lines are consecutive in the lyrics, so a plain monotonic
            # transfer against the window transcript is both precise and
            # order-safe — the fuzzy whole-segment matcher below is meant for
            # *reordered* material and gets lost among filler ("aaah") units.
            for ln in _transfer_timing([s.text for s in stale], units, cjk):
                aligned.append(ln)
                placed.add(ln.text)
        before = len(aligned)
        _recover_reordered(aligned, lyr, units, set(), cjk)
        placed.update(ln.text for ln in aligned[before:])
        # Keep any line the evidence couldn't place, rather than losing lyrics.
        aligned.extend(ln for ln in stale if ln.text not in placed)


def _transfer_timing(
    texts: list[str], units: list[tuple[str, float, float, float]], cjk: bool
) -> list[AlignedLine]:
    """Time a run of consecutive lyric lines against a transcript, monotonically.

    The main pass's anchoring restricted to a subset: lines keep their order,
    so a plain LCS transfer is precise even when the transcript carries filler
    the lyrics don't have. Only lines that genuinely anchor are returned —
    callers keep their previous guess for the rest."""
    rows = _lyric_units(texts, cjk)
    midx = [i for i, r in enumerate(rows) if r[2]]
    if not rows or not midx or not units:
        return []
    sm = difflib.SequenceMatcher(
        a=[rows[i][2] for i in midx], b=[u[0] for u in units], autojunk=False
    )
    for tag, i1, i2, j1, _j2 in sm.get_opcodes():
        if tag != "equal":
            continue
        for k in range(i2 - i1):
            i = midx[i1 + k]
            rows[i][3], rows[i][4], rows[i][5] = units[j1 + k][1:4]

    out: list[AlignedLine] = []
    for li, text in enumerate(texts):
        mine = [r for r in rows if r[0] == li]
        matchable = [r for r in mine if r[2]]
        anchored = [r for r in mine if r[3] is not None]
        if not matchable or len(anchored) / len(matchable) < 0.4:
            continue  # not convincingly heard here; leave it to the caller
        lo, hi = anchored[0][3], anchored[-1][4]
        span = max(hi - lo, 0.2)
        step = span / len(mine)
        toks: list[AlignedToken] = []
        cursor = lo
        for k, r in enumerate(mine):
            s = r[3] if r[3] is not None else lo + step * k
            e = r[4] if r[4] is not None else s + step
            s = max(float(s), cursor)
            e = max(float(e), s)
            toks.append(AlignedToken(r[1], round(s, 3), round(e, 3), r[5]))
            cursor = s
        if cjk:
            toks = _explode_cjk(toks)
        ps = [t.p for t in toks if t.p is not None]
        out.append(
            AlignedLine(
                text=text,
                start=toks[0].start,
                end=toks[-1].end,
                tokens=toks,
                score=round(sum(ps) / len(ps), 4) if ps else None,
                alignment="aligned",
            )
        )
    return out


def _transcribe_window(
    audio_path: Path, language: str | None, cjk: bool, start: float, end: float
) -> list[tuple[str, float, float, float]]:
    """Transcribe [start, end] of the audio, beginning at the first VAD-detected
    vocal onset inside the window; unit times are absolute (offset applied)."""
    import tempfile
    import wave

    import numpy as np
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    sr = 16000
    audio = decode_audio(str(audio_path), sampling_rate=sr)
    window = audio[int(start * sr) : int(end * sr)]
    if len(window) < sr:
        return []
    speech = get_speech_timestamps(window, VadOptions())
    if not speech:
        return []  # nothing sung here (a real instrumental break)
    onset = max(0.0, speech[0]["start"] / sr - 0.3)
    offset = start + onset
    clip = window[int(onset * sr) :]

    import os

    fd, tmp_name = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes((np.clip(clip, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
        units = _transcribe_units(tmp, language, cjk)
    finally:
        tmp.unlink(missing_ok=True)
    return [(n, s + offset, e + offset, p) for n, s, e, p in units]


def _recover_reordered(
    aligned: list[AlignedLine],
    lyr: list[str],
    wh: list[tuple[str, float, float, float]],
    used_j: set[int],
    cjk: bool,
) -> None:
    """Rescue sections sung OUT of lyric order (appended to `aligned`).

    A TV-size or concert edit may open with the chorus or repeat it; a
    monotonic global alignment can never anchor those. Group the transcript
    units the first pass did not consume into time-contiguous segments, match
    each segment's text against every lyric line, and re-emit strong matches
    at the segment's real time — a line may then rightfully appear more than
    once. Recurses on the leftovers so a twice-sung chorus yields both copies.
    """
    sep = "" if cjk else " "
    line_norms: dict[int, str] = {}
    for li, text in enumerate(lyr):
        if cjk:
            units = [c for c in (_norm_char(ch) for ch in text) if c]
        else:
            units = [w for w in (_norm_word(x) for x in text.split()) if w]
        if units:
            line_norms[li] = sep.join(units)

    covered = [(ln.start, ln.end) for ln in aligned]

    def _is_covered(s: float, e: float) -> bool:
        return any(s < ce - 0.5 and e > cs + 0.5 for cs, ce in covered)

    def _emit(seg: list[int], depth: int) -> None:
        if depth > 4 or len(seg) < 3:
            return
        # Character offset of each unit inside the joined segment text.
        offs: list[int] = []
        pos = 0
        parts: list[str] = []
        for j in seg:
            offs.append(pos)
            parts.append(wh[j][0])
            pos += len(wh[j][0]) + len(sep)
        seg_text = sep.join(parts)

        best: tuple[float, int, int, int] | None = None  # coverage, li, a1, a2
        for li, ln_norm in line_norms.items():
            smx = difflib.SequenceMatcher(None, seg_text, ln_norm, autojunk=False)
            blocks = [b for b in smx.get_matching_blocks() if b.size]
            if not blocks:
                continue
            coverage = sum(b.size for b in blocks) / len(ln_norm)
            if coverage < 0.6:
                continue
            a1, a2 = blocks[0].a, blocks[-1].a + blocks[-1].size
            if best is None or coverage > best[0]:
                best = (coverage, li, a1, a2)
        if best is None:
            return
        _cov, li, a1, a2 = best
        # Map the matched char window back to unit indices.
        u1 = max(k for k, o in enumerate(offs) if o <= a1)
        u2 = min((k for k, o in enumerate(offs) if o >= a2), default=len(seg) - 1)
        u2 = max(u2, u1 + 1)
        s = wh[seg[u1]][1]
        e = wh[seg[min(u2, len(seg) - 1)]][2]
        if e - s >= 1.0 and not _is_covered(s, e):
            rows = _lyric_units([lyr[li]], cjk)
            if rows:
                step = (e - s) / len(rows)
                toks = [
                    AlignedToken(r[1], s + k * step, s + (k + 1) * step, None)
                    for k, r in enumerate(rows)
                ]
                if cjk:
                    toks = _explode_cjk(toks)
                ps = [wh[j][3] for j in seg[u1 : u2 + 1]]
                aligned.append(
                    AlignedLine(
                        text=lyr[li],
                        start=round(s, 3),
                        end=round(e, 3),
                        tokens=toks,
                        score=round(sum(ps) / len(ps), 4) if ps else None,
                        alignment="aligned",
                    )
                )
                covered.append((s, e))
        # Whatever surrounds the matched window may hold more lines.
        _emit(seg[:u1], depth + 1)
        _emit(seg[u2 + 1 :], depth + 1)

    seg: list[int] = []
    for j in range(len(wh)):
        if j in used_j:
            _emit(seg, 0)
            seg = []
            continue
        if seg and wh[j][1] - wh[seg[-1]][2] > 1.5:
            _emit(seg, 0)
            seg = []
        seg.append(j)
    _emit(seg, 0)


def align_lyrics(
    audio_path: Path,
    lines: list[str],
    language: str | None,
    anchors: list[float | None] | None = None,
) -> tuple[list[AlignedLine], float]:
    """Blocking (call from a worker thread). Returns (aligned lines, overall
    confidence 0-1).

    Transcription-based alignment is tried first for every language (downloaded
    text + Whisper timing, word-level for space-delimited languages, char-level
    for CJK, trimmed to the audio). stable-ts forced alignment is the fallback
    when transcription yields no usable anchors.
    """
    _load_model()  # surfaces AlignmentUnavailable early if ML deps are missing
    try:
        aligned, confidence = _align_by_transcription(audio_path, lines, language, anchors)
    except Exception:  # noqa: BLE001 - never let timing fall over the pipeline
        log.exception("transcription alignment failed; using forced alignment")
        aligned, confidence = [], 0.0
    if aligned:
        return aligned, confidence
    log.warning("transcription alignment produced nothing; using forced alignment")

    return _align_forced(audio_path, lines, language, anchors)
