"""Integration test for the furigana annotation stage: character-level aligned
tokens (as produced by align for Japanese) get regrouped into ruby segments
whose timings are inherited from the underlying characters."""

from karaoke_server.pipeline.stages import _apply_furigana
from karaoke_server.subtitles.exporters import to_ass, to_enhanced_lrc
from karaoke_server.subtitles.schema import Line, SubtitleDoc, Token


def _char_tokens(text: str, start: float, step: float = 0.3) -> list[Token]:
    """Simulate align's per-character output for CJK."""
    toks = []
    t = start
    for ch in text:
        toks.append(Token(text=ch, start=round(t, 2), end=round(t + step, 2), p=0.9))
        t += step
    return toks


def _doc() -> SubtitleDoc:
    text = "君の名前を呼ぶ"
    return SubtitleDoc(
        lang="ja",
        title="夜空",
        lines=[
            Line(id="L0", start=0.0, end=2.1, text=text, tokens=_char_tokens(text, 0.0)),
        ],
    )


def test_furigana_regroups_and_preserves_timing():
    doc = _doc()
    _apply_furigana(doc)
    line = doc.lines[0]

    # Reconstructed text must equal the original exactly.
    assert "".join(t.text for t in line.tokens) == "君の名前を呼ぶ"

    # Every kanji-bearing token carries a hiragana reading.
    by_text = {t.text: t for t in line.tokens}
    assert by_text["君"].ruby == "きみ"
    assert by_text["君"].ruby_source == "auto"
    assert by_text["名前"].ruby == "なまえ"
    # Kana tokens carry no ruby.
    assert by_text["の"].ruby is None

    # Merged tokens inherit start of first char and end of last char.
    assert by_text["名前"].start == 0.6  # 3rd char (index 2) * 0.3
    assert by_text["名前"].end == 1.2  # through 4th char


def test_annotated_doc_exports_cleanly():
    doc = _doc()
    _apply_furigana(doc)
    ass = to_ass(doc)
    assert "きみ" in ass and "なまえ" in ass
    assert "Furi" in ass
    # Enhanced LRC drops ruby but keeps word timing tags.
    elrc = to_enhanced_lrc(doc)
    assert "君" in elrc and "<00:00.00>" in elrc


def test_manual_ruby_preserved_on_reannotate():
    doc = _doc()
    _apply_furigana(doc)
    # User corrects a reading.
    for t in doc.lines[0].tokens:
        if t.text == "君":
            t.ruby = "きみさま"
            t.ruby_source = "manual"
    _apply_furigana(doc)
    by_text = {t.text: t for t in doc.lines[0].tokens}
    assert by_text["君"].ruby == "きみさま"
    assert by_text["君"].ruby_source == "manual"


def test_reannotate_is_idempotent():
    """Re-running annotation on already-merged tokens must not misalign
    multi-character kanji groups."""
    doc = _doc()
    _apply_furigana(doc)
    first = [(t.text, t.ruby, t.start, t.end) for t in doc.lines[0].tokens]
    _apply_furigana(doc)
    second = [(t.text, t.ruby, t.start, t.end) for t in doc.lines[0].tokens]
    assert first == second
    # 名前 still spans its two original characters (0.6 - 1.2).
    by_text = {t.text: t for t in doc.lines[0].tokens}
    assert by_text["名前"].ruby == "なまえ"
    assert (by_text["名前"].start, by_text["名前"].end) == (0.6, 1.2)
