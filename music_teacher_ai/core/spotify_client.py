from dataclasses import dataclass, field
from typing import Optional
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

from music_teacher_ai.config.settings import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET
from music_teacher_ai.core.api_cache import cached_api


class SpotifyPremiumRequiredError(RuntimeError):
    """
    Raised when the Spotify API returns 403 with a premium-required message.

    Since November 2024, Spotify requires the owner of the developer app to have
    an active Premium subscription. To fix this:

      1. Upgrade the Spotify account that owns the developer app to Premium, OR
      2. Apply for Extended Quota Mode at:
         https://developer.spotify.com/documentation/web-api/concepts/quota-modes
    """


@dataclass
class TrackMetadata:
    title: str
    artist: str
    album: str
    spotify_id: Optional[str] = None        # None when sourced from MusicBrainz/Last.fm
    artist_spotify_id: Optional[str] = None  # None when sourced from MusicBrainz/Last.fm
    release_year: Optional[int] = None
    popularity: Optional[int] = None
    duration_ms: Optional[int] = None
    genres: list[str] = field(default_factory=list)
    tempo: Optional[float] = None
    valence: Optional[float] = None
    energy: Optional[float] = None
    danceability: Optional[float] = None
    metadata_source: str = "spotify"


def _make_client() -> spotipy.Spotify:
    auth = SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    )
    return spotipy.Spotify(auth_manager=auth)


_client: spotipy.Spotify | None = None


def get_client() -> spotipy.Spotify:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


@cached_api("spotify", from_cache=lambda d: TrackMetadata(**d))
def search_track(title: str, artist: str) -> Optional[TrackMetadata]:
    sp = get_client()
    query = f"track:{title} artist:{artist}"
    try:
        results = sp.search(q=query, type="track", limit=1)
    except SpotifyException as exc:
        if exc.http_status == 403:
            raise SpotifyPremiumRequiredError(
                "Spotify API returned 403: the owner of this developer app requires an active "
                "Premium subscription. Upgrade the account at spotify.com or apply for Extended "
                "Quota Mode at https://developer.spotify.com/documentation/web-api/concepts/quota-modes"
            ) from exc
        raise
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return None
    return _parse_track(sp, items[0])


def _parse_track(sp: spotipy.Spotify, item: dict) -> TrackMetadata:
    artist_id = item["artists"][0]["id"]
    artist_info = sp.artist(artist_id)
    genres = artist_info.get("genres", [])

    release_year = None
    try:
        release_year = int(item["album"]["release_date"][:4])
    except (KeyError, ValueError):
        pass

    audio_features = {}
    try:
        features = sp.audio_features([item["id"]])
        if features and features[0]:
            audio_features = features[0]
    except Exception:
        pass

    return TrackMetadata(
        spotify_id=item["id"],
        title=item["name"],
        artist=item["artists"][0]["name"],
        artist_spotify_id=artist_id,
        album=item["album"]["name"],
        release_year=release_year,
        popularity=item.get("popularity"),
        duration_ms=item.get("duration_ms"),
        genres=genres,
        tempo=audio_features.get("tempo"),
        valence=audio_features.get("valence"),
        energy=audio_features.get("energy"),
        danceability=audio_features.get("danceability"),
    )
