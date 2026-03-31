"""
Smoke tests for the SQLite database layer.

No external API required.

Verifies:
- Schema creation succeeds
- Basic insert/query/update operations work for all core models
- Foreign key relationships are consistent
- Duplicate detection by spotify_id works
"""

import pytest
from sqlmodel import select


@pytest.fixture()
def session(tmp_db):
    """Return a live session against the temp database."""
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as s:
        yield s


def test_schema_creation(tmp_db):
    """create_db() creates all expected tables."""
    import sqlite3

    conn = sqlite3.connect(str(tmp_db))
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    conn.close()

    expected = {
        "song",
        "artist",
        "album",
        "lyrics",
        "chart",
        "vocabularyindex",
        "embedding",
        "ingestionfailure",
    }
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


def test_insert_and_query_artist(session):
    from music_teacher_ai.database.models import Artist

    artist = Artist(name="John Lennon", spotify_id="spotify_jl_001")
    session.add(artist)
    session.commit()
    session.refresh(artist)

    fetched = session.get(Artist, artist.id)
    assert fetched is not None
    assert fetched.name == "John Lennon"
    assert fetched.spotify_id == "spotify_jl_001"


def test_insert_song_with_artist(session):
    from music_teacher_ai.database.models import Artist, Song

    artist = Artist(name="Bob Dylan")
    session.add(artist)
    session.flush()

    song = Song(
        title="Blowin' in the Wind",
        artist_id=artist.id,
        release_year=1963,
        spotify_id="spotify_bitw_001",
    )
    session.add(song)
    session.commit()
    session.refresh(song)

    fetched = session.get(Song, song.id)
    assert fetched.title == "Blowin' in the Wind"
    assert fetched.artist_id == artist.id
    assert fetched.release_year == 1963


def test_insert_lyrics(session):
    from music_teacher_ai.database.models import Artist, Lyrics, Song

    artist = Artist(name="Marvin Gaye")
    session.add(artist)
    session.flush()
    song = Song(title="What's Going On", artist_id=artist.id, release_year=1971)
    session.add(song)
    session.flush()

    lyrics = Lyrics(
        song_id=song.id,
        lyrics_text="Mother mother there's too many of you crying",
        word_count=9,
        unique_words=9,
    )
    session.add(lyrics)
    session.commit()

    fetched = session.exec(select(Lyrics).where(Lyrics.song_id == song.id)).first()
    assert fetched is not None
    assert "mother" in fetched.lyrics_text.lower()
    assert fetched.word_count == 9


def test_vocabulary_index(session):
    from music_teacher_ai.database.models import Artist, Song, VocabularyIndex

    artist = Artist(name="Test Artist")
    session.add(artist)
    session.flush()
    song = Song(title="Test Song", artist_id=artist.id)
    session.add(song)
    session.flush()

    for word in ["dream", "hope", "free"]:
        session.add(VocabularyIndex(word=word, song_id=song.id))
    session.commit()

    hits = session.exec(select(VocabularyIndex).where(VocabularyIndex.word == "dream")).all()
    assert len(hits) == 1
    assert hits[0].song_id == song.id


def test_ingestion_failure_tracking(session):
    from music_teacher_ai.database.models import IngestionFailure

    failure = IngestionFailure(
        stage="lyrics",
        error_message="HTTP 429 rate limited",
        raw_title="Some Song",
        raw_artist="Some Artist",
        retry_count=0,
    )
    session.add(failure)
    session.commit()
    session.refresh(failure)

    fetched = session.get(IngestionFailure, failure.id)
    assert fetched.stage == "lyrics"
    assert fetched.retry_count == 0


def test_spotify_id_unique_constraint(session):
    """Two songs with the same spotify_id should raise an integrity error."""
    import pytest
    from sqlalchemy.exc import IntegrityError

    from music_teacher_ai.database.models import Artist, Song

    artist = Artist(name="Artist X")
    session.add(artist)
    session.flush()

    session.add(Song(title="Song A", artist_id=artist.id, spotify_id="dup_id_001"))
    session.commit()

    session.add(Song(title="Song B", artist_id=artist.id, spotify_id="dup_id_001"))
    with pytest.raises(IntegrityError):
        session.commit()
