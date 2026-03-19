import random
from typing import Callable, Optional

from music_teacher_ai.pipeline.types import CandidateSong, Variant

REQUEST_DELAY = 0.3
PAGE_SIZE = 50
GEO_COUNTRIES = [
    "United States",
    "United Kingdom",
    "Brazil",
    "Japan",
    "Germany",
    "France",
    "Australia",
    "Canada",
    "Mexico",
    "Sweden",
]

_LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"


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
        time.sleep(REQUEST_DELAY)

    if genre and api_key:
        for page in range(1, pages_per_source + 1):
            _try_fetch(fetch_tag_top_tracks, genre, page, api_key)

    if artist:
        if api_key:
            for page in range(1, pages_per_source + 1):
                _try_fetch(fetch_artist_top_tracks, artist, page, api_key)
        else:
            for page in range(1, pages_per_source + 1):
                _try_fetch(fetch_by_artist_mb, artist, page)

    if year:
        for page in range(1, pages_per_source + 1):
            _try_fetch(fetch_by_year_mb, year, page)

    return all_candidates, api_requests


def _lastfm_get(api_key: str, method: str, **params) -> dict:
    import requests

    resp = requests.get(
        _LASTFM_API_URL,
        params={"method": method, "api_key": api_key, "format": "json", "limit": PAGE_SIZE, **params},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


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


def fetch_tag_top_tracks(tag: str, page: int, api_key: str) -> list[CandidateSong]:
    try:
        data = _lastfm_get(api_key, "tag.getTopTracks", tag=tag, page=page)
        tracks = data.get("tracks", {}).get("track", [])
        return [
            CandidateSong(title=t["name"], artist=t["artist"]["name"])
            for t in tracks
            if isinstance(t, dict) and t.get("name") and t.get("artist", {}).get("name")
        ]
    except Exception:
        return []


def fetch_artist_top_tracks(artist: str, page: int, api_key: str) -> list[CandidateSong]:
    try:
        data = _lastfm_get(api_key, "artist.getTopTracks", artist=artist, page=page)
        tracks = data.get("toptracks", {}).get("track", [])
        return [CandidateSong(title=t["name"], artist=artist) for t in tracks if isinstance(t, dict) and t.get("name")]
    except Exception:
        return []


def fetch_geo_top_tracks(country: str, page: int, api_key: str) -> list[CandidateSong]:
    try:
        data = _lastfm_get(api_key, "geo.getTopTracks", country=country, page=page)
        tracks = data.get("tracks", {}).get("track", [])
        return [
            CandidateSong(title=t["name"], artist=t["artist"]["name"])
            for t in tracks
            if isinstance(t, dict) and t.get("name") and t.get("artist", {}).get("name")
        ]
    except Exception:
        return []


def fetch_by_year_mb(year: int, page: int) -> list[CandidateSong]:
    try:
        import musicbrainzngs as mb

        mb.set_useragent("MusicTeacherAI", "0.1")
        result = mb.search_recordings(date=str(year), limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        candidates = []
        for rec in result.get("recording-list", []):
            title = rec.get("title", "").strip()
            artist_name = next(
                (c["artist"]["name"] for c in rec.get("artist-credit", []) if isinstance(c, dict) and "artist" in c),
                "",
            ).strip()
            if title and artist_name:
                candidates.append(CandidateSong(title=title, artist=artist_name, year=year))
        return candidates
    except Exception:
        return []


def fetch_by_artist_mb(artist: str, page: int) -> list[CandidateSong]:
    try:
        import musicbrainzngs as mb

        mb.set_useragent("MusicTeacherAI", "0.1")
        result = mb.search_recordings(artistname=artist, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        candidates = []
        for rec in result.get("recording-list", []):
            title = rec.get("title", "").strip()
            artist_name = next(
                (c["artist"]["name"] for c in rec.get("artist-credit", []) if isinstance(c, dict) and "artist" in c),
                "",
            ).strip()
            if title and artist_name:
                candidates.append(CandidateSong(title=title, artist=artist_name))
        return candidates
    except Exception:
        return []


def build_variants(
    *,
    genre: Optional[str],
    artist: Optional[str],
    year: Optional[int],
    api_key: str,
    random_page_max: int,
    min_artist_pages: int = 10,
    min_similar_pages: int = 5,
    geo_sources: int = 6,
) -> list[Variant]:
    variants: list[Variant] = []

    if genre:
        tags = [genre]
        if api_key:
            tags.extend(_get_related_tags(genre, api_key))
        for tag in tags:
            variants.append(
                Variant(
                    name=f"tag:{tag}",
                    fetch_fn=lambda p, t=tag: fetch_tag_top_tracks(t, p, api_key),
                    max_page=random_page_max,
                )
            )
        if api_key:
            top_artists = _get_tag_top_artists(genre, api_key)
            random.shuffle(top_artists)
            for art in top_artists[:15]:
                variants.append(
                    Variant(
                        name=f"artist:{art}",
                        fetch_fn=lambda p, a=art: fetch_artist_top_tracks(a, p, api_key),
                        max_page=min(random_page_max, min_artist_pages),
                    )
                )
            countries = random.sample(GEO_COUNTRIES, min(geo_sources, len(GEO_COUNTRIES)))
            for country in countries:
                variants.append(
                    Variant(
                        name=f"geo:{country}",
                        fetch_fn=lambda p, c=country: fetch_geo_top_tracks(c, p, api_key),
                        max_page=min(random_page_max, min_artist_pages),
                    )
                )
    elif artist:
        if api_key:
            variants.append(
                Variant(
                    name=f"artist:{artist}",
                    fetch_fn=lambda p: fetch_artist_top_tracks(artist, p, api_key),
                    max_page=random_page_max,
                )
            )
            similar = _get_similar_artists(artist, api_key)
            random.shuffle(similar)
            for sim in similar[:10]:
                variants.append(
                    Variant(
                        name=f"similar:{sim}",
                        fetch_fn=lambda p, a=sim: fetch_artist_top_tracks(a, p, api_key),
                        max_page=min(random_page_max, min_similar_pages),
                    )
                )
        if not api_key or not variants:
            variants.append(
                Variant(
                    name=f"mb:artist:{artist}",
                    fetch_fn=lambda p: fetch_by_artist_mb(artist, p),
                    max_page=random_page_max,
                )
            )
    elif year:
        variants.append(
            Variant(
                name=f"mb:year:{year}",
                fetch_fn=lambda p: fetch_by_year_mb(year, p),
                max_page=random_page_max,
            )
        )

    random.shuffle(variants)
    return variants

