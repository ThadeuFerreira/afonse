"""
Last.fm metadata client.

Provides genre tags and listener/play counts.
Requires LASTFM_API_KEY in .env (free at https://www.last.fm/api/account/create).

Used as a supplement to MusicBrainz when Spotify is unavailable.
"""

from typing import Optional

from music_teacher_ai.config.settings import LASTFM_API_KEY
from music_teacher_ai.core.api_cache import cached_api


def _get_network():
    import pylast

    if not LASTFM_API_KEY:
        raise RuntimeError(
            "LASTFM_API_KEY is not set. Get a free key at https://www.last.fm/api/account/create"
        )
    return pylast.LastFMNetwork(api_key=LASTFM_API_KEY)


@cached_api("lastfm")
def _fetch_tags(title: str, artist: str, limit: int) -> list[str]:
    """Inner call — raises on error so the cache is not written on failure."""
    network = _get_network()
    track = network.get_track(artist, title)
    top_tags = track.get_top_tags(limit=limit)
    tags = [t.item.get_name().lower() for t in top_tags if t.item.get_name()]
    if tags:
        return tags

    # Fallback for tracks that have no direct tag data in Last.fm.
    artist_top_tags = network.get_artist(artist).get_top_tags(limit=limit)
    return [t.item.get_name().lower() for t in artist_top_tags if t.item.get_name()]


def get_tags(title: str, artist: str, limit: int = 5) -> list[str]:
    """Return the top genre tags for a track. Returns [] if unavailable."""
    try:
        return _fetch_tags(title, artist, limit)
    except Exception:
        return []


@cached_api("lastfm")
def _fetch_play_count(title: str, artist: str) -> Optional[int]:
    """Inner call — raises on error so the cache is not written on failure."""
    network = _get_network()
    track = network.get_track(artist, title)
    return int(track.get_playcount())


def get_play_count(title: str, artist: str) -> Optional[int]:
    """Return the global play count for a track. Returns None if unavailable."""
    try:
        return _fetch_play_count(title, artist)
    except Exception:
        return None


def is_configured() -> bool:
    return bool(LASTFM_API_KEY)
