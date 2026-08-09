"""Unit tests for transcription-transfer alignment (word and char mode) and
the interpolation/sanity fallbacks. Everything under test is pure Python; the
Whisper boundary (_transcribe_units / _load_model) is monkeypatched."""

from pathlib import Path

from karaoke_server.align import whisper_align as wa

AUDIO = Path("unused.wav")


def _spread(chars: list[str], start: float, end: float, p: float = 0.9):
    """Fake transcript units: chars spread evenly over [start, end]."""
    step = (end - start) / len(chars)
    return [
        (c, round(start + i * step, 3), round(start + (i + 1) * step, 3), p)
        for i, c in enumerate(chars)
    ]


def _norm_chars(text: str) -> list[str]:
    return [c for c in (wa._norm_char(ch) for ch in text) if c]


# --------------------------------------------------------------------- _norm_char

def test_norm_char_folds_and_drops():
    assert wa._norm_char("カ") == "か"
    assert wa._norm_char("ヴ") == "ゔ"
    assert wa._norm_char("Ａ") == "a"  # NFKC full-width
    assert wa._norm_char("ー") == "ー"  # prolonged sound mark preserved
    assert wa._norm_char("、") == ""
    assert wa._norm_char("。") == ""
    assert wa._norm_char(" ") == ""
    assert wa._norm_char("　") == ""


# ------------------------------------------- char-mode transcription transfer

JA_LINES = [
    "歌に託してサヨナラ 誰も知らない恋の歌",
    "傘ならもういらない",
]


def test_char_mode_line_end_ignores_melisma(monkeypatch):
    # Line 0 sung 10-19s, then a long held ~~~ahh (not in the lyrics) until
    # 25s, line 1 sung 35-43s. The line must end when its last char is sung.
    units = (
        _spread(_norm_chars(JA_LINES[0]), 10.0, 19.0)
        + _spread(["あ"] * 6, 19.0, 25.0)  # melisma: transcript-only insert
        + _spread(_norm_chars(JA_LINES[1]), 35.0, 43.0)
    )
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, confidence = wa._align_by_transcription(AUDIO, JA_LINES, "ja")

    assert [ln.text for ln in aligned] == JA_LINES
    assert aligned[0].alignment == "aligned"
    assert abs(aligned[0].start - 10.0) < 0.1
    assert abs(aligned[0].end - 19.0) < 0.1  # not 25.0, not 35.0
    assert abs(aligned[1].start - 35.0) < 0.1
    assert confidence > 0.8
    # Real anchors carry probabilities.
    assert all(t.p is not None for t in aligned[0].tokens)
    # Tokens reconstruct the line text minus spaces (furigana-pool invariant).
    assert "".join(t.text for t in aligned[0].tokens) == JA_LINES[0].replace(" ", "")


def test_char_mode_katakana_lyric_anchors_hiragana_transcript(monkeypatch):
    lines = ["サヨナラだけが人生だ"]
    # Whisper "heard" hiragana where the lyric uses katakana.
    units = _spread(_norm_chars("さよならだけが人生だ"), 5.0, 9.0)
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")
    assert len(aligned) == 1 and aligned[0].alignment == "aligned"
    assert abs(aligned[0].start - 5.0) < 0.1
    assert aligned[0].tokens[0].text == "サ"  # original text preserved


def test_char_mode_keeps_punctuation_tokens(monkeypatch):
    lines = ["だから、昨日よりもずっと"]
    units = _spread(_norm_chars(lines[0]), 3.0, 8.0)
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")
    texts = [t.text for t in aligned[0].tokens]
    assert "、" in texts  # unmatched but present, with interpolated timing
    tok = aligned[0].tokens[texts.index("、")]
    assert 3.0 <= tok.start <= tok.end <= 8.0


def test_char_mode_unanchored_run_interpolates_locally(monkeypatch):
    line = "歌に託してサヨナラ誰も知らない"
    chars = _norm_chars(line)
    units = _spread(chars, 10.0, 17.0)
    # Whisper missed 4 chars in the middle (indices 5-8).
    missing = set(range(5, 9))
    units = [u for i, u in enumerate(units) if i not in missing]
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, [line], "ja")
    toks = aligned[0].tokens
    # The gap chars sit between their anchored neighbors, not spread elsewhere.
    for i in missing:
        assert toks[4].start <= toks[i].start <= toks[9].end + 0.01
    assert abs(aligned[0].end - 17.0) < 0.1


