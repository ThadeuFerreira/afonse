"""
Unit tests for the database enrichment pipeline.

All tests mock at the _build_variants level or at the DB level so they
never touch real external APIs.
"""

from unittest.mock import patch

import pytest

from music_teacher_ai.pipeline.enrichment import (
    _GLOBAL_DUP_STOP,
    _MIN_VARIANT_TRIES,
    CandidateSong,
    EnrichmentResult,
    Variant,
    _normalize,
    _song_key,
)
from music_teacher_ai.pipeline.observers import NullObserver

# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------


def test_normalize_lowercase():
    assert _normalize("Hello World") == "hello world"


def test_normalize_removes_punctuation():
    assert _normalize("Don't Stop Believin'") == "dont stop believin"


def test_normalize_collapses_whitespace():
    assert _normalize("  hello   world  ") == "hello world"


def test_song_key_order():
    key = _song_key("Imagine", "John Lennon")
    assert "john lennon" in key
    assert "imagine" in key


def test_song_key_case_insensitive():
    assert _song_key("IMAGINE", "JOHN LENNON") == _song_key("imagine", "john lennon")


def test_song_key_punctuation_insensitive():
    assert _song_key("Don't Stop Believin'", "Journey") == _song_key(
        "Dont Stop Believin", "Journey"
    )


# ---------------------------------------------------------------------------
# Variant state machine
# ---------------------------------------------------------------------------


def _make_variant(name="v", max_page=5) -> Variant:
    return Variant(name=name, fetch_fn=lambda p: [], max_page=max_page)


def test_variant_next_page_picks_from_range():
    v = _make_variant(max_page=5)
    pages = {v.next_page() for _ in range(100)}
    assert pages.issubset(set(range(1, 6)))


def test_variant_next_page_none_when_exhausted():
    v = _make_variant(max_page=2)
    v.record(1, 0, 0)
    v.record(2, 0, 0)
    assert v.next_page() is None


def test_variant_is_exhausted():
    v = _make_variant(max_page=2)
    assert not v.is_exhausted
    v.record(1, 0, 0)
    v.record(2, 0, 0)
    assert v.is_exhausted


def test_variant_is_not_saturated_below_min_tries():
    v = _make_variant()
    for i in range(1, _MIN_VARIANT_TRIES):
        v.record(i, 0, 100)  # all duplicates
    assert not v.is_saturated()


def test_variant_is_saturated_after_min_tries_with_high_dup():
    v = _make_variant(max_page=20)
    for i in range(1, _MIN_VARIANT_TRIES + 1):
        v.record(i, 0, 100)  # all duplicates
    assert v.is_saturated()


def test_variant_not_saturated_when_dup_ratio_low():
    v = _make_variant(max_page=20)
    for i in range(1, _MIN_VARIANT_TRIES + 1):
        v.record(i, 50, 5)  # low dup ratio
    assert not v.is_saturated()


def test_variant_dup_ratio():
    v = _make_variant()
    v.record(1, 10, 40)
    assert abs(v.dup_ratio - 0.8) < 0.01


# ---------------------------------------------------------------------------
# DB helpers — _load_existing_keys / _insert_candidates
# ---------------------------------------------------------------------------


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path / "reports"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.database.sqlite as db
    import music_teacher_ai.pipeline.reporter as rep

    importlib.reload(s)
    importlib.reload(db)
    importlib.reload(rep)
    db.create_db()


