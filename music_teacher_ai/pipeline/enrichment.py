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
import random
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

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
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.reporter import PipelineReport

console = Console()

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
_REQUEST_DELAY = 0.3        # seconds between API calls

_GEO_COUNTRIES = [
    "United States", "United Kingdom", "Brazil", "Japan", "Germany",
    "France", "Australia", "Canada", "Mexico", "Sweden",
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class CandidateSong:
    title: str
    artist: str
    year: Optional[int] = None


@dataclass
class EnrichmentResult:
    genre: Optional[str] = None
    artist: Optional[str] = None
    year: Optional[int] = None
    requested_limit: int = 100
    api_results_processed: int = 0
    new_songs_inserted: int = 0
    duplicates_skipped: int = 0
    api_requests: int = 0
    stop_reason: str = ""


@dataclass
class Variant:
    """
    One named query strategy.

    Pages are picked randomly from [1, max_page].  The variant tracks its
    own duplicate ratio so the engine can retire saturated strategies early.
    """
    name: str
    fetch_fn: Callable[[int], list[CandidateSong]]
    max_page: int = _DEFAULT_RANDOM_PAGE_MAX
    tried_pages: set[int] = field(default_factory=set)
    new_count: int = 0
    skip_count: int = 0

    def next_page(self) -> Optional[int]:
        available = [p for p in range(1, self.max_page + 1) if p not in self.tried_pages]
        return random.choice(available) if available else None

    def record(self, page: int, new: int, skipped: int) -> None:
        self.tried_pages.add(page)
        self.new_count += new
        self.skip_count += skipped

    @property
    def dup_ratio(self) -> float:
        total = self.new_count + self.skip_count
        return self.skip_count / total if total > 0 else 0.0

    @property
    def is_exhausted(self) -> bool:
        return len(self.tried_pages) >= self.max_page

    def is_saturated(self) -> bool:
        return len(self.tried_pages) >= _MIN_VARIANT_TRIES and self.dup_ratio >= _DUP_THRESHOLD


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _song_key(title: str, artist: str) -> str:
    return f"{_normalize(artist)}||{_normalize(title)}"


def _load_existing_keys() -> set[str]:
    with get_session() as session:
        rows = session.exec(
            select(Song.title, Artist.name).join(Artist, Song.artist_id == Artist.id)
        ).all()
    return {_song_key(title, artist) for title, artist in rows}


# ---------------------------------------------------------------------------
# Last.fm REST helpers  (pylast does not expose page= on tag/artist methods)
# ---------------------------------------------------------------------------

_LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"


def _lastfm_get(api_key: str, method: str, **params) -> dict:
    import requests
    resp = requests.get(
        _LASTFM_API_URL,
        params={"method": method, "api_key": api_key, "format": "json",
                "limit": _PAGE_SIZE, **params},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# -- Discovery helpers (called once during variant-building) -----------------

def _get_related_tags(tag: str, api_key: str, limit: int = 9) -> list[str]:
    try:
        data = _lastfm_get(api_key, "tag.getSimilar", tag=tag)
        items = data.get("similartags", {}).get("tag", [])
        return [t["name"] for t in items[:limit] if isinstance(t, dict) and t.get("name")]
    except Exception:
        return []


def _get_tag_top_artists(tag: str, api_key: str, limit: int = 20) -> list[str]:
    try:
        data = _lastfm_get(api_key, "tag.getTopArtists", tag=tag, limit=limit)
        items = data.get("topartists", {}).get("artist", [])
        return [a["name"] for a in items if isinstance(a, dict) and a.get("name")]
    except Exception:
        return []


def _get_similar_artists(artist: str, api_key: str, limit: int = 15) -> list[str]:
    try:
        data = _lastfm_get(api_key, "artist.getSimilar", artist=artist, limit=limit)
        items = data.get("similarartists", {}).get("artist", [])
        return [a["name"] for a in items[:limit] if isinstance(a, dict) and a.get("name")]
    except Exception:
        return []


# -- Per-page fetch functions ------------------------------------------------

def _fetch_tag_top_tracks(tag: str, page: int, api_key: str) -> list[CandidateSong]:
    try:
        data = _lastfm_get(api_key, "tag.getTopTracks", tag=tag, page=page)
        tracks = data.get("tracks", {}).get("track", [])
        return [
            CandidateSong(title=t["name"], artist=t["artist"]["name"])
            for t in tracks
            if isinstance(t, dict) and t.get("name") and t.get("artist", {}).get("name")
        ]
    except Exception as exc:
        console.log(f"[dim]tag.getTopTracks({tag!r}, p={page}): {exc}[/dim]")
        return []


def _fetch_artist_top_tracks(artist: str, page: int, api_key: str) -> list[CandidateSong]:
    try:
        data = _lastfm_get(api_key, "artist.getTopTracks", artist=artist, page=page)
        tracks = data.get("toptracks", {}).get("track", [])
        return [
            CandidateSong(title=t["name"], artist=artist)
            for t in tracks
            if isinstance(t, dict) and t.get("name")
        ]
    except Exception as exc:
        console.log(f"[dim]artist.getTopTracks({artist!r}, p={page}): {exc}[/dim]")
        return []


def _fetch_geo_top_tracks(country: str, page: int, api_key: str) -> list[CandidateSong]:
    try:
        data = _lastfm_get(api_key, "geo.getTopTracks", country=country, page=page)
        tracks = data.get("tracks", {}).get("track", [])
        return [
            CandidateSong(title=t["name"], artist=t["artist"]["name"])
            for t in tracks
            if isinstance(t, dict) and t.get("name") and t.get("artist", {}).get("name")
        ]
    except Exception as exc:
        console.log(f"[dim]geo.getTopTracks({country!r}, p={page}): {exc}[/dim]")
        return []


def _fetch_by_year_mb(year: int, page: int) -> list[CandidateSong]:
    try:
        import musicbrainzngs as mb
        mb.set_useragent("MusicTeacherAI", "0.1")
        result = mb.search_recordings(date=str(year), limit=_PAGE_SIZE,
                                      offset=(page - 1) * _PAGE_SIZE)
        candidates = []
        for rec in result.get("recording-list", []):
            title = rec.get("title", "").strip()
            artist_name = next(
                (c["artist"]["name"] for c in rec.get("artist-credit", [])
                 if isinstance(c, dict) and "artist" in c),
                "",
            ).strip()
            if title and artist_name:
                candidates.append(CandidateSong(title=title, artist=artist_name, year=year))
        return candidates
    except Exception as exc:
        console.log(f"[dim]MusicBrainz year={year} p={page}: {exc}[/dim]")
        return []


def _fetch_by_artist_mb(artist: str, page: int) -> list[CandidateSong]:
    try:
        import musicbrainzngs as mb
        mb.set_useragent("MusicTeacherAI", "0.1")
        result = mb.search_recordings(artistname=artist, limit=_PAGE_SIZE,
                                      offset=(page - 1) * _PAGE_SIZE)
        candidates = []
        for rec in result.get("recording-list", []):
            title = rec.get("title", "").strip()
            artist_name = next(
                (c["artist"]["name"] for c in rec.get("artist-credit", [])
                 if isinstance(c, dict) and "artist" in c),
                "",
            ).strip()
            if title and artist_name:
                candidates.append(CandidateSong(title=title, artist=artist_name))
        return candidates
    except Exception as exc:
        console.log(f"[dim]MusicBrainz artist={artist!r} p={page}: {exc}[/dim]")
        return []


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
    """
    Build the full pool of query strategies for the given criterion.

    The list is shuffled before being returned so every enrichment run
    explores strategies in a different order.
    """
    variants: list[Variant] = []

    if genre:
        # ------------------------------------------------------------------ #
        # 1. Tag walk — seed tag + related tags                               #
        # ------------------------------------------------------------------ #
        seed_tags = [genre]
        if api_key:
            related = _get_related_tags(genre, api_key)
            if related:
                console.log(f"[dim]Related tags for {genre!r}: {related}[/dim]")
            seed_tags.extend(related)

        for tag in seed_tags:
            variants.append(Variant(
                name=f"tag:{tag}",
                fetch_fn=lambda p, t=tag: _fetch_tag_top_tracks(t, p, api_key),
                max_page=random_page_max,
            ))

        # ------------------------------------------------------------------ #
        # 2. Artist walk — top genre artists → their individual track lists   #
        # ------------------------------------------------------------------ #
        if api_key:
            top_artists = _get_tag_top_artists(genre, api_key)
            random.shuffle(top_artists)
            if top_artists:
                console.log(f"[dim]{len(top_artists)} seed artists for tag {genre!r}[/dim]")
            for art in top_artists[:15]:
                variants.append(Variant(
                    name=f"artist:{art}",
                    fetch_fn=lambda p, a=art: _fetch_artist_top_tracks(a, p, api_key),
                    max_page=min(random_page_max, 10),
                ))

        # ------------------------------------------------------------------ #
        # 3. Country chart walk                                               #
        # ------------------------------------------------------------------ #
        if api_key:
            countries = random.sample(_GEO_COUNTRIES, min(6, len(_GEO_COUNTRIES)))
            for country in countries:
                variants.append(Variant(
                    name=f"geo:{country}",
                    fetch_fn=lambda p, c=country: _fetch_geo_top_tracks(c, p, api_key),
                    max_page=min(random_page_max, 10),
                ))

    elif artist:
        # ------------------------------------------------------------------ #
        # 4. Direct artist top tracks                                         #
        # ------------------------------------------------------------------ #
        if api_key:
            variants.append(Variant(
                name=f"artist:{artist}",
                fetch_fn=lambda p: _fetch_artist_top_tracks(artist, p, api_key),
                max_page=random_page_max,
            ))

            # Similar artists walk
            similar = _get_similar_artists(artist, api_key)
            random.shuffle(similar)
            if similar:
                console.log(f"[dim]{len(similar)} similar artists for {artist!r}[/dim]")
            for sim in similar[:10]:
                variants.append(Variant(
                    name=f"similar:{sim}",
                    fetch_fn=lambda p, a=sim: _fetch_artist_top_tracks(a, p, api_key),
                    max_page=min(random_page_max, 5),
                ))

        # MusicBrainz fallback when Last.fm is not configured
        if not api_key or not variants:
            variants.append(Variant(
                name=f"mb:artist:{artist}",
                fetch_fn=lambda p: _fetch_by_artist_mb(artist, p),
                max_page=random_page_max,
            ))

    elif year:
        # ------------------------------------------------------------------ #
        # 5. MusicBrainz year search                                          #
        # ------------------------------------------------------------------ #
        variants.append(Variant(
            name=f"mb:year:{year}",
            fetch_fn=lambda p: _fetch_by_year_mb(year, p),
            max_page=random_page_max,
        ))

    random.shuffle(variants)
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

            artist_row = session.exec(
                select(Artist).where(Artist.name == c.artist)
            ).first()
            if not artist_row:
                artist_row = Artist(name=c.artist)
                session.add(artist_row)
                session.flush()

            # Guard against a race on the same artist from a prior page
            existing = session.exec(
                select(Song)
                .where(Song.title == c.title)
                .where(Song.artist_id == artist_row.id)
            ).first()
            if existing:
                existing_keys.add(key)
                skipped += 1
                continue

            session.add(Song(title=c.title, artist_id=artist_row.id, release_year=c.year))
            existing_keys.add(key)
            inserted += 1

        session.commit()

    return inserted, skipped


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
    report = PipelineReport("enrichment")
    report.set("requested_limit", limit)
    report.set("max_requests", max_requests)
    if genre:
        report.set("genre", genre)
    if artist:
        report.set("artist", artist)
    if year:
        report.set("year", year)

    criteria = " ".join(filter(None, [
        f"genre={genre!r}" if genre else "",
        f"artist={artist!r}" if artist else "",
        f"year={year}" if year else "",
    ]))
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

            time.sleep(_REQUEST_DELAY)

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

        from music_teacher_ai.pipeline.metadata_enrichment import enrich_metadata
        from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
        from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index
        from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

        console.print("[bold green]Step 1/4 – Enriching metadata...[/bold green]")
        enrich_metadata()

        console.print("[bold green]Step 2/4 – Downloading lyrics...[/bold green]")
        download_lyrics()

        console.print("[bold green]Step 3/4 – Building vocabulary index...[/bold green]")
        build_vocabulary_index()

        console.print("[bold green]Step 4/4 – Generating embeddings...[/bold green]")
        generate_embeddings()

    report_path = report.save()
    console.print(f"[dim]Report: {report_path}[/dim]")

    return result
