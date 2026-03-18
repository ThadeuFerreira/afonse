from dataclasses import dataclass, field
from typing import Optional
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from music_teacher_ai.config.settings import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET


@dataclass
class TrackMetadata:
    spotify_id: str
    title: str
    artist: str
    artist_spotify_id: str
    album: str
    release_year: Optional[int]
    popularity: Optional[int]
    duration_ms: Optional[int]
    genres: list[str] = field(default_factory=list)
    tempo: Optional[float] = None
    valence: Optional[float] = None
    energy: Optional[float] = None
    danceability: Optional[float] = None


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


def search_track(title: str, artist: str) -> Optional[TrackMetadata]:
    sp = get_client()
    query = f"track:{title} artist:{artist}"
    results = sp.search(q=query, type="track", limit=1)
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
