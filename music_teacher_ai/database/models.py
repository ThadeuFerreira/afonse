from typing import Optional
from sqlmodel import Field, SQLModel


class Artist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    spotify_id: Optional[str] = Field(default=None, index=True)
    genres: Optional[str] = None  # JSON-encoded list


class Album(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    artist_id: int = Field(foreign_key="artist.id")
    release_year: Optional[int] = None


class Song(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    spotify_id: Optional[str] = Field(default=None, index=True, unique=True)
    title: str
    artist_id: int = Field(foreign_key="artist.id")
    album_id: Optional[int] = Field(default=None, foreign_key="album.id")
    release_year: Optional[int] = Field(default=None, index=True)
    genre: Optional[str] = None
    popularity: Optional[int] = None
    duration_ms: Optional[int] = None
    tempo: Optional[float] = None
    valence: Optional[float] = None
    energy: Optional[float] = None
    danceability: Optional[float] = None
    metadata_source: Optional[str] = None  # "spotify" | "musicbrainz" | "lastfm" | None=not enriched


class Lyrics(SQLModel, table=True):
    song_id: int = Field(foreign_key="song.id", primary_key=True)
    lyrics_text: str
    language: Optional[str] = Field(default="en")
    word_count: Optional[int] = None
    unique_words: Optional[int] = None


class Chart(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    song_id: int = Field(foreign_key="song.id", index=True)
    chart_name: str
    rank: int
    date: str  # ISO date string


class VocabularyIndex(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    word: str = Field(index=True)
    song_id: int = Field(foreign_key="song.id")


class Embedding(SQLModel, table=True):
    song_id: int = Field(foreign_key="song.id", primary_key=True)
    embedding_vector: bytes  # numpy array serialized with numpy.tobytes()
    faiss_id: Optional[int] = Field(default=None, index=True)  # position in FAISS index


class IngestionFailure(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    song_id: Optional[int] = Field(default=None, foreign_key="song.id")
    stage: str  # e.g. "lyrics", "metadata", "embedding"
    error_message: str
    retry_count: int = Field(default=0)
    raw_title: Optional[str] = None
    raw_artist: Optional[str] = None
