"""
Billboard Year-End Hot 100 chart client.

Replaces the old billboard.py weekly scraper with Wikipedia Year-End Hot 100
pages — one HTTP request per year instead of ~52 weekly requests.

URL pattern:
  https://en.wikipedia.org/wiki/Billboard_Year-End_Hot_100_singles_of_{year}

Each page contains the 100 top-ranked songs for that year as a simple HTML
table, which pandas.read_html() parses in milliseconds.  With 5 parallel
workers, a full 1960→today ingest takes seconds instead of hours.
"""
import dataclasses
import io
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterator

import pandas as pd
import requests

from music_teacher_ai.config.settings import BILLBOARD_START_YEAR
from music_teacher_ai.core.api_cache import cached_api

_WIKIPEDIA_URL = (
    "https://en.wikipedia.org/wiki/Billboard_Year-End_Hot_100_singles_of_{year}"
)
_HEADERS = {"User-Agent": "MusicTeacherAI/0.1 (educational project)"}

# Column-name aliases observed across different Wikipedia year pages.
_TITLE_COLS = ("Title", "Song", "Single", "Song title")
_ARTIST_COLS = ("Artist(s)", "Artist", "Artist(s) / Title", "Performer(s)")
# Curly and straight quotes that Genius/Wikipedia wrap titles in.
_QUOTE_RE = re.compile(r'^["\u201c\u201d\u2018\u2019]+|["\u201c\u201d\u2018\u2019]+$')


@dataclass
class ChartEntry:
    title: str
    artist: str
    rank: int
    year: int
    date: str  # ISO date — year-end charts use YYYY-12-31


def _strip_quotes(s: str) -> str:
    return _QUOTE_RE.sub("", s).strip()


def _parse_tables(tables: list, year: int) -> list[ChartEntry]:
    """Find the Hot 100 table among all tables on the page and parse it."""
    date_str = f"{year}-12-31"

    for table in tables:
        cols = set(table.columns)
        title_col = next((c for c in _TITLE_COLS if c in cols), None)
        artist_col = next((c for c in _ARTIST_COLS if c in cols), None)
        if not title_col or not artist_col:
            continue

        entries: list[ChartEntry] = []
        for rank, (_, row) in enumerate(table.iterrows(), start=1):
            title = row[title_col]
            artist = row[artist_col]
            if not isinstance(title, str) or not isinstance(artist, str):
                continue
            entries.append(ChartEntry(
                title=_strip_quotes(title),
                artist=artist.strip(),
                rank=rank,
                year=year,
                date=date_str,
            ))

        if entries:
            return entries

    return []


@cached_api(
    "wikipedia_charts",
    serialize=lambda r: [dataclasses.asdict(e) for e in r],
    from_cache=lambda data: [ChartEntry(**d) for d in data],
)
def fetch_chart_for_year(
    year: int,
    limit: int | None = None,
) -> list[ChartEntry]:
    """Fetch the Billboard Year-End Hot 100 for *year* from Wikipedia."""
    url = _WIKIPEDIA_URL.format(year=year)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to fetch Wikipedia chart for {year}: {exc}") from exc

    try:
        tables = pd.read_html(io.StringIO(resp.text))
    except ValueError as exc:
        raise RuntimeError(
            f"No tables found on Wikipedia chart page for {year}: {exc}"
        ) from exc

    entries = _parse_tables(tables, year)
    if not entries:
        raise RuntimeError(
            f"Could not parse chart table for {year} — Wikipedia column names may have changed"
        )

    return entries[:limit] if limit else entries


def fetch_all_years_parallel(
    start: int = BILLBOARD_START_YEAR,
    end: int | None = None,
    workers: int = 5,
    limit: int | None = None,
    on_year_done: Callable[[int, "list[ChartEntry] | Exception"], None] | None = None,
    # kept for interface compatibility — unused (Wikipedia has no named "chart")
    chart: str = "hot-100",
) -> dict[int, list[ChartEntry] | Exception]:
    """
    Fetch Year-End Hot 100 charts for all years in parallel.

    Because we fetch one Wikipedia page per year (instead of 52 weekly Billboard
    pages), the full 1960→today dataset completes in seconds even on a cold cache.

    Args:
        limit: Return only the top-N songs per year.
        on_year_done: Optional callback invoked from a worker thread after each
            year completes.  Receives ``(year, result)`` where result is either
            a list of entries or the Exception that was raised.

    Returns:
        Dict mapping year → list[ChartEntry] on success, or Exception on failure.
        Order is arbitrary; callers should sort by year if needed.
    """
    end = end or date.today().year
    years = list(range(start, end + 1))
    results: dict[int, list[ChartEntry] | Exception] = {}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_year = {
            pool.submit(fetch_chart_for_year, year, limit): year
            for year in years
        }
        for future in as_completed(future_to_year):
            year = future_to_year[future]
            exc = future.exception()
            result: list[ChartEntry] | Exception = exc if exc is not None else future.result()
            results[year] = result
            if on_year_done is not None:
                on_year_done(year, result)

    return results


def iter_all_years(
    start: int = BILLBOARD_START_YEAR,
    end: int | None = None,
    limit: int | None = None,
    chart: str = "hot-100",  # kept for interface compatibility
) -> Iterator[tuple[int, list[ChartEntry]]]:
    """Sequential fallback — yields (year, entries) one at a time."""
    end = end or date.today().year
    for year in range(start, end + 1):
        yield year, fetch_chart_for_year(year, limit=limit)
