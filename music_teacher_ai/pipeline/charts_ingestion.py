from datetime import date

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from sqlmodel import select

from music_teacher_ai.core.billboard_client import fetch_all_years_parallel, ChartEntry
from music_teacher_ai.database.models import Artist, Song, Chart, IngestionFailure
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.config.settings import BILLBOARD_START_YEAR

console = Console()

# Keywords that suggest the site is rate-limiting us rather than a real error.
_BLOCK_HINTS = ("429", "too many", "rate limit", "forbidden", "blocked")


def _is_block(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(hint in msg for hint in _BLOCK_HINTS)


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
    limit: int | None = None,
) -> None:
    end = end or date.today().year
    total_years = end - start + 1
    limit_label = f" (top {limit} per year)" if limit else ""

    console.print(
        f"[cyan]Fetching {total_years} Billboard charts in parallel "
        f"(workers={workers}){limit_label}…[/cyan]"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        fetch_task = progress.add_task("Fetching years", total=total_years)

        def on_year_done(year: int, result: list[ChartEntry] | Exception) -> None:
            if isinstance(result, Exception):
                if _is_block(result):
                    console.log(f"[bold red]  {year}  BLOCKED – {result}[/bold red]")
                else:
                    console.log(f"[red]  {year}  ERROR   – {result}[/red]")
            else:
                console.log(f"[green]  {year}  OK      – {len(result)} entries[/green]")
            progress.advance(fetch_task)

        results = fetch_all_years_parallel(
            start=start,
            end=end,
            workers=workers,
            limit=limit,
            on_year_done=on_year_done,
        )

    fetch_errors = {year: exc for year, exc in results.items() if isinstance(exc, Exception)}
    blocks = {y: e for y, e in fetch_errors.items() if _is_block(e)}
    plain_errors = {y: e for y, e in fetch_errors.items() if not _is_block(e)}

    if blocks:
        console.print(
            f"[bold red]{len(blocks)} year(s) were blocked (rate-limited). "
            "Consider reducing --workers or retrying later.[/bold red]"
        )
    if plain_errors:
        console.print(f"[red]{len(plain_errors)} year(s) failed with errors.[/red]")

    total_songs = 0
    total_chart_entries = 0

    with get_session() as session:
        for year in sorted(results):
            entries = results[year]
            if isinstance(entries, Exception):
                continue  # already reported above

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
        f"Failed years: {len(fetch_errors)} "
        f"({len(blocks)} blocked, {len(plain_errors)} errors)"
    )
