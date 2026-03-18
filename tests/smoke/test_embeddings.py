"""
Smoke tests for the local embedding model and FAISS index.

No external API required — uses the local sentence-transformers model.
The model is downloaded on first run (~90MB).

Verifies:
- SentenceTransformer model loads without error
- Embeddings have the correct dimensionality (384)
- Vectors are normalized (L2 norm ≈ 1.0)
- FAISS index can be created, populated, and searched
- Nearest-neighbor search returns the correct result
- Index can be saved and reloaded from disk
"""
import numpy as np
import pytest


def test_model_loads():
    """SentenceTransformer model loads without error."""
    from sentence_transformers import SentenceTransformer
    from music_teacher_ai.config.settings import EMBEDDING_MODEL

    model = SentenceTransformer(EMBEDDING_MODEL)
    assert model is not None


def test_embedding_shape():
    """A single text produces a vector of the expected dimensionality."""
    from sentence_transformers import SentenceTransformer
    from music_teacher_ai.config.settings import EMBEDDING_MODEL, EMBEDDING_DIM

    model = SentenceTransformer(EMBEDDING_MODEL)
    vec = model.encode(["Imagine there's no heaven"], normalize_embeddings=True)

    assert vec.shape == (1, EMBEDDING_DIM), f"Unexpected shape: {vec.shape}"


def test_embedding_normalized():
    """Normalized embeddings have L2 norm ≈ 1.0."""
    from sentence_transformers import SentenceTransformer
    from music_teacher_ai.config.settings import EMBEDDING_MODEL

    model = SentenceTransformer(EMBEDDING_MODEL)
    vec = model.encode(["test text"], normalize_embeddings=True)[0]

    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 1e-5, f"Vector not normalized, norm={norm}"


def test_semantic_similarity_ordering():
    """
    Two semantically similar sentences should be closer than
    a semantically dissimilar pair.
    """
    from sentence_transformers import SentenceTransformer
    from music_teacher_ai.config.settings import EMBEDDING_MODEL

    model = SentenceTransformer(EMBEDDING_MODEL)
    vecs = model.encode(
        [
            "I have a dream about freedom",    # anchor
            "Dreaming of liberty and hope",    # similar
            "The stock market fell sharply",   # dissimilar
        ],
        normalize_embeddings=True,
    )

    sim_similar = float(np.dot(vecs[0], vecs[1]))
    sim_dissimilar = float(np.dot(vecs[0], vecs[2]))

    assert sim_similar > sim_dissimilar, (
        f"Similar pair score ({sim_similar:.3f}) should exceed "
        f"dissimilar pair score ({sim_dissimilar:.3f})"
    )


def test_faiss_index_add_and_search():
    """FAISS index correctly returns nearest neighbor."""
    import faiss
    from music_teacher_ai.config.settings import EMBEDDING_DIM

    index = faiss.IndexFlatIP(EMBEDDING_DIM)

    vecs = np.random.randn(10, EMBEDDING_DIM).astype(np.float32)
    # Normalize
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = vecs / norms

    index.add(vecs)
    assert index.ntotal == 10

    # Query with the third vector — nearest neighbor should be itself (position 2)
    query = vecs[2:3]
    distances, indices = index.search(query, k=1)

    assert indices[0][0] == 2, f"Expected position 2, got {indices[0][0]}"
    assert abs(distances[0][0] - 1.0) < 1e-5, f"Self-similarity should be 1.0, got {distances[0][0]}"


def test_faiss_index_save_and_reload(tmp_path):
    """Index can be written to disk and reloaded with identical results."""
    import faiss
    from music_teacher_ai.config.settings import EMBEDDING_DIM

    index_path = str(tmp_path / "test.index")

    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    vec = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
    vec /= np.linalg.norm(vec)
    index.add(vec)
    faiss.write_index(index, index_path)

    reloaded = faiss.read_index(index_path)
    assert reloaded.ntotal == 1

    distances, indices = reloaded.search(vec, k=1)
    assert indices[0][0] == 0
