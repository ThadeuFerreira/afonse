"""
PlaylistManager – create, load, list, delete, and refresh playlists.

Playlists are stored as JSON files under PLAYLISTS_DIR/{slug}/playlist.json.
M3U and M3U8 exports are generated alongside the JSON on creation.
"""
import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from music_teacher_ai.config.settings import PLAYLISTS_DIR
from music_teacher_ai.playlists.models import Playlist, PlaylistQuery, PlaylistSong
from music_teacher_ai.playlists.exporters import export_all


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Convert a playlist name to a filesystem-safe slug."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]", "-", s)
    return s.strip("-")


def _playlist_dir(slug: str) -> Path:
    return PLAYLISTS_DIR / slug


def _load_json(path: Path) -> Playlist:
    return Playlist.model_validate_json(path.read_text(encoding="utf-8"))


def _enrich_with_spotify_id(song_dicts: list[dict]) -> list[PlaylistSong]:
    """Look up spotify_id for each song and return PlaylistSong objects."""
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.database.models import Song

    result = []
    with get_session() as session:
        for s in song_dicts:
            db_song = session.get(Song, s["id"])
            result.append(
                PlaylistSong(
                    song_id=s["id"],
                    title=s["title"],
                    artist=s["artist"],
                    year=s.get("year"),
                    spotify_id=db_song.spotify_id if db_song else None,
                )
            )
    return result


def _run_query(query: PlaylistQuery) -> list[PlaylistSong]:
    """Execute the stored query and return enriched PlaylistSong list."""
    raw: list[dict] = []

    if query.similar_text:
        from music_teacher_ai.search.similar_search import find_similar_by_text
        raw = find_similar_by_text(query.similar_text, top_k=query.limit)

    elif query.similar_song_id is not None:
        from music_teacher_ai.search.similar_search import find_similar_by_song
        raw = find_similar_by_song(query.similar_song_id, top_k=query.limit)

    elif query.semantic_query:
        from music_teacher_ai.search.semantic_search import semantic_search
        raw = semantic_search(query.semantic_query, top_k=query.limit)

    else:
        from music_teacher_ai.search.keyword_search import search_songs
        raw = search_songs(
            word=query.word,
            year=query.year,
            year_min=query.year_min,
            year_max=query.year_max,
            artist=query.artist,
            genre=query.genre,
            limit=query.limit,
        )

    return _enrich_with_spotify_id(raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create(
    name: str,
    description: Optional[str] = None,
    query: Optional[PlaylistQuery] = None,
    songs: Optional[list[PlaylistSong]] = None,
) -> Playlist:
    """
    Create a playlist.

    Either pass a `query` (auto-populated from search) or a manual `songs` list.
    Raises FileExistsError if a playlist with the same slug already exists.
    """
    slug = _slug(name)
    dest = _playlist_dir(slug)
    if dest.exists():
        raise FileExistsError(
            f"Playlist '{slug}' already exists. Delete it first or choose a different name."
        )

    resolved_songs: list[PlaylistSong] = []
    if query is not None:
        resolved_songs = _run_query(query)
    elif songs is not None:
        resolved_songs = songs

    playlist = Playlist(
        id=slug,
        name=name,
        description=description,
        created_at=date.today().isoformat(),
        query=query,
        songs=resolved_songs,
    )

    export_all(playlist, dest)
    return playlist


def get(playlist_id: str) -> Playlist:
    """Load a playlist by its slug. Raises FileNotFoundError if missing."""
    path = _playlist_dir(playlist_id) / "playlist.json"
    if not path.exists():
        raise FileNotFoundError(f"Playlist not found: '{playlist_id}'")
    return _load_json(path)


def list_all() -> list[Playlist]:
    """Return all playlists, sorted by creation date (newest first)."""
    PLAYLISTS_DIR.mkdir(parents=True, exist_ok=True)
    playlists = []
    for entry in sorted(PLAYLISTS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        json_file = entry / "playlist.json"
        if entry.is_dir() and json_file.exists():
            try:
                playlists.append(_load_json(json_file))
            except Exception:
                pass  # skip corrupt files
    return playlists


def delete(playlist_id: str) -> None:
    """Delete a playlist directory. Raises FileNotFoundError if missing."""
    dest = _playlist_dir(playlist_id)
    if not dest.exists():
        raise FileNotFoundError(f"Playlist not found: '{playlist_id}'")
    import shutil
    shutil.rmtree(dest)


def refresh(playlist_id: str) -> Playlist:
    """Re-run the stored query and overwrite the playlist with fresh results."""
    existing = get(playlist_id)
    if not existing.query:
        raise ValueError(f"Playlist '{playlist_id}' has no stored query — cannot refresh.")
    delete(playlist_id)
    return create(
        name=existing.name,
        description=existing.description,
        query=existing.query,
    )


def export_format(playlist_id: str, fmt: str) -> str:
    """Return the playlist content as a string in the requested format."""
    from music_teacher_ai.playlists.exporters import render
    playlist = get(playlist_id)
    return render(playlist, fmt)
