import faiss
import numpy as np
from rich.console import Console
from sqlmodel import select

from music_teacher_ai.config.settings import EMBEDDING_DIM, EMBEDDING_MODEL, FAISS_INDEX_PATH
from music_teacher_ai.database.models import Embedding, Lyrics
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.reporter import PipelineReport

console = Console()


def _load_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


def _load_or_create_index() -> faiss.IndexFlatIP:
    if FAISS_INDEX_PATH.exists():
        return faiss.read_index(str(FAISS_INDEX_PATH))
    return faiss.IndexFlatIP(EMBEDDING_DIM)


def generate_embeddings(batch_size: int = 32, rebuild: bool = False) -> None:
    report = PipelineReport("embeddings")
    with get_session() as session:
        if rebuild:
            from sqlmodel import delete
            session.exec(delete(Embedding))
            session.commit()
            # Also remove the FAISS file so _load_or_create_index() starts fresh
            if FAISS_INDEX_PATH.exists():
                FAISS_INDEX_PATH.unlink()
            embedded_ids: set[int] = set()
        else:
            embedded_ids = {
                row for row in session.exec(select(Embedding.song_id)).all()
            }

        lyrics_rows = session.exec(select(Lyrics)).all()
        pending = [l for l in lyrics_rows if l.song_id not in embedded_ids]

    if not pending:
        console.print("[yellow]No new lyrics to embed.[/yellow]")
        report.set("total", 0)
        report.save()
        return

    console.print(f"[cyan]Generating embeddings for {len(pending)} songs[/cyan]")
    report.set("total", len(pending))
    report.set("model", EMBEDDING_MODEL)
    report.set("batch_size", batch_size)
    model = _load_model()
    FAISS_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    index = _load_or_create_index()

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        texts = [l.lyrics_text for l in batch]
        vectors = model.encode(texts, normalize_embeddings=True)

        # FAISS assigns sequential IDs starting from index.ntotal
        base_faiss_id = index.ntotal
        index.add(np.array(vectors, dtype=np.float32))

        with get_session() as session:
            for offset, (lyr, vec) in enumerate(zip(batch, vectors)):
                session.add(
                    Embedding(
                        song_id=lyr.song_id,
                        embedding_vector=vec.astype(np.float32).tobytes(),
                        faiss_id=base_faiss_id + offset,
                    )
                )
            session.commit()
        console.print(f"  embedded {min(i + batch_size, len(pending))}/{len(pending)}")

    faiss.write_index(index, str(FAISS_INDEX_PATH))

    report.set("embedded", len(pending))
    report.set("faiss_index_size", index.ntotal)
    report.set("faiss_path", str(FAISS_INDEX_PATH))
    report_path = report.save()

    console.print(f"[green]Embeddings complete.[/green] FAISS index saved to {FAISS_INDEX_PATH}")
    console.print(f"[dim]Report: {report_path}[/dim]")