def test_char_mode_trims_unsung_tail_lines(monkeypatch):
    lines = ["歌に託してサヨナラ", "誰も知らない恋の歌", "届かない未来のこと", "終わらない夜の話"]
    units = _spread(_norm_chars(lines[0]), 1.0, 4.0) + _spread(
        _norm_chars(lines[1]), 5.0, 8.0
    )
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")
    assert [ln.text for ln in aligned] == lines[:2]


# ------------------------------------------------------- word-mode regression

def test_word_mode_still_anchors(monkeypatch):
    lines = ["fly me to the moon", "let me play among the stars"]
    words1 = [wa._norm_word(w) for w in lines[0].split()]
    words2 = [wa._norm_word(w) for w in lines[1].split()]
    units = _spread(words1, 12.0, 15.0) + _spread(words2, 18.0, 21.5)
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, confidence = wa._align_by_transcription(AUDIO, lines, "en")
    assert [ln.text for ln in aligned] == lines
    assert abs(aligned[0].start - 12.0) < 0.01
    assert abs(aligned[0].end - 15.0) < 0.01
    assert abs(aligned[1].end - 21.5) < 0.01
    assert confidence > 0.8
    assert [t.text for t in aligned[0].tokens] == lines[0].split()


# ------------------------------------------------------- _interpolate_failed

def _failed_line(text: str) -> wa.AlignedLine:
    toks = [wa.AlignedToken(c, 0.0, 0.0) for c in text]
    return wa.AlignedLine(text=text, start=0.0, end=0.0, tokens=toks, alignment="interpolated")


def test_interpolate_caps_token_spread_but_keeps_window():
    line = _failed_line("あ" * 23)
    wa._interpolate_failed([line], [100.0, 125.1], cjk=True)
    assert line.start == 100.0
    assert line.end == 125.1  # display window untouched
    est = 23 / wa.INTERP_CJK_RATE  # 9.2s of singing, not 25.1
    assert abs(line.tokens[-1].end - (100.0 + est)) < 0.01
    # Tokens are contiguous and even.
    assert abs(line.tokens[0].start - 100.0) < 0.01


def test_interpolate_floor_and_word_rate():
    short = _failed_line("あい")
    wa._interpolate_failed([short], [10.0, 40.0], cjk=True)
    assert abs(short.tokens[-1].end - 12.0) < 0.01  # 2s floor

    en = wa.AlignedLine(
        text="w " * 10,
        start=0.0,
        end=0.0,
        tokens=[wa.AlignedToken("w", 0.0, 0.0) for _ in range(10)],
        alignment="interpolated",
    )
    wa._interpolate_failed([en], [10.0, 40.0], cjk=False)
    assert abs(en.tokens[-1].end - (10.0 + 10 / wa.INTERP_WORD_RATE)) < 0.01


def test_interpolate_short_window_unchanged():
    # Window smaller than the estimate: spread across the whole window.
    line = _failed_line("あ" * 20)
    wa._interpolate_failed([line], [10.0, 14.0], cjk=True)
    assert abs(line.tokens[-1].end - 14.0) < 0.01


# ----------------------------------------------------------------- _line_ok

def test_line_ok_uses_token_span_not_segment_window():
    toks = [wa.AlignedToken("あ", 1.0 + i * 0.5, 1.5 + i * 0.5, 0.9) for i in range(8)]
    # Segment window inflated to 20s by a trailing melisma the aligner absorbed.
    line = wa.AlignedLine(text="あ" * 8, start=0.0, end=20.0, tokens=toks, score=0.9)
    assert wa._line_ok(line, cjk=True, threshold=0.45)


