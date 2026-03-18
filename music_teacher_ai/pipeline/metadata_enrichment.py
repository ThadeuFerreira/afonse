import json

from rich.console import Console
from sqlmodel import select

from music_teacher_ai.core.spotify_client import search_track
from music_teacher_ai.database.models import Artist, Song, Album, IngestionFailure
from music_teacher_ai.database.sqlite import get_session

console = Console()


def enrich_metadata(batch_size: int = 50) -> None:
    """Fetch Spotify metadata for songs that have no spotify_id yet."""
    with get_session() as session:
        songs = session.exec(
            select(Song).where(Song.spotify_id == None)  # noqa: E711
        ).all()

    console.print(f"[cyan]Enriching {len(songs)} songs with Spotify metadata[/cyan]")
    enriched = 0
    failed = 0

    for song in songs:
        with get_session() as session:
            artist = session.get(Artist, song.artist_id)
            if not artist:
                continue

            try:
                meta = search_track(song.title, artist.name)
                if not meta:
                    raise ValueError("No Spotify result found")

                # Update artist spotify_id and genres
                artist.spotify_id = meta.artist_spotify_id
                artist.genres = json.dumps(meta.genres)
                session.add(artist)

                # Upsert album
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

                # Update song
                song.spotify_id = meta.spotify_id
                song.album_id = album.id
                song.release_year = meta.release_year
                song.popularity = meta.popularity
                song.duration_ms = meta.duration_ms
                song.tempo = meta.tempo
                song.valence = meta.valence
                song.energy = meta.energy
                song.danceability = meta.danceability
                # Derive a single genre string from the artist's genre list
                if meta.genres:
                    song.genre = meta.genres[0]
                session.add(song)
                session.commit()
                enriched += 1

            except Exception as exc:
                session.add(
                    IngestionFailure(
                        song_id=song.id,
                        stage="metadata",
                        error_message=str(exc),
                    )
                )
                session.commit()
                failed += 1

        if (enriched + failed) % batch_size == 0:
            console.print(f"  enriched={enriched} failed={failed}")

    console.print(f"[green]Metadata enrichment complete.[/green] enriched={enriched} failed={failed}")
