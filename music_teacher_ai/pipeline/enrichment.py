"""
Robust enrichment pipeline with randomised exploration.

Strategy
--------
For each criterion (genre / artist / year) the pipeline builds a *pool of
variants* — named query strategies that each cover a different slice of the
catalog:

  genre  → tag_walk     : seed tag + up to 9 related tags  (tag.getTopTracks)
           artist_walk  : top artists for the genre         (artist.getTopTracks)
           country_chart: geo.getTopTracks for 6 countries

  artist → direct       : artist.getTopTracks (random pages)
           similar_walk : artist.getSimilar → their top tracks

  year   → mb_year      : MusicBrainz recordings search (random page offsets)

Within each variant pages are selected *at random* so repeated runs explore
different parts of the ranked list rather than always re-fetching page 1.

Duplicate-aware loop
--------------------
A global in-memory set of normalised "artist||title" keys is loaded once at
startup.  Every inserted key is added immediately so later variants benefit
without extra DB queries.

A variant is marked *saturated* once it has been tried ≥ _MIN_VARIANT_TRIES
times and its overall duplicate ratio exceeds _DUP_THRESHOLD (90 %).
Saturated / exhausted variants are dropped from the active pool.

The loop also stops if the last _GLOBAL_DUP_STOP consecutive requests across
ALL variants were all-duplicates.

Stop conditions (first one wins)
---------------------------------
  1. new_songs_inserted  ≥ limit
  2. api_requests        ≥ max_requests
  3. elapsed time        ≥ max_runtime_seconds
  4. all variants exhausted / saturated
  5. _GLOBAL_DUP_STOP consecutive fully-duplicate pages
"""
import time
from collections import deque
from typing import Optional

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

from music_teacher_ai.database.models import Artist, Song
from music_teacher_ai.database.repositories import SongRepository, normalize_text, song_key
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.fetchers import REQUEST_DELAY, build_variants as build_fetch_variants
from music_teacher_ai.pipeline.reporter import PipelineReport
from music_teacher_ai.pipeline.types import CandidateSong, EnrichmentResult, Variant

console = Console()
_song_repo = SongRepository()

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_PAGE_SIZE = 50
_DEFAULT_MAX_REQUESTS = 200
_DEFAULT_MAX_RUNTIME = 300
_DEFAULT_RANDOM_PAGE_MAX = 50
_DUP_THRESHOLD = 0.9        # variant dup ratio above which it's considered saturated
_MIN_VARIANT_TRIES = 3      # minimum page tries before checking saturation
_GLOBAL_DUP_STOP = 10       # consecutive all-dup pages across all variants → stop
_MAX_LIMIT = 1000


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    return normalize_text(s)


def _song_key(title: str, artist: str) -> str:
    return song_key(title, artist)


def _load_existing_keys() -> set[str]:
    with get_session() as session:
        return _song_repo.load_existing_keys(session)


# ---------------------------------------------------------------------------
# Variant builders
# ---------------------------------------------------------------------------

def _build_variants(
    genre: Optional[str],
    artist: Optional[str],
    year: Optional[int],
    api_key: str,
    random_page_max: int,
) -> list[Variant]:
    variants = build_fetch_variants(
        genre=genre,
        artist=artist,
        year=year,
        api_key=api_key,
        random_page_max=random_page_max,
    )
    # Keep threshold semantics aligned with enrichment tunables for saturation.
    for variant in variants:
        variant.min_variant_tries = _MIN_VARIANT_TRIES
        variant.dup_threshold = _DUP_THRESHOLD
    return variants


# ---------------------------------------------------------------------------
# DB insert
# ---------------------------------------------------------------------------

def _insert_candidates(
    candidates: list[CandidateSong],
    existing_keys: set[str],
) -> tuple[int, int]:
    """
    Insert only candidates not already in the DB.

    existing_keys is updated in-place so the next variant page benefits
    immediately without an extra DB query.  Returns (inserted, skipped).
    """
    inserted = 0
    skipped = 0

    with get_session() as session:
        for c in candidates:
            key = _song_key(c.title, c.artist)
            if key in existing_keys:
                skipped += 1
                continue

            artist_row = _song_repo.get_or_create_artist(session, c.artist)

            # Guard against a race on the same artist from a prior page
            if _song_repo.song_exists(session, title=c.title, artist_id=artist_row.id):
                existing_keys.add(key)
                skipped += 1
                continue

            try:
                _song_repo.add_song(
                    session,
                    title=c.title,
                    artist_id=artist_row.id,
                    release_year=c.year,
                )
                existing_keys.add(key)
                inserted += 1
            except Exception:
                # Protect idempotency on concurrent duplicate inserts.
                skipped += 1

        session.commit()

    return inserted, skipped


