"""
Metadata enrichment pipeline.

Source priority:
  1. Spotify  — full metadata + audio features (requires Premium account)
  2. MusicBrainz + Last.fm  — title, artist, album, year, duration, genres
  3. Nothing  — song is recorded as IngestionFailure(stage="metadata")

Spotify is disabled for the rest of the batch the moment it raises
SpotifyPremiumRequiredError, avoiding 6500 failed requests.
"""
import json

from rich.console import Console
from sqlmodel import select

from music_teacher_ai.core.spotify_client import TrackMetadata
from music_teacher_ai.database.models import Artist, Song, Album, IngestionFailure
from music_teacher_ai.database.sqlite import get_session

console = Console()


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

def _try_spotify(title: str, artist: str) -> TrackMetadata | None:
    from music_teacher_ai.core.spotify_client import search_track
    return search_track(title, artist)


def _try_musicbrainz(title: str, artist: str) -> TrackMetadata | None:
    from music_teacher_ai.core.musicbrainz_client import search_track
    try:
        return search_track(title, artist)
    except Exception:
        return None


def _enrich_with_lastfm(meta: TrackMetadata) -> TrackMetadata:
    """Add genre tags and play count from Last.fm when not already present."""
    from music_teacher_ai.core import lastfm_client
    if not lastfm_client.is_configured():
        return meta
    if not meta.genres:
        meta.genres = lastfm_client.get_tags(meta.title, meta.artist)
    if meta.popularity is None:
        play_count = lastfm_client.get_play_count(meta.title, meta.artist)
        if play_count is not None:
            # Normalize to 0–100 scale (cap at 10M plays)
            meta.popularity = min(100, int(play_count / 100_000))
    return meta


# ---------------------------------------------------------------------------
# DB write helper
# ---------------------------------------------------------------------------

def _apply_metadata(session, song: Song, artist: Artist, meta: TrackMetadata) -> None:
    artist.genres = json.dumps(meta.genres)
    if meta.artist_spotify_id:
        artist.spotify_id = meta.artist_spotify_id
    session.add(artist)

    if meta.album:
        album = session.exec(
            select(Album)
            .where(Album.name == meta.album)
            .where(Album.artist_id == artist.id)
        ).first()
        if not album:
            album = Album(
                name=meta.album,
                artist_id=artist.id,
                release_year=meta.release_year,
            )
            session.add(album)
            session.flush()
        song.album_id = album.id

    if meta.spotify_id:
        song.spotify_id = meta.spotify_id
    if meta.release_year:
        song.release_year = meta.release_year
    song.popularity = meta.popularity
    song.duration_ms = meta.duration_ms
    song.tempo = meta.tempo
    song.valence = meta.valence
    song.energy = meta.energy
    song.danceability = meta.danceability
    if meta.genres:
        song.genre = meta.genres[0]
    song.metadata_source = meta.metadata_source
    session.add(song)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_metadata(batch_size: int = 50) -> None:
    """Enrich songs that have not yet been processed by any metadata source."""
    with get_session() as session:
        songs = session.exec(
            select(Song).where(Song.metadata_source == None)  # noqa: E711
        ).all()

    console.print(f"[cyan]Enriching metadata for {len(songs)} songs[/cyan]")

    spotify_available = True   # disabled on first SpotifyPremiumRequiredError
    enriched = 0
    failed = 0

    for song in songs:
        with get_session() as session:
            artist = session.get(Artist, song.artist_id)
            if not artist:
                continue

            meta: TrackMetadata | None = None
            error: str | None = None

            # --- Spotify ---
            if spotify_available:
                try:
                    meta = _try_spotify(song.title, artist.name)
                except Exception as exc:
                    from music_teacher_ai.core.spotify_client import SpotifyPremiumRequiredError
                    if isinstance(exc, SpotifyPremiumRequiredError):
                        console.print(
                            f"[yellow]Spotify unavailable (Premium required). "
                            f"Falling back to MusicBrainz + Last.fm for all remaining songs.[/yellow]"
                        )
                        spotify_available = False
                    else:
                        error = f"Spotify: {exc}"

            # --- MusicBrainz + Last.fm fallback ---
            if meta is None and not spotify_available:
                meta = _try_musicbrainz(song.title, artist.name)
                if meta:
                    meta = _enrich_with_lastfm(meta)
                    meta.metadata_source = "musicbrainz"

            if meta is None and error is None:
                # Spotify returned no result and no exception; try MusicBrainz anyway
                meta = _try_musicbrainz(song.title, artist.name)
                if meta:
                    meta = _enrich_with_lastfm(meta)

            if meta:
                try:
                    _apply_metadata(session, song, artist, meta)
                    session.commit()
                    enriched += 1
                except Exception as exc:
                    session.rollback()
                    error = f"DB write: {exc}"

            if meta is None:
                error = error or "No result from any source"
                session.add(
                    IngestionFailure(
                        song_id=song.id,
                        stage="metadata",
                        error_message=error,
                    )
                )
                session.commit()
                failed += 1

        if (enriched + failed) % batch_size == 0:
            source = "Spotify" if spotify_available else "MusicBrainz/Last.fm"
            console.print(f"  [{source}] enriched={enriched} failed={failed}")

    console.print(
        f"[green]Metadata enrichment complete.[/green] enriched={enriched} failed={failed}"
    )
