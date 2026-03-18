"""
Smoke tests for the MusicBrainz client.

No API credentials required.
MusicBrainz enforces 1 req/s — tests use a single well-known song.
"""


def test_musicbrainz_search_known_track():
    """search_track returns metadata for a well-known song."""
    from music_teacher_ai.core.musicbrainz_client import search_track

    meta = search_track("Imagine", "John Lennon")

    assert meta is not None, "search_track returned None for 'Imagine'"
    assert meta.title, "title is empty"
    assert meta.artist, "artist is empty"
    assert meta.metadata_source == "musicbrainz"


def test_musicbrainz_release_year():
    """Release year is parsed correctly."""
    from music_teacher_ai.core.musicbrainz_client import search_track

    meta = search_track("Imagine", "John Lennon")
    assert meta is not None
    if meta.release_year is not None:
        assert 1970 <= meta.release_year <= 1973, f"Unexpected year: {meta.release_year}"


def test_musicbrainz_no_result_returns_none():
    """Returns None for a clearly non-existent track."""
    from music_teacher_ai.core.musicbrainz_client import search_track

    meta = search_track("ZZZZ_THIS_SONG_DOES_NOT_EXIST_XYZ_12345", "ZZZZ_ARTIST_99999")
    assert meta is None
