from karaoke_server.lyrics.language import detect_language, latin_ratio


def test_english():
    assert detect_language("Hello darkness my old friend") == "en"


def test_chinese():
    assert detect_language("月亮代表我的心 你问我爱你有多深") == "zh"


def test_japanese_kana():
    assert detect_language("君の名前を呼ぶよ さよならの向こうへ") == "ja"


def test_japanese_mostly_kanji_with_kana():
    assert detect_language("桜舞い散る中に忘れた記憶と") == "ja"


def test_empty():
    assert detect_language("   ") == "unknown"


def test_latin_ratio_flags_romanization():
    assert latin_ratio("kimi no na wa boku no kioku") > 0.8
    assert latin_ratio("君の名は") == 0.0
