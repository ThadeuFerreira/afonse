from typing import Optional

from sqlmodel import select

from music_teacher_ai.database.models import Artist, Song, VocabularyIndex
from music_teacher_ai.database.sqlite import get_session


def search_songs(
    word: Optional[str] = None,
    year: Optional[int] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    artist: Optional[str] = None,
    genre: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    with get_session() as session:
        if word:
            # exec(select(Column)) returns scalars directly, not row tuples
            song_ids = set(
                session.exec(
                    select(VocabularyIndex.song_id).where(VocabularyIndex.word == word.lower())
                ).all()
            )
            if not song_ids:
                return []
            query = select(Song).where(Song.id.in_(song_ids))
        else:
            query = select(Song)

        if year:
            query = query.where(Song.release_year == year)
        if year_min:
            query = query.where(Song.release_year >= year_min)
        if year_max:
            query = query.where(Song.release_year <= year_max)
        if genre:
            query = query.where(Song.genre.contains(genre))

        # Apply the artist join-filter inside the query so that `limit`
        # applies to the already-filtered set, not the unfiltered table.
        if artist:
            query = query.join(Artist, Song.artist_id == Artist.id).where(
                Artist.name.ilike(f"%{artist}%")
            )

        songs = session.exec(query.limit(limit)).all()

        results = []
        for song in songs:
            artist_obj = session.get(Artist, song.artist_id)
            results.append(
                {
                    "id": song.id,
                    "title": song.title,
                    "artist": artist_obj.name if artist_obj else "",
                    "year": song.release_year,
                    "genre": song.genre,
                    "popularity": song.popularity,
                }
            )

        return results
