from karaoke_server.lyrics.lrc import parse_lrc, plain_lines


def test_parse_basic():
    raw = "[ti:Song]\n[00:12.50]hello world\n[01:02.03]second line\n"
    lines = parse_lrc(raw)
    assert len(lines) == 2
    assert abs(lines[0].time - 12.5) < 1e-6
    assert lines[0].text == "hello world"
    assert abs(lines[1].time - 62.03) < 1e-6


def test_parse_multiple_stamps_per_line():
    raw = "[00:10.00][00:50.00]chorus text"
    lines = parse_lrc(raw)
    assert [round(line.time) for line in lines] == [10, 50]
    assert all(line.text == "chorus text" for line in lines)


def test_parse_offset_and_word_tags():
    raw = "[offset:+1000]\n[00:10.00]<00:10.00>a<00:10.50>b<00:11.00>"
    lines = parse_lrc(raw)
    assert len(lines) == 1
    assert abs(lines[0].time - 9.0) < 1e-6
    assert lines[0].text == "ab"


def test_meta_lines_skipped():
    assert parse_lrc("[ar:Artist]\n[al:Album]") == []


def test_plain_lines_drops_section_markers():
    text = "line one\n\n[Chorus]\n（間奏）\nline two"
    assert plain_lines(text) == ["line one", "line two"]
