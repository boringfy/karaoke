from karaoke_server.subtitles.exporters import to_ass, to_enhanced_lrc, to_lrc, to_srt
from karaoke_server.subtitles.schema import Line, SubtitleDoc, Token


def _doc():
    return SubtitleDoc(
        lang="ja",
        title="Test",
        artist="Singer",
        lines=[
            Line(
                id="L0",
                start=10.0,
                end=13.0,
                text="君の歌",
                tokens=[
                    Token(text="君", ruby="きみ", start=10.0, end=11.0, p=0.9),
                    Token(text="の", start=11.0, end=11.5, p=0.95),
                    Token(text="歌", ruby="うた", start=11.5, end=13.0, p=0.8),
                ],
            ),
            Line(id="L1", start=15.0, end=17.0, text="la la la", tokens=[]),
        ],
    )


def test_lrc():
    out = to_lrc(_doc())
    assert "[ti:Test]" in out
    assert "[00:10.00]君の歌" in out
    assert "[00:15.00]la la la" in out


def test_enhanced_lrc_word_tags():
    out = to_enhanced_lrc(_doc())
    assert "[00:10.00]<00:10.00>君<00:11.00>の<00:11.50>歌<00:13.00>" in out


def test_srt():
    out = to_srt(_doc())
    assert "00:00:10,000 --> 00:00:13,000" in out
    assert "君の歌" in out


def test_ass_karaoke_and_furigana():
    out = to_ass(_doc())
    # main karaoke line with per-token \k centisecond durations
    assert "{\\k100}君{\\k50}の{\\k150}歌" in out
    # furigana layer present, readings aligned over kanji
    assert "Furi" in out
    assert "きみ" in out and "うた" in out


def test_json_roundtrip():
    doc = _doc()
    raw = doc.dump_json()
    back = SubtitleDoc.load_json(raw)
    assert back.lines[0].tokens[0].ruby == "きみ"
    assert back.schema_version == 1
    assert '"schema"' in raw