def test_line_ok_still_rejects_bad_lines():
    empty = wa.AlignedLine(text="x", start=0.0, end=5.0, tokens=[], score=0.9)
    assert not wa._line_ok(empty, cjk=True, threshold=0.45)
    zero_span = wa.AlignedLine(
        text="x", start=0.0, end=5.0, tokens=[wa.AlignedToken("x", 2.0, 2.0)], score=0.9
    )
    assert not wa._line_ok(zero_span, cjk=True, threshold=0.45)
    low_score = wa.AlignedLine(
        text="x",
        start=0.0,
        end=5.0,
        tokens=[wa.AlignedToken("x", 0.0, 1.0)],
        score=0.1,
    )
    assert not wa._line_ok(low_score, cjk=True, threshold=0.45)


# --------------------------------------------------------- _cap_final_token

def test_cap_final_token_trims_absorbed_silence():
    toks = [wa.AlignedToken("あ", i * 0.3, (i + 1) * 0.3, 0.9) for i in range(10)]
    toks[-1].end = toks[-1].start + 10.0  # aligner absorbed 10s of tail
    wa._cap_final_token(toks)
    assert abs(toks[-1].end - (toks[-1].start + 1.0)) < 0.01  # max(1.0, 3*0.3)


def test_cap_final_token_keeps_real_holds():
    toks = [wa.AlignedToken("あ", i * 1.0, (i + 1) * 1.0, 0.9) for i in range(6)]
    toks[-1].end = toks[-1].start + 2.5  # genuinely held note
    wa._cap_final_token(toks)
    assert abs(toks[-1].end - (toks[-1].start + 2.5)) < 0.01


# ------------------------------------------------------------ align_lyrics routing

def test_align_lyrics_falls_back_to_forced(monkeypatch):
    monkeypatch.setattr(wa, "_load_model", lambda: None)
    monkeypatch.setattr(wa, "_align_by_transcription", lambda *a: ([], 0.0))
    sentinel = ([wa.AlignedLine(text="x", start=0.0, end=1.0)], 0.5)
    monkeypatch.setattr(wa, "_align_forced", lambda *a, **k: sentinel)
    assert wa.align_lyrics(AUDIO, ["x"], "ja") == sentinel


def test_align_lyrics_prefers_transcription(monkeypatch):
    monkeypatch.setattr(wa, "_load_model", lambda: None)
    good = ([wa.AlignedLine(text="x", start=0.0, end=1.0)], 0.9)
    monkeypatch.setattr(wa, "_align_by_transcription", lambda *a: good)

    def _boom(*a, **k):
        raise AssertionError("forced alignment must not run")

    monkeypatch.setattr(wa, "_align_forced", _boom)
    assert wa.align_lyrics(AUDIO, ["x"], "ja") == good


# ------------------------------------------------- out-of-order recovery pass

def test_recovers_chorus_sung_before_verses(monkeypatch):
    """A TV edit opens with the chorus (last line of the full lyrics) before
    verse 1. The monotonic pass can't anchor it; the recovery pass must
    re-emit the chorus line at its real (early) time — and keep the later,
    in-order copy too."""
    lines = [
        "うぶ毛の小鳥たちも",
        "いつか空に羽ばたく",
        "大きな強い翼で飛ぶ",
        "はしれはしれスタートダッシュ",  # chorus, sung both first and last
    ]
    units = (
        _spread(_norm_chars(lines[3]), 0.0, 5.0)      # opening chorus (reordered)
        + _spread(_norm_chars(lines[0]), 10.0, 15.0)
        + _spread(_norm_chars(lines[1]), 16.0, 21.0)
        + _spread(_norm_chars(lines[2]), 22.0, 27.0)
        + _spread(_norm_chars(lines[3]), 30.0, 35.0)  # finale chorus (in order)
    )
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")

    texts = [ln.text for ln in aligned]
    assert texts.count(lines[3]) == 2, texts
    # sorted by time: chorus first, then the verses, chorus again
    assert texts[0] == lines[3]
    assert aligned[0].start < 6.0 and aligned[0].end <= 6.0
    assert texts[1:4] == lines[:3]
    assert aligned[-1].start >= 29.0