def _build_report(
    result: EnrichmentResult,
    *,
    genre: Optional[str],
    artist: Optional[str],
    year: Optional[int],
    limit: int,
    max_requests: int,
) -> tuple[PipelineReport, str]:
    report = PipelineReport("enrichment")
    report.set("requested_limit", limit)
    report.set("max_requests", max_requests)
    if genre:
        report.set("genre", genre)
    if artist:
        report.set("artist", artist)
    if year:
        report.set("year", year)
    criteria = " ".join(
        filter(
            None,
            [
                f"genre={genre!r}" if genre else "",
                f"artist={artist!r}" if artist else "",
                f"year={year}" if year else "",
            ],
        )
    )
    return report, criteria


def _run_post_pipeline() -> None:
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.metadata_enrichment import enrich_metadata
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index

    console.print("[bold green]Step 1/4 – Enriching metadata...[/bold green]")
    enrich_metadata()
    console.print("[bold green]Step 2/4 – Downloading lyrics...[/bold green]")
    download_lyrics()
    console.print("[bold green]Step 3/4 – Building vocabulary index...[/bold green]")
    build_vocabulary_index()
    console.print("[bold green]Step 4/4 – Generating embeddings...[/bold green]")
    generate_embeddings()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def enrich_database(
    genre: Optional[str] = None,
    artist: Optional[str] = None,
    year: Optional[int] = None,
    limit: int = 100,
    max_requests: int = _DEFAULT_MAX_REQUESTS,
    max_runtime_seconds: int = _DEFAULT_MAX_RUNTIME,
    random_page_max: int = _DEFAULT_RANDOM_PAGE_MAX,
    run_pipeline: bool = True,
    # Legacy alias kept for callers that pass max_pages=
    max_pages: Optional[int] = None,
) -> EnrichmentResult:
    """
    Expand the song database with candidates from multiple API strategies.

    Args:
        genre:               Last.fm genre tag (activates tag/artist/country variants).
        artist:              Artist name (activates direct + similar-artist variants).
        year:                Release year (MusicBrainz search).
        limit:               Maximum new songs to insert (capped at 1 000).
        max_requests:        Total API requests allowed per run.
        max_runtime_seconds: Hard wall-clock timeout.
        random_page_max:     Upper bound for random page selection per variant.
        run_pipeline:        Run metadata/lyrics/vocab/embedding stages after insert.
        max_pages:           Legacy alias for max_requests (deprecated).
    """
    if max_pages is not None:
        max_requests = max_pages  # backward compat

    if not any([genre, artist, year]):
        raise ValueError("Provide at least one of: genre, artist, year.")

    limit = min(limit, _MAX_LIMIT)

    from music_teacher_ai.config.settings import LASTFM_API_KEY
    api_key: str = LASTFM_API_KEY or ""

    result = EnrichmentResult(
        genre=genre, artist=artist, year=year, requested_limit=limit,
    )
    report, criteria = _build_report(
        result,
        genre=genre,
        artist=artist,
        year=year,
        limit=limit,
        max_requests=max_requests,
    )
    console.print(f"[cyan]Enriching database: {criteria}  limit={limit}[/cyan]")

    existing_keys = _load_existing_keys()
    console.print(f"[dim]{len(existing_keys)} songs already in database[/dim]")

    variants = _build_variants(genre, artist, year, api_key, random_page_max)
    console.print(f"[dim]{len(variants)} query variants built[/dim]")
    for v in variants:
        console.log(f"[dim]  • {v.name}[/dim]")

    active: deque[Variant] = deque(variants)
    deadline = time.monotonic() + max_runtime_seconds
    api_requests = 0
    consecutive_global_dup = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn(
            "[green]✓{task.fields[new]}[/green]  "
            "[dim]dup={task.fields[dup]}  "
            "req={task.fields[req]}  "
            "variants={task.fields[variants]}[/dim]"
        ),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "Enriching",
            total=limit,
            new=0,
            dup=0,
            req=0,
            variants=len(active),
        )

        while (
            result.new_songs_inserted < limit
            and api_requests < max_requests
            and active
            and time.monotonic() < deadline
        ):
            variant = active.popleft()
            page = variant.next_page()

            if page is None:
                report.add_event("variant_exhausted", name=variant.name, new=variant.new_count)
                continue  # don't re-add — naturally dropped

            candidates = variant.fetch_fn(page)
            api_requests += 1
            result.api_results_processed += len(candidates)

            # Cap to remaining capacity before inserting
            capacity = limit - result.new_songs_inserted
            novel = [c for c in candidates if _song_key(c.title, c.artist) not in existing_keys]
            known  = [c for c in candidates if _song_key(c.title, c.artist) in existing_keys]
            trimmed = known + novel[:capacity]

            inserted, skipped = _insert_candidates(trimmed, existing_keys)
            result.new_songs_inserted += inserted
            result.duplicates_skipped += skipped
            variant.record(page, inserted, skipped)

            # Track global consecutive all-dup pages
            batch_total = len(candidates)
            batch_dup = skipped / batch_total if batch_total > 0 else 1.0
            if batch_dup >= _DUP_THRESHOLD:
                consecutive_global_dup += 1
            else:
                consecutive_global_dup = 0

            progress.update(
                task,
                advance=inserted,
                new=result.new_songs_inserted,
                dup=result.duplicates_skipped,
                req=api_requests,
                variants=len(active),
            )

            # Global duplicate stop
            if consecutive_global_dup >= _GLOBAL_DUP_STOP:
                result.stop_reason = "global_duplicate_threshold"
                report.add_event("global_dup_stop", consecutive=consecutive_global_dup)
                console.log(
                    f"[yellow]{_GLOBAL_DUP_STOP} consecutive high-dup pages "
                    f"across all variants — stopping.[/yellow]"
                )
                break

            # Decide whether to keep the variant active
            if variant.is_saturated():
                report.add_event(
                    "variant_saturated",
                    name=variant.name,
                    dup_ratio=round(variant.dup_ratio, 2),
                    tries=len(variant.tried_pages),
                )
                console.log(
                    f"[dim]Retired saturated variant: {variant.name} "
                    f"(dup={variant.dup_ratio:.0%})[/dim]"
                )
            elif not variant.is_exhausted:
                active.append(variant)  # round-robin: put at end

            time.sleep(REQUEST_DELAY)

    # Determine stop reason
    if not result.stop_reason:
        if result.new_songs_inserted >= limit:
            result.stop_reason = "limit_reached"
        elif api_requests >= max_requests:
            result.stop_reason = "max_requests_reached"
        elif time.monotonic() >= deadline:
            result.stop_reason = "timeout"
        else:
            result.stop_reason = "all_variants_exhausted"

    result.api_requests = api_requests
    report.set("api_requests", api_requests)
    report.set("api_results_processed", result.api_results_processed)
    report.set("new_songs_inserted", result.new_songs_inserted)
    report.set("duplicates_skipped", result.duplicates_skipped)
    report.set("stop_reason", result.stop_reason)

    console.print()
    console.print(
        f"[bold]Enrichment request[/bold]\n"
        f"  {criteria}\n\n"
        f"  API requests made  : {api_requests}\n"
        f"  Candidates seen    : {result.api_results_processed}\n"
        f"  Duplicates filtered: {result.duplicates_skipped}\n"
        f"  New songs inserted : [green]{result.new_songs_inserted}[/green]\n\n"
        f"  Stopping condition : {result.stop_reason.replace('_', ' ')}"
    )

    if run_pipeline and result.new_songs_inserted > 0:
        console.print()
        console.print("[bold green]Running pipeline on new songs...[/bold green]")
        _run_post_pipeline()

    report_path = report.save()
    console.print(f"[dim]Report: {report_path}[/dim]")

    return result
