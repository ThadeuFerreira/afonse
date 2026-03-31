import re
from typing import Optional

from sqlmodel import Session, select

from music_teacher_ai.database.models import Artist, Song, SongCandidate


def normalize_text(value: str) -> str:
    normalized = value.lower()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def song_key(title: str, artist: str) -> str:
    return f"{normalize_text(artist)}||{normalize_text(title)}"


class SongRepository:
    def get_or_create_artist(self, session: Session, artist_name: str) -> Artist:
        row = session.exec(select(Artist).where(Artist.name == artist_name)).first()
        if row:
            return row
        row = Artist(name=artist_name)
        session.add(row)
        session.flush()
        return row

    def song_exists(self, session: Session, *, title: str, artist_id: int) -> bool:
        return (
            session.exec(
                select(Song).where(Song.title == title).where(Song.artist_id == artist_id)
            ).first()
            is not None
        )

    def add_song(
        self,
        session: Session,
        *,
        title: str,
        artist_id: int,
        release_year: Optional[int] = None,
        genre: Optional[str] = None,
    ) -> Song:
        song = Song(title=title, artist_id=artist_id, release_year=release_year, genre=genre)
        session.add(song)
        return song

    def load_existing_keys(self, session: Session) -> set[str]:
        rows = session.exec(
            select(Song.title, Artist.name).join(Artist, Song.artist_id == Artist.id)
        ).all()
        return {song_key(title, artist) for title, artist in rows}


class SongCandidateRepository:
    def pending(self, session: Session, query_origin: Optional[str] = None) -> list[SongCandidate]:
        query = select(SongCandidate).where(SongCandidate.status == "pending")
        if query_origin:
            query = query.where(SongCandidate.query_origin == query_origin)
        return session.exec(query).all()
