"""
Tests for the on-demand database expansion pipeline.

All tests use an in-memory/tmp database and mock external API calls so they
never hit real network endpoints.
"""
import threading

import pytest
from sqlmodel import select

from music_teacher_ai.pipeline.enrichment import CandidateSong
from music_teacher_ai.pipeline.expansion import (
    _active_jobs,
    _jobs_lock,
    build_query_origin,
    process_candidates,
    trigger_expansion,
)

# ---------------------------------------------------------------------------
# DB fixture — same pattern as test_enrichment.py
# ---------------------------------------------------------------------------

def _make_db(tmp_path, monkeypatch):
    """Point the whole stack at a fresh SQLite database in tmp_path."""
    from music_teacher_ai.config import settings as cfg_settings

    db_path = tmp_path / "test.db"
    monkeypatch.setattr(cfg_settings, "DATABASE_PATH", db_path)

    import music_teacher_ai.database.sqlite as db_mod
    monkeypatch.setattr(db_mod, "DATABASE_PATH", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    from sqlmodel import SQLModel, create_engine
    test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    monkeypatch.setattr(db_mod, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    # Ensure active_jobs set is clean between tests
    with _jobs_lock:
        _active_jobs.clear()

    import music_teacher_ai.pipeline.expansion as exp_mod
    monkeypatch.setattr(exp_mod, "_active_jobs", _active_jobs)
    return exp_mod


# ---------------------------------------------------------------------------
# build_query_origin
# ---------------------------------------------------------------------------

def test_query_origin_genre():
    assert build_query_origin(genre="jazz") == "genre:jazz"


def test_query_origin_artist():
    assert build_query_origin(artist="Adele") == "artist:Adele"


def test_query_origin_year():
    assert build_query_origin(year=2000) == "year:2000"


def test_query_origin_combined():
    origin = build_query_origin(genre="pop", artist="Taylor Swift", year=2020)
    assert "genre:pop" in origin
    assert "artist:Taylor Swift" in origin
    assert "year:2020" in origin


def test_query_origin_word_only():
    assert build_query_origin(word="love") == "word:love"


def test_query_origin_empty():
    assert build_query_origin() == "unknown"


# ---------------------------------------------------------------------------
# _stage_candidates
# ---------------------------------------------------------------------------

def test_stage_candidates_writes_pending(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import SongCandidate
    from music_teacher_ai.database.sqlite import get_session

    candidates = [
        CandidateSong(title="Song A", artist="Artist 1", year=2010),
        CandidateSong(title="Song B", artist="Artist 2"),
    ]
    exp._stage_candidates(candidates, "genre:rock", "lastfm")

    with get_session() as session:
        rows = session.exec(select(SongCandidate)).all()

    assert len(rows) == 2
    assert all(r.status == "pending" for r in rows)
    assert all(r.query_origin == "genre:rock" for r in rows)
    assert all(r.source_api == "lastfm" for r in rows)
    titles = {r.title for r in rows}
    assert titles == {"Song A", "Song B"}


def test_stage_candidates_preserves_year(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import SongCandidate
    from music_teacher_ai.database.sqlite import get_session

    exp._stage_candidates([CandidateSong("T", "A", year=1999)], "year:1999", "musicbrainz")
    with get_session() as session:
        row = session.exec(select(SongCandidate)).first()
    assert row.year == 1999


# ---------------------------------------------------------------------------
# process_candidates
# ---------------------------------------------------------------------------

def test_process_candidates_inserts_new_song(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import Song
    from music_teacher_ai.database.sqlite import get_session

    exp._stage_candidates([CandidateSong("New Song", "New Artist")], "genre:pop", "lastfm")
    result = exp.process_candidates()

    assert result["processed"] == 1
    assert result["rejected"] == 0
    assert result["total"] == 1

    with get_session() as session:
        songs = session.exec(select(Song)).all()
    assert any(s.title == "New Song" for s in songs)


def test_process_candidates_rejects_existing_song(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    # Pre-populate the main DB with the same song
    with get_session() as session:
        a = Artist(name="Known Artist")
        session.add(a)
        session.flush()
        session.add(Song(title="Known Song", artist_id=a.id))
        session.commit()

    exp._stage_candidates([CandidateSong("Known Song", "Known Artist")], "artist:Known Artist", "lastfm")
    result = exp.process_candidates()

    assert result["rejected"] == 1
    assert result["processed"] == 0


def test_process_candidates_returns_zero_when_no_pending(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch)
    result = process_candidates()
    assert result == {"processed": 0, "rejected": 0, "total": 0}


def test_process_candidates_filters_by_query_origin(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import Song
    from music_teacher_ai.database.sqlite import get_session

    exp._stage_candidates([CandidateSong("Song X", "Artist X")], "genre:rock", "lastfm")
    exp._stage_candidates([CandidateSong("Song Y", "Artist Y")], "genre:jazz", "lastfm")

    # Only process the jazz candidates
    result = exp.process_candidates(query_origin="genre:jazz")
    assert result["processed"] == 1

    with get_session() as session:
        titles = {s.title for s in session.exec(select(Song)).all()}
    # rock candidate still pending, jazz inserted
    assert "Song Y" in titles
    assert "Song X" not in titles


def test_process_candidates_marks_status_correctly(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    from music_teacher_ai.database.models import Artist, Song, SongCandidate
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        a = Artist(name="Existing Artist")
        session.add(a)
        session.flush()
        session.add(Song(title="Existing Song", artist_id=a.id))
        session.commit()

    exp._stage_candidates(
        [
            CandidateSong("Existing Song", "Existing Artist"),  # dup → rejected
            CandidateSong("Brand New Song", "New Artist"),      # new → processed
        ],
        "artist:Existing Artist",
        "lastfm",
    )
    exp.process_candidates()

    with get_session() as session:
        rows = {r.title: r.status for r in session.exec(select(SongCandidate)).all()}
    assert rows["Existing Song"] == "rejected"
    assert rows["Brand New Song"] == "processed"


# ---------------------------------------------------------------------------
# trigger_expansion
# ---------------------------------------------------------------------------

def test_trigger_expansion_returns_false_word_only(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch)
    assert trigger_expansion(word="love") is False


def test_trigger_expansion_returns_false_no_criteria(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch)
    assert trigger_expansion() is False


def test_trigger_expansion_starts_thread_for_genre(tmp_path, monkeypatch):
    exp = _make_db(tmp_path, monkeypatch)
    started = threading.Event()

    def fake_run(origin, genre, artist, year):
        started.set()

    monkeypatch.setattr(exp, "_run_expansion", fake_run)
    result = trigger_expansion(genre="jazz")
    assert result is True
    started.wait(timeout=2)
    assert started.is_set()


def test_trigger_expansion_deduplicates_active_jobs(tmp_path, monkeypatch):
    _make_db(tmp_path, monkeypatch)
    barrier = threading.Barrier(2)
    released = threading.Event()

    def fake_run(origin, genre, artist, year):
        barrier.wait(timeout=2)
        released.wait(timeout=2)

    import music_teacher_ai.pipeline.expansion as exp_mod
    monkeypatch.setattr(exp_mod, "_run_expansion", fake_run)

    first = trigger_expansion(genre="rock")
    second = trigger_expansion(genre="rock")  # same query — should be deduplicated

    barrier.wait(timeout=2)
    released.set()

    assert first is True
    assert second is False


# ---------------------------------------------------------------------------
# REST endpoint — /search returns new format
# ---------------------------------------------------------------------------

@pytest.fixture
def rest_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlmodel import SQLModel, create_engine

    import music_teacher_ai.database.sqlite as db_mod
    from music_teacher_ai.config import settings as cfg_settings

    db_path = tmp_path / "rest_test.db"
    monkeypatch.setattr(cfg_settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATABASE_PATH", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    monkeypatch.setattr(db_mod, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    from music_teacher_ai.api.rest_api import app
    return TestClient(app, raise_server_exceptions=True)


def test_search_returns_results_and_expansion_flag(rest_client):
    resp = rest_client.get("/search", params={"word": "love"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data
    assert "database_expansion_triggered" in data
    assert isinstance(data["results"], list)
    assert isinstance(data["database_expansion_triggered"], bool)


def test_search_triggers_expansion_when_results_below_threshold(rest_client, monkeypatch):
    triggered = []

    import music_teacher_ai.api.rest_api as rest_mod
    monkeypatch.setattr(
        rest_mod,
        "keyword_search",
        # Can't monkeypatch the route function directly; patch trigger_expansion instead
        rest_mod.keyword_search,
    )

    import music_teacher_ai.pipeline.expansion as exp_mod
    monkeypatch.setattr(exp_mod, "trigger_expansion",
                        lambda **kw: triggered.append(kw) or True)

    resp = rest_client.get("/search", params={"genre": "synthwave"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["database_expansion_triggered"] is True


def test_search_no_expansion_for_word_only(rest_client, monkeypatch):
    triggered = []
    import music_teacher_ai.pipeline.expansion as exp_mod
    monkeypatch.setattr(exp_mod, "trigger_expansion",
                        lambda **kw: triggered.append(kw) or False)

    resp = rest_client.get("/search", params={"word": "never"})
    assert resp.status_code == 200
    assert resp.json()["database_expansion_triggered"] is False


# ---------------------------------------------------------------------------
# MCP — search_songs dispatch returns new format + process_candidates tool
# ---------------------------------------------------------------------------

def test_mcp_search_songs_returns_new_format(tmp_path, monkeypatch):
    from sqlmodel import SQLModel, create_engine

    import music_teacher_ai.database.sqlite as db_mod
    from music_teacher_ai.config import settings as cfg_settings

    db_path = tmp_path / "mcp_test.db"
    monkeypatch.setattr(cfg_settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATABASE_PATH", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    monkeypatch.setattr(db_mod, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    from music_teacher_ai.api.mcp_server import dispatch
    result = dispatch("search_songs", {"word": "love"})
    assert "results" in result
    assert "database_expansion_triggered" in result


def test_mcp_process_candidates_tool_in_tools_list():
    from music_teacher_ai.api.mcp_server import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "process_candidates" in names


def test_mcp_process_candidates_dispatch(tmp_path, monkeypatch):
    from sqlmodel import SQLModel, create_engine

    import music_teacher_ai.database.sqlite as db_mod
    from music_teacher_ai.config import settings as cfg_settings

    db_path = tmp_path / "mcp_proc.db"
    monkeypatch.setattr(cfg_settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATABASE_PATH", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    monkeypatch.setattr(db_mod, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    from music_teacher_ai.api.mcp_server import dispatch
    result = dispatch("process_candidates", {})
    assert result == {"processed": 0, "rejected": 0, "total": 0}


def test_mcp_process_candidates_with_query_origin(tmp_path, monkeypatch):
    from sqlmodel import SQLModel, create_engine

    import music_teacher_ai.database.sqlite as db_mod
    from music_teacher_ai.config import settings as cfg_settings

    db_path = tmp_path / "mcp_proc2.db"
    monkeypatch.setattr(cfg_settings, "DATABASE_PATH", db_path)
    monkeypatch.setattr(db_mod, "DATABASE_PATH", db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    test_engine = create_engine(f"sqlite:///{db_path}", echo=False)
    monkeypatch.setattr(db_mod, "engine", test_engine)
    SQLModel.metadata.create_all(test_engine)

    import music_teacher_ai.pipeline.expansion as exp_mod
    monkeypatch.setattr(exp_mod, "_active_jobs", set())

    # Stage a candidate first
    exp_mod._stage_candidates(
        [CandidateSong("MCP Song", "MCP Artist")], "genre:mcp", "lastfm"
    )

    from music_teacher_ai.api.mcp_server import dispatch
    result = dispatch("process_candidates", {"query_origin": "genre:mcp"})
    assert result["processed"] == 1
