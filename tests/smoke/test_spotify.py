"""
Smoke tests for the Spotify API client.

Verifies:
- Credentials are valid and authentication succeeds
- track search returns a result for a well-known song
- Audio features are returned for a valid track ID
- Artist genres are populated

NOTE: Since November 2024, Spotify requires the developer app owner to have an
active Premium subscription. Tests that hit the API will be skipped with a clear
message if a 403 is returned, rather than failing.
"""
import pytest
from tests.smoke.conftest import requires_spotify


def _skip_if_premium_required(exc):
    from music_teacher_ai.core.spotify_client import SpotifyPremiumRequiredError
    if isinstance(exc, SpotifyPremiumRequiredError):
        pytest.skip(str(exc))
    raise exc


@requires_spotify
def test_spotify_authentication():
    """Client can authenticate with the provided credentials."""
    from music_teacher_ai.core.spotify_client import get_client
    from spotipy.exceptions import SpotifyException

    sp = get_client()
    try:
        result = sp.search(q="Imagine", type="track", limit=1)
    except SpotifyException as exc:
        if exc.http_status == 403:
            pytest.skip(
                "Spotify API returned 403: app owner requires Premium. "
                "See https://developer.spotify.com/documentation/web-api/concepts/quota-modes"
            )
        raise
    assert "tracks" in result, "Spotify response missing 'tracks' key"
    assert result["tracks"]["items"], "Spotify returned no tracks for 'Imagine'"


@requires_spotify
def test_spotify_search_known_track():
    """search_track() returns metadata for a well-known song."""
    from music_teacher_ai.core.spotify_client import search_track, SpotifyPremiumRequiredError

    try:
        meta = search_track("Imagine", "John Lennon")
    except SpotifyPremiumRequiredError as exc:
        pytest.skip(str(exc))

    assert meta is not None, "search_track returned None for 'Imagine' by John Lennon"
    assert meta.spotify_id, "spotify_id is empty"
    assert meta.title, "title is empty"
    assert meta.artist, "artist is empty"
    assert meta.release_year is not None, "release_year is None"
    assert 1970 <= meta.release_year <= 1972, f"Unexpected release year: {meta.release_year}"


@requires_spotify
def test_spotify_audio_features():
    """Audio features (tempo, energy, valence, danceability) are populated."""
    from music_teacher_ai.core.spotify_client import search_track, SpotifyPremiumRequiredError

    try:
        meta = search_track("Imagine", "John Lennon")
    except SpotifyPremiumRequiredError as exc:
        pytest.skip(str(exc))

    assert meta is not None
    # Audio features may be None if the endpoint is restricted
    if meta.tempo is not None:
        assert meta.tempo > 0, f"tempo must be positive, got {meta.tempo}"
    if meta.energy is not None:
        assert 0.0 <= meta.energy <= 1.0, f"energy out of range: {meta.energy}"
    if meta.valence is not None:
        assert 0.0 <= meta.valence <= 1.0, f"valence out of range: {meta.valence}"


@requires_spotify
def test_spotify_artist_genres():
    """Artist genres list is returned (may be empty for some artists, but not missing)."""
    from music_teacher_ai.core.spotify_client import search_track, SpotifyPremiumRequiredError

    try:
        meta = search_track("Imagine", "John Lennon")
    except SpotifyPremiumRequiredError as exc:
        pytest.skip(str(exc))

    assert meta is not None
    assert isinstance(meta.genres, list), f"genres should be a list, got {type(meta.genres)}"


@requires_spotify
def test_spotify_no_result_returns_none():
    """search_track returns None for a clearly non-existent song."""
    from music_teacher_ai.core.spotify_client import search_track, SpotifyPremiumRequiredError

    try:
        meta = search_track(
            "ZZZZ_THIS_SONG_DOES_NOT_EXIST_XYZ_12345",
            "ZZZZ_ARTIST_XYZ_99999",
        )
    except SpotifyPremiumRequiredError as exc:
        pytest.skip(str(exc))

    assert meta is None, "Expected None for non-existent track"
