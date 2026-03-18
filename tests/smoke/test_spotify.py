"""
Smoke tests for the Spotify API client.

Verifies:
- Credentials are valid and authentication succeeds
- track search returns a result for a well-known song
- Audio features are returned for a valid track ID
- Artist genres are populated
"""
import pytest
from tests.smoke.conftest import requires_spotify


@requires_spotify
def test_spotify_authentication():
    """Client can authenticate with the provided credentials."""
    from music_teacher_ai.core.spotify_client import get_client
    sp = get_client()
    # A simple API call that requires valid auth
    result = sp.search(q="Imagine", type="track", limit=1)
    assert "tracks" in result, "Spotify response missing 'tracks' key"
    assert result["tracks"]["items"], "Spotify returned no tracks for 'Imagine'"


@requires_spotify
def test_spotify_search_known_track():
    """search_track() returns metadata for a well-known song."""
    from music_teacher_ai.core.spotify_client import search_track

    meta = search_track("Imagine", "John Lennon")

    assert meta is not None, "search_track returned None for 'Imagine' by John Lennon"
    assert meta.spotify_id, "spotify_id is empty"
    assert meta.title, "title is empty"
    assert meta.artist, "artist is empty"
    assert meta.release_year is not None, "release_year is None"
    assert 1970 <= meta.release_year <= 1972, f"Unexpected release year: {meta.release_year}"


@requires_spotify
def test_spotify_audio_features():
    """Audio features (tempo, energy, valence, danceability) are populated."""
    from music_teacher_ai.core.spotify_client import search_track

    meta = search_track("Imagine", "John Lennon")
    assert meta is not None

    assert meta.tempo is not None, "tempo is None"
    assert meta.energy is not None, "energy is None"
    assert meta.valence is not None, "valence is None"
    assert meta.danceability is not None, "danceability is None"

    assert 0.0 <= meta.energy <= 1.0, f"energy out of range: {meta.energy}"
    assert 0.0 <= meta.valence <= 1.0, f"valence out of range: {meta.valence}"
    assert meta.tempo > 0, f"tempo must be positive, got {meta.tempo}"


@requires_spotify
def test_spotify_artist_genres():
    """Artist genres list is returned (may be empty for some artists, but not missing)."""
    from music_teacher_ai.core.spotify_client import search_track

    meta = search_track("Imagine", "John Lennon")
    assert meta is not None
    assert isinstance(meta.genres, list), f"genres should be a list, got {type(meta.genres)}"


@requires_spotify
def test_spotify_no_result_returns_none():
    """search_track returns None for a clearly non-existent song."""
    from music_teacher_ai.core.spotify_client import search_track

    meta = search_track(
        "ZZZZ_THIS_SONG_DOES_NOT_EXIST_XYZ_12345",
        "ZZZZ_ARTIST_XYZ_99999",
    )
    assert meta is None, "Expected None for non-existent track"
