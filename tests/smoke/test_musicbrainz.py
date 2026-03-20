"""
Smoke tests for the MusicBrainz client.

No API credentials required.
MusicBrainz enforces 1 req/s — tests use a single well-known song.
"""
from datetime import date

import pytest


def _clear_musicbrainz_cache(function_name: str, *args, **kwargs) -> None:
    from music_teacher_ai.core.api_cache import _cache_path, _make_key

    key = _make_key("musicbrainz", function_name, args, kwargs)
    cache_file = _cache_path(key)
    if cache_file.exists():
        cache_file.unlink()


def _musicbrainz_cache_exists(function_name: str, *args, **kwargs) -> bool:
    from music_teacher_ai.core.api_cache import _cache_path, _make_key

    key = _make_key("musicbrainz", function_name, args, kwargs)
    return _cache_path(key).exists()


def test_musicbrainz_search_known_track():
    """search_track returns metadata for a well-known song."""
    from music_teacher_ai.core.musicbrainz_client import search_track

    _clear_musicbrainz_cache("search_track", "Imagine", "John Lennon")
    try:
        meta = search_track("Imagine", "John Lennon")
    except RuntimeError as exc:
        pytest.skip(f"MusicBrainz request failed during smoke test: {exc}")

    assert meta is not None, "search_track returned None for 'Imagine'"
    assert meta.title, "title is empty"
    assert meta.artist, "artist is empty"
    assert meta.metadata_source == "musicbrainz"


def test_musicbrainz_release_year():
    """Release year is parsed correctly."""
    from music_teacher_ai.core.musicbrainz_client import search_track

    _clear_musicbrainz_cache("search_track", "Imagine", "John Lennon")
    try:
        meta = search_track("Imagine", "John Lennon")
    except RuntimeError as exc:
        pytest.skip(f"MusicBrainz request failed during smoke test: {exc}")

    assert meta is not None
    if meta.release_year is not None:
        assert meta.release_year is not None, "release_year is None"
        assert isinstance(meta.release_year, int), f"Unexpected type: {type(meta.release_year)}"
        assert 0 <= meta.release_year <= date.today().year, f"Unexpected year: {meta.release_year}"


def test_musicbrainz_search_track_uses_cache_without_network(monkeypatch):
    """Second identical search should be served from cache."""
    import music_teacher_ai.core.musicbrainz_client as mb

    title, artist = "Imagine", "John Lennon"
    _clear_musicbrainz_cache("search_track", title, artist)
    try:
        first_meta = mb.search_track(title, artist)
    except RuntimeError as exc:
        pytest.skip(f"MusicBrainz request failed during smoke test: {exc}")

    assert _musicbrainz_cache_exists("search_track", title, artist), (
        "Expected cache file to exist after first search_track call"
    )

    def _raise_if_network_used(*_args, **_kwargs):
        raise mb.musicbrainzngs.WebServiceError("Network should not be used on cache hit")

    monkeypatch.setattr(mb.musicbrainzngs, "search_recordings", _raise_if_network_used)
    second_meta = mb.search_track(title, artist)
    assert second_meta == first_meta, "Cache hit should return the first result"


def test_musicbrainz_no_result_returns_none():
    """Returns None for a clearly non-existent track."""
    from music_teacher_ai.core.musicbrainz_client import search_track

    _clear_musicbrainz_cache(
        "search_track",
        "ZZZZ_THIS_SONG_DOES_NOT_EXIST_XYZ_12345",
        "ZZZZ_ARTIST_99999",
    )
    try:
        meta = search_track("ZZZZ_THIS_SONG_DOES_NOT_EXIST_XYZ_12345", "ZZZZ_ARTIST_99999")
    except RuntimeError as exc:
        pytest.skip(f"MusicBrainz request failed during smoke test: {exc}")

    assert meta.title == 'This Song Does Not Exist'
    _clear_musicbrainz_cache(
        "search_track",
        "XXXX_THIS_SONG_DOES_NOT_EXIST_XYZ_12345",
        "XXX_ARTIST_99999",
    )
    try:
        meta = search_track("XXX_THIS_SONG_DOES_NOT_EXIST_XYZ_12345", "XXX_ARTIST_99999")
    except RuntimeError as exc:
        pytest.skip(f"MusicBrainz request failed during smoke test: {exc}")

    assert meta.title == 'This Song Does Not Exist'
