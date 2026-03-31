"""
Unit tests for music_teacher_ai/pipeline/lyrics_downloader.py.
No database or real Genius API required.
"""

from unittest.mock import patch

# ---------------------------------------------------------------------------
# _is_rate_limit()
# ---------------------------------------------------------------------------


def test_is_rate_limit_429():
    from music_teacher_ai.pipeline.lyrics_downloader import _is_rate_limit

    assert _is_rate_limit(Exception("HTTP 429 Too Many Requests")) is True


def test_is_rate_limit_too_many():
    from music_teacher_ai.pipeline.lyrics_downloader import _is_rate_limit

    assert _is_rate_limit(Exception("too many requests from this IP")) is True


def test_is_rate_limit_rate_limit_text():
    from music_teacher_ai.pipeline.lyrics_downloader import _is_rate_limit

    assert _is_rate_limit(Exception("rate limit exceeded")) is True


def test_is_rate_limit_case_insensitive():
    from music_teacher_ai.pipeline.lyrics_downloader import _is_rate_limit

    assert _is_rate_limit(Exception("RATE LIMIT hit")) is True
    assert _is_rate_limit(Exception("TOO MANY requests")) is True


def test_is_rate_limit_generic_error():
    from music_teacher_ai.pipeline.lyrics_downloader import _is_rate_limit

    assert _is_rate_limit(Exception("Connection timeout")) is False


def test_is_rate_limit_404():
    from music_teacher_ai.pipeline.lyrics_downloader import _is_rate_limit

    assert _is_rate_limit(Exception("404 Not Found")) is False


# ---------------------------------------------------------------------------
# _fetch_one() — via mocked fetch_lyrics
# ---------------------------------------------------------------------------


def test_fetch_one_ok():
    from music_teacher_ai.pipeline.lyrics_downloader import _fetch_one

    with patch(
        "music_teacher_ai.pipeline.lyrics_downloader.fetch_lyrics", return_value="some lyrics text"
    ):
        status, data = _fetch_one("Imagine", "John Lennon")
    assert status == "ok"
    assert data == "some lyrics text"


def test_fetch_one_not_found_when_empty():
    from music_teacher_ai.pipeline.lyrics_downloader import _fetch_one

    with patch("music_teacher_ai.pipeline.lyrics_downloader.fetch_lyrics", return_value=None):
        status, data = _fetch_one("Unknown Song", "Unknown Artist")
    assert status == "not_found"
    assert data is None


def test_fetch_one_not_found_when_empty_string():
    from music_teacher_ai.pipeline.lyrics_downloader import _fetch_one

    with patch("music_teacher_ai.pipeline.lyrics_downloader.fetch_lyrics", return_value=""):
        status, data = _fetch_one("Ghost Song", "Nobody")
    assert status == "not_found"
    assert data is None


def test_fetch_one_rate_limit():
    from music_teacher_ai.pipeline.lyrics_downloader import _fetch_one

    with patch(
        "music_teacher_ai.pipeline.lyrics_downloader.fetch_lyrics",
        side_effect=Exception("429 Too Many Requests"),
    ):
        status, data = _fetch_one("Song", "Artist")
    assert status == "rate_limit"
    assert "429" in data


def test_fetch_one_generic_error():
    from music_teacher_ai.pipeline.lyrics_downloader import _fetch_one

    with patch(
        "music_teacher_ai.pipeline.lyrics_downloader.fetch_lyrics",
        side_effect=Exception("Connection refused"),
    ):
        status, data = _fetch_one("Song", "Artist")
    assert status == "error"
    assert "Connection refused" in data


# ---------------------------------------------------------------------------
# _count_words()
# ---------------------------------------------------------------------------


def test_count_words_basic():
    from music_teacher_ai.pipeline.lyrics_downloader import _count_words

    total, unique = _count_words("hello world hello")
    assert total == 3
    assert unique == 2


def test_count_words_empty():
    from music_teacher_ai.pipeline.lyrics_downloader import _count_words

    total, unique = _count_words("")
    assert total == 0
    assert unique == 0


def test_count_words_case_insensitive():
    from music_teacher_ai.pipeline.lyrics_downloader import _count_words

    total, unique = _count_words("Hello HELLO hello")
    assert total == 3
    assert unique == 1


def test_count_words_with_apostrophe():
    from music_teacher_ai.pipeline.lyrics_downloader import _count_words

    total, unique = _count_words("I don't care")
    # "don't" counts as one word with apostrophe
    assert total >= 2
