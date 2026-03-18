from datetime import date
from dataclasses import dataclass
from typing import Iterator
import billboard

from music_teacher_ai.config.settings import BILLBOARD_START_YEAR, BILLBOARD_CHART


@dataclass
class ChartEntry:
    title: str
    artist: str
    rank: int
    year: int
    date: str


def _last_saturday_of_year(year: int) -> date:
    """Return a date string for the last week of the given year."""
    d = date(year, 12, 28)
    # Roll back to Saturday (weekday 5)
    d = d.replace(day=28 - (d.weekday() + 2) % 7)
    return d


def fetch_chart_for_year(year: int, chart: str = BILLBOARD_CHART) -> list[ChartEntry]:
    d = _last_saturday_of_year(year)
    date_str = d.strftime("%Y-%m-%d")
    try:
        chart_data = billboard.ChartData(chart, date=date_str)
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch Billboard chart for {year}: {exc}") from exc

    return [
        ChartEntry(
            title=entry.title,
            artist=entry.artist,
            rank=entry.rank,
            year=year,
            date=date_str,
        )
        for entry in chart_data
    ]


def iter_all_years(
    start: int = BILLBOARD_START_YEAR,
    end: int | None = None,
    chart: str = BILLBOARD_CHART,
) -> Iterator[tuple[int, list[ChartEntry]]]:
    end = end or date.today().year
    for year in range(start, end + 1):
        yield year, fetch_chart_for_year(year, chart)
