"""
Tests for the Minimal Mode demo loader.

Validates:
  - demo_songs.json structure and completeness
  - is_db_empty() detection
  - load_demo_songs() inserts songs/artists/lyrics idempotently
  - auto_load_demo_if_needed() activates on empty DB only
  - print_minimal_banner() and credential warning output
"""
import json
from pathlib import Path

import pytest

_DEMO_JSON = Path(__file__).resolve().parent.parent / "data" / "demo_songs.json"


# ---------------------------------------------------------------------------
# Demo dataset file
# ---------------------------------------------------------------------------

class TestDemoDataset:
    def test_file_exists(self):
        assert _DEMO_JSON.exists(), "data/demo_songs.json is missing"

    def test_is_valid_json(self):
        data = json.loads(_DEMO_JSON.read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_has_ten_songs(self):
        data = json.loads(_DEMO_JSON.read_text(encoding="utf-8"))
        assert len(data) == 10

    def test_each_entry_has_required_fields(self):
        data = json.loads(_DEMO_JSON.read_text(encoding="utf-8"))
        for entry in data:
            assert "title" in entry, f"Missing 'title' in {entry}"
            assert "artist" in entry, f"Missing 'artist' in {entry}"
            assert "year" in entry, f"Missing 'year' in {entry}"
            assert "lyrics" in entry, f"Missing 'lyrics' in {entry}"

    def test_lyrics_are_non_empty(self):
        data = json.loads(_DEMO_JSON.read_text(encoding="utf-8"))
        for entry in data:
            assert len(entry["lyrics"].strip()) > 10, \
                f"Lyrics too short for {entry['title']}"

    def test_years_are_integers(self):
        data = json.loads(_DEMO_JSON.read_text(encoding="utf-8"))
        for entry in data:
            assert isinstance(entry["year"], int)

    def test_known_songs_present(self):
        data = json.loads(_DEMO_JSON.read_text(encoding="utf-8"))
        titles = {e["title"] for e in data}
        for expected in ("Imagine", "Hey Jude", "Bohemian Rhapsody", "Yesterday"):
            assert expected in titles, f"Expected '{expected}' in demo dataset"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """Provide an isolated empty database for each test."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import importlib

    import music_teacher_ai.config.settings as _s
    import music_teacher_ai.database.sqlite as _db
    importlib.reload(_s)
    importlib.reload(_db)
    _db.create_db()
    yield tmp_path


# ---------------------------------------------------------------------------
# is_db_empty()
# ---------------------------------------------------------------------------

class TestIsDbEmpty:
    def test_empty_after_create(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        assert ldr.is_db_empty() is True

    def test_not_empty_after_insert(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        from music_teacher_ai.database.models import Artist, Song
        from music_teacher_ai.database.sqlite import get_session
        importlib.reload(ldr)

        with get_session() as session:
            a = Artist(name="Test")
            session.add(a)
            session.flush()
            session.add(Song(title="Test Song", artist_id=a.id))
            session.commit()

        assert ldr.is_db_empty() is False


# ---------------------------------------------------------------------------
# load_demo_songs()
# ---------------------------------------------------------------------------

class TestLoadDemoSongs:
    def test_inserts_ten_songs(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        count = ldr.load_demo_songs()
        assert count == 10

    def test_songs_present_after_load(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()

        from sqlmodel import select

        from music_teacher_ai.database.models import Song
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            songs = session.exec(select(Song)).all()
        assert len(songs) == 10

    def test_artists_created(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()

        from sqlmodel import select

        from music_teacher_ai.database.models import Artist
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            artists = session.exec(select(Artist)).all()
        assert len(artists) >= 7   # 10 songs, some share artists (The Beatles ×2)

    def test_lyrics_inserted(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()

        from sqlmodel import select

        from music_teacher_ai.database.models import Lyrics
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            lyric_rows = session.exec(select(Lyrics)).all()
        assert len(lyric_rows) == 10

    def test_idempotent_second_call(self, fresh_db):
        """Calling load_demo_songs() twice must not duplicate rows."""
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()
        second = ldr.load_demo_songs()
        assert second == 0   # nothing new inserted

        from sqlmodel import select

        from music_teacher_ai.database.models import Song
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            count = len(session.exec(select(Song)).all())
        assert count == 10

    def test_shared_artists_deduplicated(self, fresh_db):
        """The Beatles appear twice — only one Artist row should be created."""
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()

        from sqlmodel import select

        from music_teacher_ai.database.models import Artist
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            beatles = session.exec(
                select(Artist).where(Artist.name == "The Beatles")
            ).all()
        assert len(beatles) == 1


# ---------------------------------------------------------------------------
# auto_load_demo_if_needed()
# ---------------------------------------------------------------------------

class TestAutoLoad:
    def test_activates_on_empty_db(self, fresh_db, capsys):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        activated = ldr.auto_load_demo_if_needed()
        assert activated is True

    def test_does_not_activate_on_populated_db(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()          # populate
        activated = ldr.auto_load_demo_if_needed()
        assert activated is False

    def test_no_duplicate_insert_on_second_call(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.auto_load_demo_if_needed()   # first: loads
        ldr.auto_load_demo_if_needed()   # second: skips

        from sqlmodel import select

        from music_teacher_ai.database.models import Song
        from music_teacher_ai.database.sqlite import get_session

        with get_session() as session:
            count = len(session.exec(select(Song)).all())
        assert count == 10


# ---------------------------------------------------------------------------
# print_minimal_banner() — just verify it doesn't raise
# ---------------------------------------------------------------------------

class TestBanner:
    def test_banner_runs_without_error(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.print_minimal_banner()   # must not raise

    def test_credential_warning_with_no_keys(self, fresh_db, monkeypatch):
        for key, _ in [("GENIUS_ACCESS_TOKEN", ""), ("SPOTIFY_CLIENT_ID", ""),
                       ("LASTFM_API_KEY", "")]:
            monkeypatch.delenv(key, raising=False)

        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr._print_credential_warning()   # must not raise

    def test_no_credential_warning_when_all_set(self, fresh_db, monkeypatch):
        monkeypatch.setenv("GENIUS_ACCESS_TOKEN", "tok")
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "cid")
        monkeypatch.setenv("LASTFM_API_KEY", "key")

        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr._print_credential_warning()   # must not raise and prints nothing


# ---------------------------------------------------------------------------
# Integration: demo data is searchable
# ---------------------------------------------------------------------------

class TestDemoSearchable:
    def test_song_title_searchable(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()

        from music_teacher_ai.playlists.manager import _search_by_title
        importlib.reload(__import__("music_teacher_ai.playlists.manager",
                                    fromlist=["_search_by_title"]))

        results = _search_by_title("Imagine", limit=10)
        assert any(r["title"] == "Imagine" for r in results)

    def test_lyrics_accessible_for_exercise(self, fresh_db):
        import importlib

        import music_teacher_ai.demo.loader as ldr
        importlib.reload(ldr)
        ldr.load_demo_songs()

        from sqlmodel import select

        from music_teacher_ai.database.models import Lyrics, Song
        from music_teacher_ai.database.sqlite import get_session
        from music_teacher_ai.education_services.exercises.gap_fill import generate_random

        with get_session() as session:
            songs = session.exec(select(Song)).all()
            song = songs[0]
            lyr = session.exec(select(Lyrics).where(Lyrics.song_id == song.id)).first()

        assert lyr is not None
        ex = generate_random(lyr.lyrics_text, level=20)
        assert ex.blanked_count > 0
