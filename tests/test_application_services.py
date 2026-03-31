from unittest.mock import patch

import pytest

from music_teacher_ai.application.enrichment_service import EnrichRequest, run_enrichment
from music_teacher_ai.application.errors import ValidationError
from music_teacher_ai.application.search_service import SearchRequest, keyword_search_with_expansion


def test_run_enrichment_requires_criteria():
    with pytest.raises(ValidationError, match="at least one"):
        run_enrichment(EnrichRequest(limit=10))


def test_run_enrichment_maps_pipeline_result():
    class FakeResult:
        new_songs_inserted = 3
        duplicates_skipped = 7

    with patch("music_teacher_ai.pipeline.enrichment.enrich_database", return_value=FakeResult()):
        payload = run_enrichment(EnrichRequest(genre="jazz", limit=10))
    assert payload == {"requested": 10, "new_songs_inserted": 3, "duplicates_skipped": 7}


def test_keyword_search_with_expansion_uses_policy(monkeypatch):
    monkeypatch.setattr(
        "music_teacher_ai.application.search_service.search_songs",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        "music_teacher_ai.pipeline.expansion.EXPANSION_THRESHOLD",
        10,
    )

    class FakeRunner:
        def trigger_expansion(self, **kwargs):
            return kwargs["genre"] == "rock"

    monkeypatch.setattr(
        "music_teacher_ai.pipeline.jobs.get_job_runner",
        lambda: FakeRunner(),
    )

    response = keyword_search_with_expansion(SearchRequest(genre="rock", limit=20))
    assert response["results"] == []
    assert response["database_expansion_triggered"] is True
