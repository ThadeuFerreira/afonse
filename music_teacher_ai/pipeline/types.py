from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class CandidateSong:
    title: str
    artist: str
    year: Optional[int] = None


@dataclass
class EnrichmentResult:
    genre: Optional[str] = None
    artist: Optional[str] = None
    year: Optional[int] = None
    requested_limit: int = 100
    api_results_processed: int = 0
    new_songs_inserted: int = 0
    duplicates_skipped: int = 0
    api_requests: int = 0
    stop_reason: str = ""


@dataclass
class Variant:
    name: str
    fetch_fn: Callable[[int], list[CandidateSong]]
    max_page: int
    tried_pages: set[int] = field(default_factory=set)
    new_count: int = 0
    skip_count: int = 0
    min_variant_tries: int = 3
    dup_threshold: float = 0.9

    def next_page(self) -> Optional[int]:
        import random

        available = [p for p in range(1, self.max_page + 1) if p not in self.tried_pages]
        return random.choice(available) if available else None

    def record(self, page: int, new: int, skipped: int) -> None:
        self.tried_pages.add(page)
        self.new_count += new
        self.skip_count += skipped

    @property
    def dup_ratio(self) -> float:
        total = self.new_count + self.skip_count
        return self.skip_count / total if total > 0 else 0.0

    @property
    def is_exhausted(self) -> bool:
        return len(self.tried_pages) >= self.max_page

    def is_saturated(self) -> bool:
        return len(self.tried_pages) >= self.min_variant_tries and self.dup_ratio >= self.dup_threshold