def test_recovery_ignores_hallucinated_tail(monkeypatch):
    """Unconsumed transcript that matches no lyric line well must NOT create
    subtitle lines (e.g. hallucinated 'thank you' after the song ends)."""
    lines = ["うぶ毛の小鳥たちも", "いつか空に羽ばたく"]
    units = (
        _spread(_norm_chars(lines[0]), 0.0, 5.0)
        + _spread(_norm_chars(lines[1]), 6.0, 11.0)
        + _spread(_norm_chars("ご視聴ありがとうございました"), 20.0, 24.0)
    )
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")

    assert [ln.text for ln in aligned] == lines
    assert aligned[-1].end < 12.0


# ------------------------------------------------ simplified-glyph conversion

def test_to_japanese_kanji_fixes_simplified_and_kyujitai():
    from karaoke_server.lyrics.script import to_japanese_kanji

    src = "热い胸　きっと未来を切り开く筈さ"
    assert to_japanese_kanji(src) == "熱い胸　きっと未来を切り開く筈さ"
    assert to_japanese_kanji("その日が绝対来る") == "その日が絶対来る"
    assert to_japanese_kanji("大きな强い翼で飛ぶ") == "大きな強い翼で飛ぶ"
    assert to_japanese_kanji("谛めちゃダメなんだ") == "諦めちゃダメなんだ"
    # already-Japanese text is untouched (incl. kana, length preserved)
    ja = "うぶ毛の小鳥たちも Hey!"
    assert to_japanese_kanji(ja) == ja


def test_zh_traditional_transcript_anchors_simplified_lyrics(monkeypatch):
    """Whisper may emit Traditional forms against Simplified lyrics; the
    matching fold must let them anchor (不讀三國 vs 不读三国)."""
    lines = ["不是英雄 不读三国", "若是英雄 怎么能不懂寂寞"]
    units = (
        _spread(_norm_chars("不是英雄不讀三國"), 26.8, 31.5)
        + _spread(_norm_chars("若是英雄怎麼能不懂寂寞"), 33.5, 39.7)
    )
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, conf = wa._align_by_transcription(AUDIO, lines, "zh")

    assert [ln.text for ln in aligned] == lines
    assert abs(aligned[0].start - 26.8) < 0.2
    assert conf > 0.8


# ---------------------------------------------------- LRC-anchor last resort

def test_unheard_line_recovered_from_lrc_anchor(monkeypatch):
    """A line ASR cannot hear at all (spoken hook Whisper hallucinates over)
    must still appear at its synced-LRC time when that window is uncovered."""
    lines = ["不是英雄 不读三国", "若是英雄 怎么能不懂寂寞"]
    anchors = [26.8, 33.5]
    # Transcript only contains line 2.
    units = _spread(_norm_chars(lines[1]), 33.5, 39.7)
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "zh", anchors)

    assert [ln.text for ln in aligned] == lines
    assert abs(aligned[0].start - 26.8) < 0.01
    assert aligned[0].alignment == "interpolated"
    assert aligned[1].alignment == "aligned"


def test_anchor_recovery_rejects_mismatched_lrc_timeline(monkeypatch):
    """Full-song LRC anchors over a short clip must be rejected wholesale —
    their timeline doesn't describe this recording."""
    lines = ["うぶ毛の小鳥たちも", "いつか空に羽ばたく"]
    anchors = [10.0, 200.0]  # anchor far beyond anything covered
    units = _spread(_norm_chars(lines[0]), 20.0, 25.0)
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja", anchors)

    assert [ln.text for ln in aligned] == [lines[0]]  # no anchor emissions


def test_producer_credit_lines_are_filtered(monkeypatch):
    lines = ["制作人 : 吴剑泓", "不是英雄 不读三国"]
    units = _spread(_norm_chars(lines[1]), 26.8, 31.5)
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "zh", [2.2, 26.8])
    assert [ln.text for ln in aligned] == [lines[1]]


# --------------------------------------------- VAD-aware gap interpolation

def test_place_in_speech_skips_instrumental_break():
    """Un-anchored units must land on the sung part of the window, not be
    smeared across an instrumental break (words on screen during silence)."""
    # Window 100-160s; the singer is only active 140-160s.
    placed = wa._place_in_speech(100.0, 160.0, 4, ((140.0, 160.0),))
    assert all(s >= 139.9 for s, _ in placed), placed
    assert placed[0][0] < placed[-1][0]  # still in order
    assert placed[-1][1] <= 160.01


