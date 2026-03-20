"""
Unit tests for similar_search helpers.
These tests mock the FAISS index and database so no real data is needed.
"""
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


def _make_embedding(song_id: int, faiss_id: int) -> MagicMock:
    emb = MagicMock()
    emb.song_id = song_id
    emb.faiss_id = faiss_id
    emb.embedding_vector = np.ones(384, dtype=np.float32).tobytes()
    return emb


def _make_song(song_id: int, title: str, artist_id: int = 1) -> MagicMock:
    song = MagicMock()
    song.id = song_id
    song.title = title
    song.artist_id = artist_id
    song.release_year = 1990
    return song


def _make_artist(name: str = "Test Artist") -> MagicMock:
    artist = MagicMock()
    artist.name = name
    return artist


@patch("music_teacher_ai.search.similar_search._load_index")
@patch("music_teacher_ai.search.similar_search._faiss_ids_to_songs")
def test_find_similar_by_song_excludes_self(mock_faiss_resolve, mock_load_index):
    from music_teacher_ai.search.similar_search import find_similar_by_song

    mock_index = MagicMock()
    mock_index.search.return_value = (
        np.array([[0.99, 0.88, 0.75]]),
        np.array([[0, 1, 2]]),
    )
    mock_load_index.return_value = mock_index

    # FAISS returns songs [1, 2, 3]; song 1 is the query — should be excluded
    mock_faiss_resolve.return_value = [
        {"id": 1, "title": "Imagine", "artist": "John Lennon", "year": 1971, "score": 0.99},
        {"id": 2, "title": "Blowin in the Wind", "artist": "Bob Dylan", "year": 1963, "score": 0.88},
        {"id": 3, "title": "What's Going On", "artist": "Marvin Gaye", "year": 1971, "score": 0.75},
    ]

    emb = MagicMock()
    emb.embedding_vector = np.ones(384, dtype=np.float32).tobytes()

    with patch("music_teacher_ai.search.similar_search.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = emb
        mock_session_ctx.return_value = mock_session

        results = find_similar_by_song(song_id=1, top_k=2)

    assert all(r["id"] != 1 for r in results)
    assert len(results) == 2


def test_find_similar_by_song_missing_embedding():
    from music_teacher_ai.search.similar_search import find_similar_by_song

    with patch("music_teacher_ai.search.similar_search.get_session") as mock_session_ctx:
        mock_session = MagicMock()
        mock_session.__enter__ = MagicMock(return_value=mock_session)
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.exec.return_value.first.return_value = None
        mock_session_ctx.return_value = mock_session

        with pytest.raises(ValueError, match="No embedding found"):
            find_similar_by_song(song_id=999)


def test_min_score_filtering():
    """Results below min_score should be filtered out."""
    from music_teacher_ai.search.similar_search import find_similar_by_text

    with patch("music_teacher_ai.search.similar_search._load_model") as mock_model, \
         patch("music_teacher_ai.search.similar_search._search") as mock_search:

        mock_model.return_value.encode.return_value = np.ones((1, 384), dtype=np.float32)
        mock_search.return_value = [
            {"id": 1, "title": "A", "artist": "X", "year": 1990, "score": 0.9},
            {"id": 2, "title": "B", "artist": "Y", "year": 1991, "score": 0.5},
            {"id": 3, "title": "C", "artist": "Z", "year": 1992, "score": 0.3},
        ]

        results = find_similar_by_text("dreaming of freedom", top_k=10, min_score=0.6)

    assert len(results) == 1
    assert results[0]["id"] == 1
