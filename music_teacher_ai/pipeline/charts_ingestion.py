import json
from datetime import date

from rich.console import Console
from sqlmodel import select

from music_teacher_ai.core.billboard_client import iter_all_years, ChartEntry
from music_teacher_ai.database.models import Artist, Song, Chart, IngestionFailure
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.config.settings import BILLBOARD_START_YEAR

console = Console()


def _get_or_create_artist(session, name: str) -> Artist:
    artist = session.exec(select(Artist).where(Artist.name == name)).first()
    if not artist:
        artist = Artist(name=name)
        session.add(artist)
        session.flush()
    return artist


def _get_or_create_song(session, entry: ChartEntry, artist: Artist) -> Song:
    # Check by artist + title (no spotify_id yet at this stage)
    song = session.exec(
        select(Song)
        .where(Song.title == entry.title)
        .where(Song.artist_id == artist.id)
    ).first()
    if not song:
        song = Song(
            title=entry.title,
            artist_id=artist.id,
            release_year=entry.year,
        )
        session.add(song)
        session.flush()
    return song


def ingest_charts(
    start: int = BILLBOARD_START_YEAR,
    end: int | None = None,
) -> None:
    end = end or date.today().year
    total_songs = 0
    total_chart_entries = 0

    for year, entries in iter_all_years(start=start, end=end):
        console.print(f"[cyan]Ingesting Billboard {year}[/cyan] ({len(entries)} entries)")
        with get_session() as session:
            for entry in entries:
                try:
                    artist = _get_or_create_artist(session, entry.artist)
                    song = _get_or_create_song(session, entry, artist)

                    # Avoid duplicate chart entries
                    existing = session.exec(
                        select(Chart)
                        .where(Chart.song_id == song.id)
                        .where(Chart.date == entry.date)
                    ).first()
                    if not existing:
                        chart = Chart(
                            song_id=song.id,
                            chart_name="hot-100",
                            rank=entry.rank,
                            date=entry.date,
                        )
                        session.add(chart)
                        total_chart_entries += 1

                    total_songs += 1
                except Exception as exc:
                    session.add(
                        IngestionFailure(
                            stage="charts",
                            error_message=str(exc),
                            raw_title=entry.title,
                            raw_artist=entry.artist,
                        )
                    )
            session.commit()

    console.print(f"[green]Charts ingestion complete.[/green] Songs: {total_songs}, Chart entries: {total_chart_entries}")
