import faiss
import numpy as np
from sqlmodel import select

from music_teacher_ai.config.settings import EMBEDDING_MODEL, FAISS_INDEX_PATH
from music_teacher_ai.database.models import Artist, Embedding, Song
from music_teacher_ai.database.sqlite import get_session


def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def _faiss_ids_to_songs(faiss_ids: list[int], scores: list[float]) -> list[dict]:
    """Resolve FAISS index positions to song dicts using the stored faiss_id column."""
    with get_session() as session:
        results = []
        for faiss_id, score in zip(faiss_ids, scores):
            if faiss_id < 0:
                continue
            emb = session.exec(select(Embedding).where(Embedding.faiss_id == faiss_id)).first()
            if not emb:
                continue
            song = session.get(Song, emb.song_id)
            if not song:
                continue
            artist = session.get(Artist, song.artist_id)
            results.append(
                {
                    "id": song.id,
                    "title": song.title,
                    "artist": artist.name if artist else "",
                    "year": song.release_year,
                    "score": round(float(score), 4),
                }
            )
    return results


def semantic_search(query: str, top_k: int = 10) -> list[dict]:
    if not FAISS_INDEX_PATH.exists():
        raise FileNotFoundError("FAISS index not found. Run embeddings pipeline first.")

    model = _load_model()
    query_vec = model.encode([query], normalize_embeddings=True).astype(np.float32)

    index = faiss.read_index(str(FAISS_INDEX_PATH))
    distances, indices = index.search(query_vec, top_k)

    return _faiss_ids_to_songs(indices[0].tolist(), distances[0].tolist())
