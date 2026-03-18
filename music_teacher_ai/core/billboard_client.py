from datetime import date
from dataclasses import dataclass
from typing import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def fetch_all_years_parallel(
    start: int = BILLBOARD_START_YEAR,
    end: int | None = None,
    chart: str = BILLBOARD_CHART,
    workers: int = 5,
) -> dict[int, list[ChartEntry] | Exception]:
    """
    Fetch charts for all years in parallel using a thread pool.

    billboard.py is I/O-bound (HTTP scraping) with no built-in rate limiting.
    Five workers gives ~5x speedup without risking soft-blocks from billboard.com.
    Increase `workers` carefully — the site has no documented rate limit but
    aggressive parallelism may trigger 429s.

    Returns a dict mapping year → list[ChartEntry] (success) or Exception (failure).
    Results are in arbitrary order; callers should sort by year if needed.
    """
    end = end or date.today().year
    years = list(range(start, end + 1))
    results: dict[int, list[ChartEntry] | Exception] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_year = {
            pool.submit(fetch_chart_for_year, year, chart): year
            for year in years
        }
        for future in as_completed(future_to_year):
            year = future_to_year[future]
            exc = future.exception()
            results[year] = exc if exc is not None else future.result()

    return results


def iter_all_years(
    start: int = BILLBOARD_START_YEAR,
    end: int | None = None,
    chart: str = BILLBOARD_CHART,
) -> Iterator[tuple[int, list[ChartEntry]]]:
    """Sequential fallback — yields (year, entries) one at a time."""
    end = end or date.today().year
    for year in range(start, end + 1):
        yield year, fetch_chart_for_year(year, chart)
