"""
Unit tests for playlist creation, export, and management.
No database or external API required.
"""
import json

import pytest

from music_teacher_ai.playlists.exporters import render, to_json, to_m3u
from music_teacher_ai.playlists.models import Playlist, PlaylistQuery, PlaylistSong

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_playlist():
    return Playlist(
        id="dream-vocabulary",
        name="Dream Vocabulary",
        description="Songs containing the word dream",
        created_at="2026-03-18",
        query=PlaylistQuery(word="dream", year_min=1980, year_max=2000),
        songs=[
            PlaylistSong(song_id=1, title="Dream On", artist="Aerosmith", year=1973, spotify_id="spotify1"),
            PlaylistSong(song_id=2, title="Dreams", artist="Fleetwood Mac", year=1977, spotify_id="spotify2"),
            PlaylistSong(song_id=3, title="Sweet Dreams", artist="Eurythmics", year=1983, spotify_id=None),
        ],
    )


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def test_slug_basic():
    from music_teacher_ai.playlists.manager import _slug
    assert _slug("Dream Vocabulary") == "dream-vocabulary"


def test_slug_special_chars():
    from music_teacher_ai.playlists.manager import _slug
    assert _slug("90's Rock & Roll!") == "90s-rock--roll"


def test_slug_extra_spaces():
    from music_teacher_ai.playlists.manager import _slug
    result = _slug("  Love  Songs  ")
    assert result == "love--songs"


# ---------------------------------------------------------------------------
# M3U export
# ---------------------------------------------------------------------------

def test_m3u_header(sample_playlist):
    content = to_m3u(sample_playlist)
    assert content.startswith("#EXTM3U")


def test_m3u_contains_extinf(sample_playlist):
    content = to_m3u(sample_playlist)
    assert "#EXTINF:-1,Aerosmith - Dream On" in content
    assert "#EXTINF:-1,Fleetwood Mac - Dreams" in content


def test_m3u_spotify_uri_when_available(sample_playlist):
    content = to_m3u(sample_playlist)
    assert "spotify:track:spotify1" in content
    assert "spotify:track:spotify2" in content


def test_m3u_fallback_when_no_spotify_id(sample_playlist):
    content = to_m3u(sample_playlist)
    # Song 3 has no spotify_id — should fall back to "artist - title"
    assert "Eurythmics - Sweet Dreams" in content
    assert "spotify:track:None" not in content


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def test_json_export_valid(sample_playlist):
    content = to_json(sample_playlist)
    data = json.loads(content)
    assert data["name"] == "Dream Vocabulary"
    assert len(data["songs"]) == 3
    assert data["songs"][0]["title"] == "Dream On"


def test_json_export_includes_query(sample_playlist):
    content = to_json(sample_playlist)
    data = json.loads(content)
    assert data["query"]["word"] == "dream"
    assert data["query"]["year_min"] == 1980


# ---------------------------------------------------------------------------
# render() dispatcher
# ---------------------------------------------------------------------------

def test_render_m3u(sample_playlist):
    content = render(sample_playlist, "m3u")
    assert "#EXTM3U" in content


def test_render_m3u8(sample_playlist):
    content = render(sample_playlist, "m3u8")
    assert "#EXTM3U" in content


def test_render_json(sample_playlist):
    content = render(sample_playlist, "json")
    data = json.loads(content)
    assert data["id"] == "dream-vocabulary"


def test_render_invalid_format(sample_playlist):
    with pytest.raises(ValueError, match="Unsupported format"):
        render(sample_playlist, "xml")


# ---------------------------------------------------------------------------
# File-system operations (using tmp_path)
# ---------------------------------------------------------------------------

