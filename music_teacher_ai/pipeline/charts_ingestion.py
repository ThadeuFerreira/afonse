from datetime import date

from rich.console import Console
from sqlmodel import select

from music_teacher_ai.core.billboard_client import fetch_all_years_parallel, ChartEntry
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
    workers: int = 5,
) -> None:
    end = end or date.today().year
    total_years = end - start + 1

    console.print(
        f"[cyan]Fetching {total_years} Billboard charts in parallel (workers={workers})…[/cyan]"
    )

    # Fetch all years concurrently; writes remain sequential (SQLite)
    results = fetch_all_years_parallel(start=start, end=end, workers=workers)

    fetch_errors = {year: exc for year, exc in results.items() if isinstance(exc, Exception)}
    if fetch_errors:
        for year, exc in sorted(fetch_errors.items()):
            console.print(f"[red]  {year}: {exc}[/red]")

    total_songs = 0
    total_chart_entries = 0

    for year in sorted(results):
        entries = results[year]
        if isinstance(entries, Exception):
            continue  # already reported above

        console.print(f"[cyan]Ingesting {year}[/cyan] ({len(entries)} entries)")
        with get_session() as session:
            for entry in entries:
                try:
                    artist = _get_or_create_artist(session, entry.artist)
                    song = _get_or_create_song(session, entry, artist)

                    existing = session.exec(
                        select(Chart)
                        .where(Chart.song_id == song.id)
                        .where(Chart.date == entry.date)
                    ).first()
                    if not existing:
                        session.add(Chart(
                            song_id=song.id,
                            chart_name="hot-100",
                            rank=entry.rank,
                            date=entry.date,
                        ))
                        total_chart_entries += 1

                    total_songs += 1
                except Exception as exc:
                    session.add(IngestionFailure(
                        stage="charts",
                        error_message=str(exc),
                        raw_title=entry.title,
                        raw_artist=entry.artist,
                    ))
            session.commit()

    console.print(
        f"[green]Charts ingestion complete.[/green] "
        f"Songs: {total_songs}, Chart entries: {total_chart_entries}, "
        f"Failed years: {len(fetch_errors)}"
    )
