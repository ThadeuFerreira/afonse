from dataclasses import dataclass
from typing import Optional, Protocol


class ExpansionJobRunner(Protocol):
    def trigger_expansion(
        self,
        genre: Optional[str] = None,
        artist: Optional[str] = None,
        year: Optional[int] = None,
        word: Optional[str] = None,
    ) -> bool:
        ...


@dataclass
class InProcessExpansionRunner:
    def trigger_expansion(
        self,
        genre: Optional[str] = None,
        artist: Optional[str] = None,
        year: Optional[int] = None,
        word: Optional[str] = None,
    ) -> bool:
        from music_teacher_ai.pipeline.expansion import trigger_expansion

        return trigger_expansion(genre=genre, artist=artist, year=year, word=word)


def get_job_runner() -> ExpansionJobRunner:
    return InProcessExpansionRunner()