def test_load_existing_keys_empty(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from music_teacher_ai.pipeline.enrichment import _load_existing_keys

    assert _load_existing_keys() == set()


def test_load_existing_keys_returns_normalized(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        a = Artist(name="The Beatles")
        session.add(a)
        session.flush()
        session.add(Song(title="Hey Jude", artist_id=a.id))
        session.commit()

    from music_teacher_ai.pipeline.enrichment import _load_existing_keys

    assert _song_key("Hey Jude", "The Beatles") in _load_existing_keys()


def test_insert_candidates_inserts_new(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from sqlmodel import select

    from music_teacher_ai.database.models import Song
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.enrichment import _insert_candidates

    inserted, skipped = _insert_candidates(
        [CandidateSong("Bohemian Rhapsody", "Queen"), CandidateSong("We Will Rock You", "Queen")],
        set(),
    )
    assert inserted == 2
    assert skipped == 0
    with get_session() as session:
        assert len(session.exec(select(Song)).all()) == 2


def test_insert_candidates_skips_known(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from music_teacher_ai.pipeline.enrichment import _insert_candidates

    inserted, skipped = _insert_candidates(
        [CandidateSong("Imagine", "John Lennon")],
        {_song_key("Imagine", "John Lennon")},
    )
    assert inserted == 0
    assert skipped == 1


def test_insert_candidates_deduplicates_within_batch(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    from music_teacher_ai.pipeline.enrichment import _insert_candidates

    inserted, skipped = _insert_candidates(
        [CandidateSong("Roxanne", "The Police"), CandidateSong("Roxanne", "The Police")],
        set(),
    )
    assert inserted == 1
    assert skipped == 1


# ---------------------------------------------------------------------------
# enrich_database() — mock _build_variants for clean isolation
# ---------------------------------------------------------------------------


def _make_db(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    import music_teacher_ai.pipeline.enrichment as enr
    import music_teacher_ai.pipeline.reporter as rep

    monkeypatch.setattr(rep, "REPORTS_DIR", tmp_path / "reports", raising=False)
    return enr


def _simple_variant(name, songs_per_page, max_page=5):
    """Variant that returns a fixed set of unique songs per page."""
    seen_pages = set()

    def fetch(page):
        seen_pages.add(page)
        return [CandidateSong(f"{s.title}@p{page}", s.artist) for s in songs_per_page]

    return Variant(name=name, fetch_fn=fetch, max_page=max_page)


def test_enrich_by_genre_inserts_songs(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    def fake_build(genre, artist, year, api_key, random_page_max):
        def fetch(page):
            return (
                [CandidateSong("Song A", "Artist X"), CandidateSong("Song B", "Artist Y")]
                if page == 1
                else []
            )

        return [Variant(name="tag:jazz", fetch_fn=fetch, max_page=3)]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(genre="jazz", limit=10, run_pipeline=False)

    assert result.new_songs_inserted == 2
    assert result.genre == "jazz"


def test_enrich_by_artist_inserts_songs(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    def fake_build(genre, artist, year, api_key, random_page_max):
        return [
            Variant(
                name=f"artist:{artist}",
                fetch_fn=lambda p: [CandidateSong("Hello", "Adele")] if p == 1 else [],
                max_page=3,
            )
        ]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(artist="Adele", limit=10, run_pipeline=False)

    assert result.new_songs_inserted == 1
    assert result.artist == "Adele"


def test_enrich_by_year_inserts_songs(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    def fake_build(genre, artist, year, api_key, random_page_max):
        return [
            Variant(
                name=f"mb:year:{year}",
                fetch_fn=lambda p: [CandidateSong("Waterfalls", "TLC", 1995)] if p == 1 else [],
                max_page=3,
            )
        ]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(year=1995, limit=10, run_pipeline=False)

    assert result.new_songs_inserted == 1
    assert result.year == 1995


def test_enrich_respects_limit(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    call_n = [0]

    def fetch(page):
        call_n[0] += 1
        offset = (page - 1) * 3
        return [CandidateSong(f"Song {offset+i}", "Big Artist") for i in range(3)]

    def fake_build(genre, artist, year, api_key, random_page_max):
        return [Variant(name="test", fetch_fn=fetch, max_page=50)]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(artist="Big Artist", limit=5, run_pipeline=False)

    assert result.new_songs_inserted == 5


def test_enrich_retires_saturated_variant(tmp_path, monkeypatch):
    """A variant that only produces duplicates is retired after MIN_VARIANT_TRIES."""
    enr = _make_db(tmp_path, monkeypatch)

    # Pre-populate with songs that the fake variant will keep returning
    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        a = Artist(name="Same Artist")
        session.add(a)
        session.flush()
        for i in range(10):
            session.add(Song(title=f"Same Song {i}", artist_id=a.id))
        session.commit()

    def fetch(page):
        return [CandidateSong(f"Same Song {i}", "Same Artist") for i in range(10)]

    def fake_build(genre, artist, year, api_key, random_page_max):
        return [Variant(name="saturated", fetch_fn=fetch, max_page=50)]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(genre="rock", limit=100, max_requests=200, run_pipeline=False)

    assert result.new_songs_inserted == 0
    assert result.stop_reason in ("all_variants_exhausted", "global_duplicate_threshold")


def test_enrich_stops_on_global_dup_threshold(tmp_path, monkeypatch):
    """Loop stops after _GLOBAL_DUP_STOP consecutive all-dup pages."""
    enr = _make_db(tmp_path, monkeypatch)

    # One song pre-populated
    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        a = Artist(name="X")
        session.add(a)
        session.flush()
        session.add(Song(title="Y", artist_id=a.id))
        session.commit()

    # Two variants, both always return the same duplicate song.
    # min_variant_tries is set well above _GLOBAL_DUP_STOP so per-variant
    # saturation cannot fire before the global consecutive-dup threshold.
    def dup_fetch(page):
        return [CandidateSong("Y", "X")]

    def fake_build(genre, artist, year, api_key, random_page_max):
        return [
            Variant(
                name="v1", fetch_fn=dup_fetch, max_page=500, min_variant_tries=_GLOBAL_DUP_STOP * 10
            ),
            Variant(
                name="v2", fetch_fn=dup_fetch, max_page=500, min_variant_tries=_GLOBAL_DUP_STOP * 10
            ),
        ]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(genre="rock", limit=100, max_requests=500, run_pipeline=False)

    assert result.stop_reason == "global_duplicate_threshold"
    assert result.api_requests <= _GLOBAL_DUP_STOP + 2  # allow for a couple of variant checks


def test_enrich_skips_duplicates(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        a = Artist(name="Coldplay")
        session.add(a)
        session.flush()
        session.add(Song(title="Yellow", artist_id=a.id))
        session.commit()

    def fake_build(genre, artist, year, api_key, random_page_max):
        return [
            Variant(
                name="test",
                fetch_fn=lambda p: (
                    [
                        CandidateSong("Yellow", "Coldplay"),
                        CandidateSong("The Scientist", "Coldplay"),
                    ]
                    if p == 1
                    else []
                ),
                max_page=1,
            )
        ]

    monkeypatch.setattr(enr, "_build_variants", fake_build)
    result = enr.enrich_database(artist="Coldplay", limit=10, run_pipeline=False)

    assert result.new_songs_inserted == 1
    assert result.duplicates_skipped >= 1


def test_enrich_raises_without_criteria(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="at least one"):
        enr.enrich_database(run_pipeline=False)


def test_enrich_caps_limit_at_1000(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(enr, "_build_variants", lambda *a, **k: [])
    result = enr.enrich_database(genre="pop", limit=99999, run_pipeline=False)
    assert result.requested_limit == 1000


def test_enrich_stop_reason_limit_reached(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    page_counter = [0]

    def fetch(page):
        page_counter[0] += 1
        return [CandidateSong(f"Song {page * 10 + i}", "Artist") for i in range(10)]

    monkeypatch.setattr(
        enr, "_build_variants", lambda *a, **k: [Variant(name="t", fetch_fn=fetch, max_page=50)]
    )
    result = enr.enrich_database(genre="rock", limit=5, run_pipeline=False)

    assert result.new_songs_inserted == 5
    assert result.stop_reason == "limit_reached"


def test_enrich_max_requests_respected(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)

    def fetch(page):
        return [CandidateSong(f"Song {page * 10 + i}", "Artist") for i in range(10)]

    monkeypatch.setattr(
        enr, "_build_variants", lambda *a, **k: [Variant(name="t", fetch_fn=fetch, max_page=200)]
    )
    result = enr.enrich_database(genre="rock", limit=1000, max_requests=3, run_pipeline=False)

    assert result.api_requests <= 3
    assert result.stop_reason == "max_requests_reached"


def test_enrich_legacy_max_pages_param(tmp_path, monkeypatch):
    """max_pages= is accepted as a legacy alias for max_requests."""
    enr = _make_db(tmp_path, monkeypatch)

    def fetch(page):
        return [CandidateSong(f"Song {page * 10 + i}", "Artist") for i in range(10)]

    monkeypatch.setattr(
        enr, "_build_variants", lambda *a, **k: [Variant(name="t", fetch_fn=fetch, max_page=200)]
    )
    result = enr.enrich_database(genre="rock", limit=1000, max_pages=2, run_pipeline=False)

    assert result.api_requests <= 2


def test_enrich_headless_observer(tmp_path, monkeypatch):
    enr = _make_db(tmp_path, monkeypatch)
    monkeypatch.setattr(enr, "_build_variants", lambda *a, **k: [])
    result = enr.enrich_database(genre="pop", limit=10, run_pipeline=False, observer=NullObserver())
    assert result.requested_limit == 10


# ---------------------------------------------------------------------------
# REST endpoint
# ---------------------------------------------------------------------------


def test_rest_enrich_valid():
    from fastapi.testclient import TestClient

    fake_result = EnrichmentResult(
        genre="jazz",
        requested_limit=50,
        new_songs_inserted=12,
        duplicates_skipped=38,
        api_requests=5,
        stop_reason="limit_reached",
    )
    with patch("music_teacher_ai.pipeline.enrichment.enrich_database", return_value=fake_result):
        from music_teacher_ai.api.rest_api import app

        resp = TestClient(app).post("/enrich", json={"genre": "jazz", "limit": 50})

    assert resp.status_code == 200
    data = resp.json()
    assert data["new_songs_inserted"] == 12
    assert data["duplicates_skipped"] == 38
    assert data["requested"] == 50


def test_rest_enrich_no_criteria():
    from fastapi.testclient import TestClient

    from music_teacher_ai.api.rest_api import app

    resp = TestClient(app).post("/enrich", json={"limit": 100})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# MCP dispatch
# ---------------------------------------------------------------------------


def test_mcp_enrich_valid():
    fake_result = EnrichmentResult(
        genre="rock",
        requested_limit=100,
        new_songs_inserted=20,
        duplicates_skipped=5,
        stop_reason="limit_reached",
    )
    with patch("music_teacher_ai.pipeline.enrichment.enrich_database", return_value=fake_result):
        from music_teacher_ai.api.mcp_server import dispatch

        result = dispatch("enrich_database", {"genre": "rock", "limit": 100})

    assert result["new_songs_inserted"] == 20
    assert result["duplicates_skipped"] == 5


def test_mcp_enrich_no_criteria():
    from music_teacher_ai.api.mcp_server import dispatch

    result = dispatch("enrich_database", {})
    assert "error" in result


def test_mcp_enrich_tool_in_tools_list():
    from music_teacher_ai.api.mcp_server import TOOLS

    assert "enrich_database" in {t["name"] for t in TOOLS}
