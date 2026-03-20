from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

_MAX_PLAYLIST_SIZE = 100
_DEFAULT_PLAYLIST_SIZE = 20


class PlaylistSong(BaseModel):
    song_id: int
    title: str
    artist: str
    year: Optional[int] = None
    spotify_id: Optional[str] = None
    isrc_code: Optional[str] = None


class PlaylistQuery(BaseModel):
    """Stored query that was used to build the playlist — enables future refresh."""
    word: Optional[str] = None
    year: Optional[int] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    song: Optional[str] = None              # song title search
    semantic_query: Optional[str] = None
    similar_text: Optional[str] = None
    similar_song_id: Optional[int] = None
    limit: int = _DEFAULT_PLAYLIST_SIZE

    def to_origin(self) -> str:
        """Human-readable summary of the query, e.g. 'genre:rock | year:1990'."""
        parts = []
        if self.word:
            parts.append(f"word:{self.word}")
        if self.song:
            parts.append(f"song:{self.song}")
        if self.artist:
            parts.append(f"artist:{self.artist}")
        if self.genre:
            parts.append(f"genre:{self.genre}")
        if self.year:
            parts.append(f"year:{self.year}")
        if self.year_min or self.year_max:
            parts.append(f"year:{self.year_min or ''}-{self.year_max or ''}")
        if self.semantic_query:
            parts.append(f"semantic:{self.semantic_query}")
        if self.similar_text:
            parts.append(f"similar_text:{self.similar_text}")
        if self.similar_song_id is not None:
            parts.append(f"similar_song:{self.similar_song_id}")
        return " | ".join(parts) if parts else "manual"


class Playlist(BaseModel):
    id: str                          # filesystem slug, e.g. "dream-vocabulary"
    name: str
    description: Optional[str] = None
    created_at: str                  # ISO date string
    query_origin: Optional[str] = None   # human-readable query summary
    query: Optional[PlaylistQuery] = None
    songs: list[PlaylistSong] = []

    @property
    def song_count(self) -> int:
        return len(self.songs)
