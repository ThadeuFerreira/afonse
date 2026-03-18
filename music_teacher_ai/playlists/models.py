from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class PlaylistSong(BaseModel):
    song_id: int
    title: str
    artist: str
    year: Optional[int] = None
    spotify_id: Optional[str] = None


class PlaylistQuery(BaseModel):
    """Stored query that was used to build the playlist — enables future refresh."""
    word: Optional[str] = None
    year: Optional[int] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    semantic_query: Optional[str] = None
    similar_text: Optional[str] = None
    similar_song_id: Optional[int] = None
    limit: int = 20


class Playlist(BaseModel):
    id: str                          # filesystem slug, e.g. "dream-vocabulary"
    name: str
    description: Optional[str] = None
    created_at: str                  # ISO date string
    query: Optional[PlaylistQuery] = None
    songs: list[PlaylistSong] = []