def test_place_in_speech_spans_two_stretches():
    """With singing on both sides of a break, units distribute over the sung
    time and skip the middle."""
    placed = wa._place_in_speech(0.0, 100.0, 4, ((0.0, 10.0), (90.0, 100.0)))
    inside_break = [s for s, _ in placed if 12.0 < s < 88.0]
    assert not inside_break, placed


def test_place_in_speech_falls_back_without_vad():
    """No VAD data (or silent window): keep the previous even spread."""
    placed = wa._place_in_speech(0.0, 10.0, 2, ())
    assert len(placed) == 2
    assert 0.0 <= placed[0][0] < placed[1][0] <= 10.0


def test_unheard_line_is_marked_interpolated(monkeypatch):
    """A line no unit of which anchored must not claim 'aligned' trust."""
    lines = ["きこえる声", "とどかない言葉"]
    units = _spread(_norm_chars(lines[0]), 10.0, 15.0)  # only line 0 is heard
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: units)
    monkeypatch.setattr(wa, "_speech_regions", lambda p: ((10.0, 15.0),))
    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")
    by_text = {ln.text: ln for ln in aligned}
    assert by_text[lines[0]].alignment == "aligned"
    if lines[1] in by_text:
        assert by_text[lines[1]].alignment == "interpolated"


def test_gap_recovery_measures_heard_coverage_not_guesses(monkeypatch):
    """Interpolated guesses must not mask the hole they span: gap recovery
    re-decides those windows on evidence and supersedes them."""
    lines = ["きこえるこえ", "とどかないことば", "むねのおくで", "ひびいている"]
    # Main pass hears only the first and last line (a long break between).
    main = (
        _spread(_norm_chars(lines[0]), 5.0, 10.0)
        + _spread(_norm_chars(lines[3]), 60.0, 65.0)
    )
    monkeypatch.setattr(wa, "_transcribe_units", lambda *a: main)
    monkeypatch.setattr(wa, "_speech_regions", lambda p: ((5.0, 10.0), (60.0, 65.0)))
    monkeypatch.setattr(wa.ffmpeg, "probe_duration", lambda p: 70.0)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    # Re-transcribing the gap DOES hear the two middle lines, late in it.
    def window(audio, lang, cjk, s, e):
        return (
            _spread(_norm_chars(lines[1]), 45.0, 50.0)
            + _spread(_norm_chars(lines[2]), 50.0, 55.0)
        )
    monkeypatch.setattr(wa, "_transcribe_window", window)

    aligned, _ = wa._align_by_transcription(AUDIO, lines, "ja")
    by_text = {ln.text: ln for ln in aligned}
    # The middle lines are placed where they were actually sung, not smeared
    # across the break starting right after line 0.
    assert by_text[lines[1]].start > 40.0, [(x.text, x.start) for x in aligned]
    assert by_text[lines[2]].start > 40.0
    # And no line is lost.
    assert set(by_text) == set(lines)


def test_transfer_timing_ignores_filler_units():
    """A run of consecutive lines must anchor precisely even when the window
    transcript is padded with filler the lyrics don't contain."""
    texts = ["きこえるこえ", "とどかないことば"]
    units = (
        _spread(["あ"] * 8, 100.0, 120.0)                      # filler ("aaah")
        + _spread(_norm_chars(texts[0]), 168.0, 173.0)
        + _spread(_norm_chars(texts[1]), 173.0, 179.0)
    )
    out = wa._transfer_timing(texts, units, True)
    assert [ln.text for ln in out] == texts
    assert abs(out[0].start - 168.0) < 0.3, out[0].start
    assert abs(out[1].end - 179.0) < 0.3
    assert all(ln.alignment == "aligned" for ln in out)


def test_transfer_timing_skips_unheard_lines():
    """Lines the window transcript doesn't contain are left for the caller."""
    texts = ["きこえるこえ", "ここにはないことば"]
    units = _spread(_norm_chars(texts[0]), 10.0, 15.0)
    out = wa._transfer_timing(texts, units, True)
    assert [ln.text for ln in out] == [texts[0]]
