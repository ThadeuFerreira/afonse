"""
Similar Lyrics Search

Three query modes:
  - find_similar_by_song(song_id, top_k, min_score)   → use stored embedding
  - find_similar_by_title(title, artist, top_k, ...)  → look up song, then same
  - find_similar_by_text(text, top_k, min_score)      → encode text on-the-fly
"""
import faiss
import numpy as np
from sqlmodel import select

from music_teacher_ai.config.settings import EMBEDDING_MODEL, FAISS_INDEX_PATH
from music_teacher_ai.database.models import Artist, Embedding, Song
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.search.semantic_search import _faiss_ids_to_songs


def _load_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


def _load_index() -> faiss.IndexFlatIP:
    if not FAISS_INDEX_PATH.exists():
        raise FileNotFoundError("FAISS index not found. Run embeddings pipeline first.")
    return faiss.read_index(str(FAISS_INDEX_PATH))


def _search(vec: np.ndarray, top_k: int, exclude_song_id: int | None = None) -> list[dict]:
    """Run FAISS search and resolve results, optionally excluding the query song."""
    index = _load_index()
    # Fetch one extra so we can drop the query song if it appears
    k = top_k + 1 if exclude_song_id is not None else top_k
    distances, indices = index.search(vec.reshape(1, -1), k)

    results = _faiss_ids_to_songs(indices[0].tolist(), distances[0].tolist())

    if exclude_song_id is not None:
        results = [r for r in results if r["id"] != exclude_song_id]

    return results[:top_k]


def find_similar_by_song(
    song_id: int,
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict]:
    """Find songs whose lyrics are semantically similar to the given song."""
    with get_session() as session:
        emb = session.exec(
            select(Embedding).where(Embedding.song_id == song_id)
        ).first()
        if not emb:
            raise ValueError(f"No embedding found for song_id={song_id}. Run the embedding pipeline first.")
        vec = np.frombuffer(emb.embedding_vector, dtype=np.float32).copy()

    results = _search(vec, top_k, exclude_song_id=song_id)
    return [r for r in results if r["score"] >= min_score]


def find_similar_by_title(
    title: str,
    artist: str | None = None,
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict]:
    """Find a song by title (and optionally artist), then return similar songs."""
    with get_session() as session:
        query = select(Song).where(Song.title.ilike(f"%{title}%"))
        songs = session.exec(query).all()

        if artist:
            matched = []
            for s in songs:
                a = session.get(Artist, s.artist_id)
                if a and artist.lower() in a.name.lower():
                    matched.append(s)
            songs = matched

        if not songs:
            raise ValueError(f"Song not found: {title!r}")

        song = songs[0]

    return find_similar_by_song(song.id, top_k=top_k, min_score=min_score)


def find_similar_by_text(
    text: str,
    top_k: int = 10,
    min_score: float = 0.0,
) -> list[dict]:
    """Find songs whose lyrics are semantically similar to the given text fragment."""
    model = _load_model()
    vec = model.encode([text], normalize_embeddings=True).astype(np.float32)[0]
    results = _search(vec, top_k)
    return [r for r in results if r["score"] >= min_score]
