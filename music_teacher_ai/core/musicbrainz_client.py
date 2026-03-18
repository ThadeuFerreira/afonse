"""
MusicBrainz metadata client.

No API key required. Uses musicbrainzngs with a polite user-agent.
Rate limit: 1 request/second (enforced by the library).

Returns TrackMetadata with title, artist, album, release_year, and duration.
Audio features (tempo/valence/energy/danceability) are not available from MusicBrainz.
"""
from typing import Optional

import musicbrainzngs

from music_teacher_ai.core.spotify_client import TrackMetadata
from music_teacher_ai.core.api_cache import cached_api

musicbrainzngs.set_useragent("MusicTeacherAI", "0.1", "https://github.com/music-teacher-ai")


@cached_api("musicbrainz", from_cache=lambda d: TrackMetadata(**d))
def search_track(title: str, artist: str) -> Optional[TrackMetadata]:
    try:
        result = musicbrainzngs.search_recordings(
            recording=title,
            artistname=artist,
            limit=1,
        )
    except musicbrainzngs.WebServiceError as exc:
        raise RuntimeError(f"MusicBrainz request failed: {exc}") from exc

    recordings = result.get("recording-list", [])
    if not recordings:
        return None

    rec = recordings[0]
    return _parse_recording(rec)


def _parse_recording(rec: dict) -> TrackMetadata:
    title = rec.get("title", "")
    artist = ""
    artist_credits = rec.get("artist-credit", [])
    if artist_credits:
        first = artist_credits[0]
        if isinstance(first, dict):
            artist = first.get("artist", {}).get("name", "")

    # Album and release year from the first release
    album = ""
    release_year = None
    releases = rec.get("release-list", [])
    if releases:
        release = releases[0]
        album = release.get("title", "")
        date_str = release.get("date", "")
        if date_str:
            try:
                release_year = int(date_str[:4])
            except ValueError:
                pass

    # Duration in ms
    duration_ms = None
    length_str = rec.get("length")
    if length_str:
        try:
            duration_ms = int(length_str)
        except ValueError:
            pass

    return TrackMetadata(
        title=title,
        artist=artist,
        album=album,
        release_year=release_year,
        duration_ms=duration_ms,
        metadata_source="musicbrainz",
    )
