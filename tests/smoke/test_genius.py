"""
Smoke tests for the Genius lyrics client.

Verifies:
- Lyrics can be fetched for a well-known song
- Normalization removes section headers and excess whitespace
- Word count is non-trivial (real lyrics, not empty/stub)
- fetch_lyrics returns None gracefully for unknown songs
"""
from tests.smoke.conftest import requires_genius


@requires_genius
def test_genius_fetch_known_song():
    """fetch_lyrics returns non-empty text for a well-known song."""
    from music_teacher_ai.core.lyrics_client import fetch_lyrics

    lyrics = fetch_lyrics("Imagine", "John Lennon")

    assert lyrics is not None, "fetch_lyrics returned None for 'Imagine'"
    assert len(lyrics) > 100, f"Lyrics suspiciously short ({len(lyrics)} chars)"


@requires_genius
def test_genius_normalization_removes_headers():
    """Normalized lyrics do not contain section headers like [Chorus]."""
    from music_teacher_ai.core.lyrics_client import fetch_lyrics

    lyrics = fetch_lyrics("Imagine", "John Lennon")
    assert lyrics is not None

    assert "[Chorus]" not in lyrics, "Section header [Chorus] was not removed"
    assert "[Verse" not in lyrics, "Section header [Verse] was not removed"


@requires_genius
def test_genius_word_count():
    """Fetched lyrics contain a reasonable number of words."""
    import re

    from music_teacher_ai.core.lyrics_client import fetch_lyrics

    lyrics = fetch_lyrics("Imagine", "John Lennon")
    assert lyrics is not None

    words = re.findall(r"\b\w+\b", lyrics)
    assert len(words) >= 50, f"Word count too low: {len(words)}"


@requires_genius
def test_genius_no_result_returns_none():
    """fetch_lyrics returns None for a clearly non-existent song."""
    from music_teacher_ai.core.lyrics_client import fetch_lyrics

    result = fetch_lyrics(
        "ZZZZ_THIS_SONG_DOES_NOT_EXIST_XYZ_12345",
        "ZZZZ_ARTIST_XYZ_99999",
    )
    assert result is None, "Expected None for non-existent song"


def test_normalize_lyrics_standalone():
    """normalize_lyrics works correctly without any API call."""
    from music_teacher_ai.core.lyrics_client import normalize_lyrics

    raw = "[Verse 1]\nImagine there's no heaven\n[Chorus]\nYou may say I'm a dreamer\n\n\n\n"
    result = normalize_lyrics(raw)

    assert "[Verse 1]" not in result
    assert "[Chorus]" not in result
    assert "Imagine there's no heaven" in result
    assert not result.endswith("\n")
