"""
Unit tests for playlist creation, export, and management.
No database or external API required.
"""
import json
import pytest
from pathlib import Path

from music_teacher_ai.playlists.models import Playlist, PlaylistSong, PlaylistQuery
from music_teacher_ai.playlists.exporters import to_m3u, to_json, render, SUPPORTED_FORMATS


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
