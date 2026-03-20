"""
Smoke tests for the ingestion pipeline components.

Exercises the pipeline stages using a minimal in-memory dataset
(no external API calls) to verify the plumbing works end-to-end.

Verifies:
- vocabulary_indexer extracts and stores words correctly
- embedding_pipeline generates embeddings and stores faiss_id
- similar_search finds results after the mini-pipeline runs
- keyword_search finds songs by indexed word
"""
import numpy as np
from sqlmodel import select

# ---------------------------------------------------------------------------
# Helpers to seed a minimal in-memory dataset
# ---------------------------------------------------------------------------

def _seed_song(session, title: str, artist_name: str, lyrics_text: str, year: int = 1990):
    from music_teacher_ai.database.models import Artist, Lyrics, Song

    artist = session.exec(select(Artist).where(Artist.name == artist_name)).first()
    if not artist:
        artist = Artist(name=artist_name)
        session.add(artist)
        session.flush()

    song = Song(title=title, artist_id=artist.id, release_year=year)
    session.add(song)
    session.flush()

    lyr = Lyrics(song_id=song.id, lyrics_text=lyrics_text, word_count=len(lyrics_text.split()))
    session.add(lyr)
    session.commit()
    return song


# ---------------------------------------------------------------------------
# Vocabulary indexer
# ---------------------------------------------------------------------------

def test_vocabulary_indexer_extracts_words(tmp_db):
    from music_teacher_ai.database.models import VocabularyIndex
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index

    with get_session() as session:
        _seed_song(session, "Dream Song", "Artist A", "dreaming of freedom and hope tonight")

    build_vocabulary_index()

    with get_session() as session:
        hits = session.exec(
            select(VocabularyIndex).where(VocabularyIndex.word == "freedom")
        ).all()
        assert hits, "Expected 'freedom' to be indexed"


def test_vocabulary_indexer_skips_stopwords(tmp_db):
    from music_teacher_ai.database.models import VocabularyIndex
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index

    with get_session() as session:
        _seed_song(session, "Stopword Song", "Artist B", "i am the one who knocks")

    build_vocabulary_index()

    with get_session() as session:
        # "i", "am", "the", "who" are stopwords and should not be indexed
        for stopword in ("i", "am", "the", "who"):
            hits = session.exec(
                select(VocabularyIndex).where(VocabularyIndex.word == stopword)
            ).all()
            assert not hits, f"Stopword '{stopword}' should not be indexed"


def test_vocabulary_indexer_no_duplicates(tmp_db):
    """Running the indexer twice must not create duplicate entries."""
    from music_teacher_ai.database.models import VocabularyIndex
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index

    with get_session() as session:
        _seed_song(session, "Double Song", "Artist C", "love and peace forever")

    build_vocabulary_index()
    build_vocabulary_index()  # second run

    with get_session() as session:
        hits = session.exec(
            select(VocabularyIndex).where(VocabularyIndex.word == "love")
        ).all()
        assert len(hits) == 1, f"Expected 1 entry for 'love', got {len(hits)}"


# ---------------------------------------------------------------------------
# Embedding pipeline
# ---------------------------------------------------------------------------

def test_embedding_pipeline_stores_faiss_id(tmp_db, tmp_faiss):
    from music_teacher_ai.database.models import Embedding
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

    with get_session() as session:
        _seed_song(session, "Embed Song", "Artist D", "the night is young and full of stars")

    generate_embeddings()

    with get_session() as session:
        embeddings = session.exec(select(Embedding)).all()
        assert embeddings, "No embeddings were stored"
        assert embeddings[0].faiss_id is not None, "faiss_id was not set"
        assert embeddings[0].faiss_id == 0, "First embedding should have faiss_id=0"


def test_embedding_pipeline_vector_shape(tmp_db, tmp_faiss):
    from music_teacher_ai.config.settings import EMBEDDING_DIM
    from music_teacher_ai.database.models import Embedding
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

    with get_session() as session:
        _seed_song(session, "Shape Song", "Artist E", "walking down the road to find my way")

    generate_embeddings()

    with get_session() as session:
        emb = session.exec(select(Embedding)).first()
        vec = np.frombuffer(emb.embedding_vector, dtype=np.float32)

    assert vec.shape == (EMBEDDING_DIM,), f"Unexpected shape: {vec.shape}"


def test_embedding_pipeline_faiss_ids_sequential(tmp_db, tmp_faiss):
    """faiss_id values are sequential (0, 1, 2, ...) across batches."""
    from music_teacher_ai.database.models import Embedding
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

    with get_session() as session:
        for i in range(3):
            _seed_song(
                session,
                f"Song {i}",
                f"Artist {i}",
                f"unique lyrics for song number {i} about {'love' if i == 0 else 'hope' if i == 1 else 'dreams'}",
            )

    generate_embeddings(batch_size=2)  # force two batches for 3 songs

    with get_session() as session:
        embeddings = session.exec(select(Embedding).order_by(Embedding.faiss_id)).all()
        faiss_ids = [e.faiss_id for e in embeddings]

    assert faiss_ids == list(range(len(faiss_ids))), f"faiss_ids not sequential: {faiss_ids}"


# ---------------------------------------------------------------------------
# End-to-end mini pipeline: seed → embed → similar search
# ---------------------------------------------------------------------------

def test_similar_search_after_pipeline(tmp_db, tmp_faiss):
    """After running the embedding pipeline, similar_search returns results."""
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings
    from music_teacher_ai.search.similar_search import find_similar_by_text

    with get_session() as session:
        _seed_song(session, "Freedom Song", "Artist F",
                   "freedom rings across the land dreaming of a better world")
        _seed_song(session, "Sad Song", "Artist G",
                   "walking alone in the dark missing you every night crying tears")
        _seed_song(session, "Happy Song", "Artist H",
                   "sunshine and rainbows dancing in the street laughing all day")

    generate_embeddings()

    results = find_similar_by_text("dreams of liberty and freedom", top_k=3)

    assert results, "find_similar_by_text returned no results"
    assert all("score" in r for r in results), "Results missing 'score' field"
    # Freedom Song should rank highest among the three
    assert results[0]["title"] == "Freedom Song", (
        f"Expected 'Freedom Song' as top result, got '{results[0]['title']}'"
    )


def test_keyword_search_after_indexing(tmp_db):
    """After vocabulary indexing, keyword_search finds songs by word."""
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index
    from music_teacher_ai.search.keyword_search import search_songs

    with get_session() as session:
        _seed_song(session, "River Song", "Artist I",
                   "the river flows through the valley carrying dreams downstream")

    build_vocabulary_index()

    results = search_songs(word="river")
    assert results, "keyword_search returned no results for 'river'"
    assert any(r["title"] == "River Song" for r in results)
