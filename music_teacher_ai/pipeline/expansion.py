"""
On-demand database expansion triggered by search queries.

When a search returns fewer than EXPANSION_THRESHOLD results and the query
includes genre, artist, or year criteria, a background thread is started to:

  1. Fetch candidate songs from Last.fm / MusicBrainz using the same fetch
     helpers as the enrichment pipeline, but with tighter per-job limits.
  2. Write each discovered song to the ``song_candidates`` staging table
     (status = "pending").
  3. Immediately process the pending rows: normalise, deduplicate, and insert
     new songs into the main ``song`` table (status → "processed" or
     "rejected").

The caller receives its search response before any API call is made.

Limits per expansion job (not configurable at runtime):
  _MAX_API_REQUESTS = 20    — total Last.fm / MusicBrainz calls
  _MAX_CANDIDATES   = 200   — candidates to stage per job
  _PAGES_PER_SOURCE = 2     — pages fetched per source strategy
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import select

from music_teacher_ai.database.models import BackgroundJob, SongCandidate
from music_teacher_ai.database.repositories import SongRepository, SongCandidateRepository, song_key
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.fetchers import CandidateSong, fetch_candidates_for_expansion

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

EXPANSION_THRESHOLD = 10    # trigger expansion when search returns fewer results
_MAX_API_REQUESTS = 20      # max API calls per expansion job
_MAX_CANDIDATES = 200       # max candidates to stage per job
_PAGES_PER_SOURCE = 2       # pages to fetch per source strategy

# ---------------------------------------------------------------------------
# In-flight job tracker — prevents duplicate background threads
# ---------------------------------------------------------------------------

_active_jobs: set[str] = set()
_jobs_lock = threading.Lock()
_song_repo = SongRepository()
_candidate_repo = SongCandidateRepository()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_query_origin(
    genre: Optional[str] = None,
    artist: Optional[str] = None,
    year: Optional[int] = None,
    word: Optional[str] = None,
) -> str:
    """Build a canonical string that identifies a search query for dedup."""
    parts = []
    if genre:
        parts.append(f"genre:{genre}")
    if artist:
        parts.append(f"artist:{artist}")
    if year:
        parts.append(f"year:{year}")
    if word:
        parts.append(f"word:{word}")
    return "|".join(parts) if parts else "unknown"


def _stage_candidates(
    candidates: list[CandidateSong],
    query_origin: str,
    source_api: str,
) -> None:
    """Write discovered songs to the staging table with status='pending'."""
    now = datetime.now(timezone.utc).isoformat()
    with get_session() as session:
        for c in candidates:
            session.add(SongCandidate(
                title=c.title,
                artist=c.artist,
                year=c.year,
                source_api=source_api,
                query_origin=query_origin,
                created_at=now,
                status="pending",
            ))
        session.commit()


def process_candidates(query_origin: Optional[str] = None) -> dict:
    """
    Process pending rows from the staging table.

    For each pending SongCandidate:
      - artist+title already in Song table → mark "rejected"
      - otherwise → insert Artist (if needed) + Song → mark "processed"

    Returns {"processed": N, "rejected": N, "total": N}.
    """
    with get_session() as session:
        pending = _candidate_repo.pending(session, query_origin=query_origin)

    if not pending:
        return {"processed": 0, "rejected": 0, "total": 0}

    with get_session() as session:
        existing_keys = _song_repo.load_existing_keys(session)
    processed = 0
    rejected = 0

    with get_session() as session:
        for cand in pending:
            key = song_key(cand.title, cand.artist)
            if key in existing_keys:
                cand.status = "rejected"
                session.add(cand)
                rejected += 1
                continue

            artist_obj = _song_repo.get_or_create_artist(session, cand.artist)

            # Guard against a race between two sessions on the same title
            if _song_repo.song_exists(session, title=cand.title, artist_id=artist_obj.id):
                cand.status = "rejected"
                session.add(cand)
                existing_keys.add(key)
                rejected += 1
                continue

            _song_repo.add_song(
                session,
                title=cand.title,
                artist_id=artist_obj.id,
                release_year=cand.year,
                genre=cand.genre,
            )
            existing_keys.add(key)
            cand.status = "processed"
            session.add(cand)
            processed += 1

        session.commit()

    return {"processed": processed, "rejected": rejected, "total": len(pending)}


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_expansion(
    query_origin: str,
    genre: Optional[str],
    artist: Optional[str],
    year: Optional[int],
) -> None:
    """Fetch candidates → stage → process.  Runs in a daemon thread."""
    try:
        now = datetime.now(timezone.utc).isoformat()
        with get_session() as session:
            session.add(
                BackgroundJob(
                    job_type="expansion",
                    query_origin=query_origin,
                    status="running",
                    created_at=now,
                    updated_at=now,
                    details="background expansion job started",
                )
            )
            session.commit()

        from music_teacher_ai.config.settings import LASTFM_API_KEY
        api_key: str = LASTFM_API_KEY or ""

        def _load_keys():
            with get_session() as session:
                return _song_repo.load_existing_keys(session)

        all_candidates, api_requests = fetch_candidates_for_expansion(
            genre=genre,
            artist=artist,
            year=year,
            api_key=api_key,
            pages_per_source=_PAGES_PER_SOURCE,
            max_api_requests=_MAX_API_REQUESTS,
            max_candidates=_MAX_CANDIDATES,
            load_existing_keys=_load_keys,
            key_fn=song_key,
        )

        if not all_candidates:
            logger.info("Expansion for %r: no new candidates found", query_origin)
            with get_session() as session:
                row = session.exec(
                    select(BackgroundJob)
                    .where(BackgroundJob.query_origin == query_origin)
                    .where(BackgroundJob.status == "running")
                ).first()
                if row:
                    row.status = "done"
                    row.updated_at = datetime.now(timezone.utc).isoformat()
                    row.details = "no new candidates found"
                    session.add(row)
                    session.commit()
            return

        source_api = "lastfm" if api_key else "musicbrainz"
        _stage_candidates(all_candidates, query_origin, source_api)
        result = process_candidates(query_origin)
        logger.info(
            "Expansion for %r complete: staged=%d processed=%d rejected=%d requests=%d",
            query_origin,
            len(all_candidates),
            result["processed"],
            result["rejected"],
            api_requests,
        )
        with get_session() as session:
            row = session.exec(
                select(BackgroundJob)
                .where(BackgroundJob.query_origin == query_origin)
                .where(BackgroundJob.status == "running")
            ).first()
            if row:
                row.status = "done"
                row.updated_at = datetime.now(timezone.utc).isoformat()
                row.details = (
                    f"staged={len(all_candidates)} processed={result['processed']} "
                    f"rejected={result['rejected']} requests={api_requests}"
                )
                session.add(row)
                session.commit()
    except Exception as exc:
        logger.exception("Expansion for %r failed: %s", query_origin, exc)
        with get_session() as session:
            row = session.exec(
                select(BackgroundJob)
                .where(BackgroundJob.query_origin == query_origin)
                .where(BackgroundJob.status == "running")
            ).first()
            if row:
                row.status = "failed"
                row.updated_at = datetime.now(timezone.utc).isoformat()
                row.details = str(exc)
                session.add(row)
                session.commit()
    finally:
        with _jobs_lock:
            _active_jobs.discard(query_origin)


# ---------------------------------------------------------------------------
# Public trigger
# ---------------------------------------------------------------------------

def trigger_expansion(
    genre: Optional[str] = None,
    artist: Optional[str] = None,
    year: Optional[int] = None,
    word: Optional[str] = None,
) -> bool:
    """
    Start a background expansion job if none is running for this query.

    Returns True if a new job was started, False if already in-flight or if
    there are no actionable API criteria (word-only queries cannot be expanded
    via external APIs).
    """
    if not any([genre, artist, year]):
        return False

    origin = build_query_origin(genre, artist, year, word)

    with _jobs_lock:
        if origin in _active_jobs:
            return False
        _active_jobs.add(origin)

    thread = threading.Thread(
        target=_run_expansion,
        args=(origin, genre, artist, year),
        daemon=True,
        name=f"expansion-{origin}",
    )
    thread.start()
    logger.info("Database expansion triggered for query: %r", origin)
    return True
