from dataclasses import dataclass
from typing import Optional

from music_teacher_ai.application.errors import ValidationError


@dataclass
class EnrichRequest:
    genre: Optional[str] = None
    artist: Optional[str] = None
    year: Optional[int] = None
    limit: int = 100
    max_pages: Optional[int] = None
    run_pipeline: bool = True


def run_enrichment(req: EnrichRequest) -> dict:
    from music_teacher_ai.pipeline.enrichment import enrich_database

    if not any([req.genre, req.artist, req.year]):
        raise ValidationError("Provide at least one of: genre, artist, year.")

    result = enrich_database(
        genre=req.genre,
        artist=req.artist,
        year=req.year,
        limit=req.limit,
        max_pages=req.max_pages,
        run_pipeline=req.run_pipeline,
    )
    return {
        "requested": req.limit,
        "new_songs_inserted": result.new_songs_inserted,
        "duplicates_skipped": result.duplicates_skipped,
    }
