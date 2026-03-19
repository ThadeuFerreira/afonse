from typing import Optional

from music_teacher_ai.pipeline.enrichment import (
    CandidateSong,
    _REQUEST_DELAY,
    _fetch_artist_top_tracks,
    _fetch_by_artist_mb,
    _fetch_by_year_mb,
    _fetch_tag_top_tracks,
)

__all__ = ["CandidateSong", "fetch_candidates_for_expansion"]


def fetch_candidates_for_expansion(
    *,
    genre: Optional[str],
    artist: Optional[str],
    year: Optional[int],
    api_key: str,
    pages_per_source: int,
    max_api_requests: int,
    max_candidates: int,
    load_existing_keys: callable,
    key_fn: callable,
):
    import time

    existing_keys = load_existing_keys()
    all_candidates: list[CandidateSong] = []
    api_requests = 0

    def _try_fetch(fn, *args) -> None:
        nonlocal api_requests
        if api_requests >= max_api_requests or len(all_candidates) >= max_candidates:
            return
        try:
            batch = fn(*args)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("fetch %s failed: %s", fn.__name__, exc)
            return
        api_requests += 1
        for candidate in batch:
            key = key_fn(candidate.title, candidate.artist)
            if key in existing_keys:
                continue
            all_candidates.append(candidate)
            existing_keys.add(key)
            if len(all_candidates) >= max_candidates:
                break
        time.sleep(_REQUEST_DELAY)

    if genre and api_key:
        for page in range(1, pages_per_source + 1):
            _try_fetch(_fetch_tag_top_tracks, genre, page, api_key)

    if artist:
        if api_key:
            for page in range(1, pages_per_source + 1):
                _try_fetch(_fetch_artist_top_tracks, artist, page, api_key)
        else:
            for page in range(1, pages_per_source + 1):
                _try_fetch(_fetch_by_artist_mb, artist, page)

    if year:
        for page in range(1, pages_per_source + 1):
            _try_fetch(_fetch_by_year_mb, year, page)

    return all_candidates, api_requests

