from dataclasses import dataclass
from typing import Optional

from music_teacher_ai.search.keyword_search import search_songs
from music_teacher_ai.search.semantic_search import semantic_search


@dataclass
class SearchRequest:
    word: Optional[str] = None
    year: Optional[int] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    limit: int = 20


def keyword_search_with_expansion(req: SearchRequest) -> dict:
    from music_teacher_ai.pipeline.jobs import get_job_runner
    from music_teacher_ai.pipeline.expansion import EXPANSION_THRESHOLD

    results = search_songs(
        word=req.word,
        year=req.year,
        year_min=req.year_min,
        year_max=req.year_max,
        artist=req.artist,
        genre=req.genre,
        limit=req.limit,
    )
    triggered = False
    if len(results) < EXPANSION_THRESHOLD:
        triggered = get_job_runner().trigger_expansion(
            genre=req.genre,
            artist=req.artist,
            year=req.year,
            word=req.word,
        )
    return {"results": results, "database_expansion_triggered": triggered}


def semantic_query(query: str, top_k: int = 10):
    return semantic_search(query, top_k=top_k)

