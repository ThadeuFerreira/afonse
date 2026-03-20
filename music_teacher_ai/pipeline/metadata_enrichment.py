"""
Metadata enrichment pipeline.

Source priority:
  1. Spotify  — full metadata + audio features (requires Premium account)
  2. MusicBrainz + Last.fm  — title, artist, album, year, duration, genres
  3. Nothing  — song is recorded as IngestionFailure(stage="metadata")

Spotify is disabled for the rest of the batch the moment it raises
SpotifyPremiumRequiredError, avoiding 6500 failed requests.

Debug logging:
  Set DEBUG=1 (or any truthy value) to enable icecream trace output showing
  which API source was used, ISRC values found, and per-song decisions.
"""
import json
import os

from icecream import ic
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from sqlmodel import select

from music_teacher_ai.core.spotify_client import TrackMetadata
from music_teacher_ai.database.models import Album, Artist, IngestionFailure, Song
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.reporter import PipelineReport

console = Console()

# Disable icecream unless DEBUG is set in the environment.
if not os.getenv("DEBUG"):
    ic.disable()


# ---------------------------------------------------------------------------
# Source helpers
# ---------------------------------------------------------------------------

def _try_spotify(title: str, artist: str) -> TrackMetadata | None:
    from music_teacher_ai.core.spotify_client import search_track
    ic(title, artist)
    result = search_track(title, artist)
    ic(result)
    return result


def _try_musicbrainz(title: str, artist: str) -> TrackMetadata | None:
    from music_teacher_ai.core.musicbrainz_client import search_track
    try:
        ic(title, artist)
        result = search_track(title, artist)
        ic(result)
        return result
    except Exception as exc:
        ic(exc)
        return None


def _enrich_with_lastfm(meta: TrackMetadata) -> TrackMetadata:
    """Add genre tags and play count from Last.fm when not already present."""
    from music_teacher_ai.core import lastfm_client
    if not lastfm_client.is_configured():
        return meta
    if not meta.genres:
        tags = lastfm_client.get_tags(meta.title, meta.artist)
        ic(tags)
        meta.genres = tags
    if meta.popularity is None:
        play_count = lastfm_client.get_play_count(meta.title, meta.artist)
        if play_count is not None:
            meta.popularity = min(100, int(play_count / 100_000))
            ic(play_count, meta.popularity)
    return meta


# ---------------------------------------------------------------------------
# DB write helper
# ---------------------------------------------------------------------------

def _apply_metadata(session, song: Song, artist: Artist, meta: TrackMetadata) -> None:
    ic(meta.metadata_source, meta.isrc)
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
    if meta.isrc:
        song.isrc = meta.isrc
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

def enrich_metadata(batch_size: int = 50, init_quick: bool = False) -> None:
    """
    Enrich songs that have not yet been processed by any metadata source AND
    still need lyrics work (no lyrics yet, or existing lyrics are suspicious).

    Songs that already have good metadata AND valid lyrics are skipped — they
    are considered done and do not need to be re-fetched.
    """
    from music_teacher_ai.pipeline.validation import songs_needing_lyrics

    report = PipelineReport("metadata")

    # Only consider songs that still need lyrics work
    needs_work = songs_needing_lyrics()

    with get_session() as session:
        base_q = (
            select(Song)
            .where(Song.metadata_source == None)  # noqa: E711
            .where(Song.id.in_(needs_work))
        )
        if init_quick:
            base_q = base_q.where(Song.release_year >= 2000).limit(10)
        songs = session.exec(base_q).all()

    total = len(songs)
    report.set("total", total)
    console.print(f"[cyan]Enriching metadata for {total} songs[/cyan]")

    if not total:
        report.save()
        return

    spotify_available = True   # disabled on first SpotifyPremiumRequiredError
    enriched = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn("[green]✓{task.fields[enriched]}[/green] [red]✗{task.fields[failed]}[/red]"),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "Enriching metadata",
            total=total,
            enriched=0,
            failed=0,
        )

        for song in songs:
            with get_session() as session:
                artist = session.get(Artist, song.artist_id)
                if not artist:
                    progress.advance(task)
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
                            console.log(
                                "[yellow]Spotify unavailable (Premium required). "
                                "Falling back to MusicBrainz + Last.fm for all remaining songs.[/yellow]"
                            )
                            report.add_event("spotify_disabled", reason="SpotifyPremiumRequiredError")
                            spotify_available = False
                        else:
                            error = f"Spotify: {exc}"
                            ic(error)

                # --- MusicBrainz + Last.fm fallback ---
                # Runs when Spotify is disabled OR returned no result (meta is None).
                # The guard on `meta is None` prevents a duplicate call when the
                # spotify_available block above already tried MusicBrainz.
                if meta is None:
                    meta = _try_musicbrainz(song.title, artist.name)
                    if meta:
                        meta = _enrich_with_lastfm(meta)
                        meta.metadata_source = "musicbrainz"

                if meta:
                    try:
                        _apply_metadata(session, song, artist, meta)
                        session.commit()
                        enriched += 1
                    except Exception as exc:
                        session.rollback()
                        error = f"DB write: {exc}"
                        ic(error)

                if meta is None:
                    error = error or "No result from any source"
                    ic(song.title, artist.name, error)
                    report.add_error(song_id=song.id, title=song.title, artist=artist.name, error=error)
                    # Mark the song so it is not retried on every subsequent run.
                    song.metadata_source = "failed"
                    session.add(song)
                    session.add(
                        IngestionFailure(
                            song_id=song.id,
                            stage="metadata",
                            error_message=error,
                        )
                    )
                    session.commit()
                    failed += 1

            progress.update(task, advance=1, enriched=enriched, failed=failed)

            if (enriched + failed) % batch_size == 0:
                source = "Spotify" if spotify_available else "MusicBrainz/Last.fm"
                console.log(
                    f"  [{source}] enriched=[green]{enriched}[/green] "
                    f"failed=[red]{failed}[/red]"
                )

    source = "spotify" if spotify_available else "musicbrainz"
    report.set("enriched", enriched)
    report.set("failed", failed)
    report.set("final_source", source)
    report_path = report.save()

    console.print(
        f"[green]Metadata enrichment complete.[/green] "
        f"enriched={enriched} failed={failed} total={total}"
    )
    console.print(f"[dim]Report: {report_path}[/dim]")
