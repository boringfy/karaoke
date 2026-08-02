from karaoke_server.subtitles.furigana import has_kanji, ruby_segments


def _joined(segs):
    return "".join(s.text for s in segs)


def test_okurigana_trimmed():
    segs = ruby_segments("走る")
    assert _joined(segs) == "走る"
    kanji = [s for s in segs if s.ruby]
    assert len(kanji) == 1
    assert kanji[0].text == "走"
    assert kanji[0].ruby == "はし"


def test_interior_kana_split():
    segs = ruby_segments("打ち合わせ")
    assert _joined(segs) == "打ち合わせ"
    readings = {s.text: s.ruby for s in segs if s.ruby}
    assert readings.get("打") == "う"
    assert readings.get("合") == "あ"


def test_pure_kana_no_ruby():
    segs = ruby_segments("さよなら")
    assert all(s.ruby is None for s in segs)


def test_katakana_loanword_no_ruby():
    segs = ruby_segments("ギターを弾く")
    assert _joined(segs) == "ギターを弾く"
    with_ruby = [s for s in segs if s.ruby]
    assert [s.text for s in with_ruby] == ["弾"]
    assert with_ruby[0].ruby == "ひ"


def test_number_compound():
    segs = ruby_segments("一人で歌う")
    assert _joined(segs) == "一人で歌う"
    assert any(s.ruby for s in segs)


def test_every_kanji_gets_ruby():
    text = "君の名前を呼ぶ夜空の星"
    segs = ruby_segments(text)
    assert _joined(segs) == text
    for seg in segs:
        if has_kanji(seg.text):
            assert seg.ruby, f"kanji segment {seg.text!r} missing ruby"


def test_mixed_sentence_reconstructs():
    text = "明日はライブ、心の準備OK？"
    assert _joined(ruby_segments(text)) == text