def test_create_and_get_playlist(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    importlib.reload(s)
    importlib.reload(pm)

    songs = [
        PlaylistSong(song_id=1, title="Dream On", artist="Aerosmith", year=1973),
    ]
    created = pm.create(name="Test Playlist", songs=songs)

    assert created.id == "test-playlist"
    assert len(created.songs) == 1

    loaded = pm.get("test-playlist")
    assert loaded.name == "Test Playlist"
    assert loaded.songs[0].title == "Dream On"


def test_export_files_written(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    importlib.reload(s)
    importlib.reload(pm)

    songs = [PlaylistSong(song_id=1, title="Song A", artist="Artist X", year=2000)]
    pm.create(name="Export Test", songs=songs)

    playlist_dir = tmp_path / "playlists" / "export-test"
    assert (playlist_dir / "playlist.json").exists()
    assert (playlist_dir / "playlist.m3u").exists()
    assert (playlist_dir / "playlist.m3u8").exists()


def test_create_duplicate_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    importlib.reload(s)
    importlib.reload(pm)

    songs = [PlaylistSong(song_id=1, title="Song A", artist="X", year=2000)]
    pm.create(name="My Playlist", songs=songs)

    with pytest.raises(FileExistsError):
        pm.create(name="My Playlist", songs=songs)


def test_delete_playlist(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    importlib.reload(s)
    importlib.reload(pm)

    songs = [PlaylistSong(song_id=1, title="Song A", artist="X", year=2000)]
    pm.create(name="To Delete", songs=songs)
    pm.delete("to-delete")

    with pytest.raises(FileNotFoundError):
        pm.get("to-delete")


def test_list_playlists(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    importlib.reload(s)
    importlib.reload(pm)

    songs = [PlaylistSong(song_id=1, title="Song", artist="X", year=2000)]
    pm.create(name="Alpha", songs=songs)
    pm.create(name="Beta", songs=songs)

    all_playlists = pm.list_all()
    names = {p.name for p in all_playlists}
    assert {"Alpha", "Beta"}.issubset(names)


# ---------------------------------------------------------------------------
# New fields: isrc_code, query_origin, song_count
# ---------------------------------------------------------------------------

def test_playlist_song_has_isrc_field():
    s = PlaylistSong(song_id=1, title="T", artist="A", isrc_code="USRC17607839")
    assert s.isrc_code == "USRC17607839"


def test_playlist_song_isrc_defaults_none():
    s = PlaylistSong(song_id=1, title="T", artist="A")
    assert s.isrc_code is None


def test_isrc_serialised_in_json(sample_playlist):
    # Add ISRC to one song and verify it appears in JSON export
    sample_playlist.songs[0].isrc_code = "USABC1234567"
    data = json.loads(to_json(sample_playlist))
    assert data["songs"][0]["isrc_code"] == "USABC1234567"


def test_playlist_has_query_origin_field():
    p = Playlist(id="x", name="X", created_at="2026-01-01", query_origin="genre:rock")
    assert p.query_origin == "genre:rock"


def test_playlist_query_origin_defaults_none():
    p = Playlist(id="x", name="X", created_at="2026-01-01")
    assert p.query_origin is None


def test_song_count_property(sample_playlist):
    assert sample_playlist.song_count == 3


def test_song_count_empty():
    p = Playlist(id="x", name="X", created_at="2026-01-01")
    assert p.song_count == 0


def test_query_origin_stored_on_create(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    importlib.reload(s)
    importlib.reload(pm)

    songs = [PlaylistSong(song_id=1, title="Song", artist="X", year=2000)]
    pl = pm.create(name="Origin Test", songs=songs)
    assert pl.query_origin == "manual"


def test_query_origin_from_query_object():
    q = PlaylistQuery(word="dream", genre="rock")
    origin = q.to_origin()
    assert "word:dream" in origin
    assert "genre:rock" in origin


def test_query_origin_semantic():
    q = PlaylistQuery(semantic_query="songs about freedom")
    assert "semantic:songs about freedom" in q.to_origin()


def test_query_origin_empty_is_manual():
    q = PlaylistQuery()
    assert q.to_origin() == "manual"


# ---------------------------------------------------------------------------
# Max playlist size (100-song cap)
# ---------------------------------------------------------------------------

def test_playlist_size_cap(tmp_path, monkeypatch):
    """Creating a playlist with 150 songs must silently cap at 100."""
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.playlists.manager as pm
    from music_teacher_ai.playlists.models import _MAX_PLAYLIST_SIZE
    importlib.reload(s)
    importlib.reload(pm)

    songs = [PlaylistSong(song_id=i, title=f"Song {i}", artist="X") for i in range(150)]
    pl = pm.create(name="Huge Playlist", songs=songs)
    assert len(pl.songs) == _MAX_PLAYLIST_SIZE
    assert pl.song_count == _MAX_PLAYLIST_SIZE


def test_max_playlist_size_constant():
    from music_teacher_ai.playlists.models import _MAX_PLAYLIST_SIZE
    assert _MAX_PLAYLIST_SIZE == 100


# ---------------------------------------------------------------------------
# PlaylistQuery.song field
# ---------------------------------------------------------------------------

def test_playlist_query_has_song_field():
    q = PlaylistQuery(song="Dream On")
    assert q.song == "Dream On"


def test_song_field_in_origin():
    q = PlaylistQuery(song="Dream On")
    assert "song:Dream On" in q.to_origin()


# ---------------------------------------------------------------------------
# _search_by_title — Song.title ilike, not VocabularyIndex
# ---------------------------------------------------------------------------

def test_search_by_title_matches_title(tmp_path, monkeypatch):
    """_search_by_title must match Song.title, not lyrics vocabulary."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import importlib

    import music_teacher_ai.config.settings as _s
    import music_teacher_ai.database.sqlite as _db
    importlib.reload(_s)
    importlib.reload(_db)
    _db.create_db()

    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        artist = Artist(name="Aerosmith")
        session.add(artist)
        session.flush()
        session.add(Song(title="Dream On", artist_id=artist.id, release_year=1973))
        session.add(Song(title="Sweet Emotion", artist_id=artist.id, release_year=1975))
        session.commit()

    from music_teacher_ai.playlists.manager import _search_by_title
    importlib.reload(__import__("music_teacher_ai.playlists.manager", fromlist=["_search_by_title"]))

    results = _search_by_title("Dream On", limit=10)
    assert len(results) == 1
    assert results[0]["title"] == "Dream On"


def test_search_by_title_case_insensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import importlib

    import music_teacher_ai.config.settings as _s
    import music_teacher_ai.database.sqlite as _db
    importlib.reload(_s)
    importlib.reload(_db)
    _db.create_db()

    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        artist = Artist(name="Aerosmith")
        session.add(artist)
        session.flush()
        session.add(Song(title="Dream On", artist_id=artist.id, release_year=1973))
        session.commit()

    from music_teacher_ai.playlists.manager import _search_by_title
    assert len(_search_by_title("dream on", limit=10)) == 1
    assert len(_search_by_title("DREAM", limit=10)) == 1


def test_search_by_title_partial_match(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import importlib

    import music_teacher_ai.config.settings as _s
    import music_teacher_ai.database.sqlite as _db
    importlib.reload(_s)
    importlib.reload(_db)
    _db.create_db()

    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        artist = Artist(name="Various")
        session.add(artist)
        session.flush()
        session.add(Song(title="Dream On", artist_id=artist.id))
        session.add(Song(title="Sweet Dreams", artist_id=artist.id))
        session.add(Song(title="Daydream", artist_id=artist.id))
        session.add(Song(title="Yesterday", artist_id=artist.id))
        session.commit()

    from music_teacher_ai.playlists.manager import _search_by_title
    results = _search_by_title("dream", limit=10)
    titles = {r["title"] for r in results}
    assert titles == {"Dream On", "Sweet Dreams", "Daydream"}
    assert "Yesterday" not in titles


def test_run_query_song_uses_title_not_vocabulary(tmp_path, monkeypatch):
    """When PlaylistQuery.song is set, _run_query must NOT touch VocabularyIndex."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("PLAYLISTS_DIR", str(tmp_path / "playlists"))
    import importlib

    import music_teacher_ai.config.settings as _s
    import music_teacher_ai.database.sqlite as _db
    importlib.reload(_s)
    importlib.reload(_db)
    _db.create_db()

    from music_teacher_ai.database.models import Artist, Song
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        artist = Artist(name="Aerosmith")
        session.add(artist)
        session.flush()
        # Title contains multi-word phrase that would never be in VocabularyIndex
        session.add(Song(title="Dream On", artist_id=artist.id, release_year=1973))
        session.commit()

    import music_teacher_ai.playlists.manager as pm
    importlib.reload(pm)

    results = pm._run_query(PlaylistQuery(song="Dream On", limit=10))
    assert len(results) == 1
    assert results[0].title == "Dream On"
