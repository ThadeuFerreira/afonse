from music_teacher_ai.core.lyrics_client import normalize_lyrics


def test_removes_section_headers():
    raw = "[Chorus]\nNever gonna give you up\n[Verse]\nWe're no strangers to love"
    result = normalize_lyrics(raw)
    assert "[Chorus]" not in result
    assert "[Verse]" not in result
    assert "Never gonna give you up" in result


def test_strips_whitespace():
    raw = "\n\n\nHello\n\n\n\nWorld\n\n\n"
    result = normalize_lyrics(raw)
    assert not result.startswith("\n")
    assert not result.endswith("\n")


def test_normalizes_line_breaks():
    raw = "line one\r\nline two\rline three"
    result = normalize_lyrics(raw)
    assert "\r" not in result
