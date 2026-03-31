"""
Pipeline stage reporter.

Every ingestion stage creates a PipelineReport at startup and calls .save()
when done. The JSON report is written to REPORTS_DIR (default: data/reports/)
and can be used to audit how well each external service is behaving over time.

Usage:
    report = PipelineReport("lyrics")
    report.increment("downloaded")
    report.add_event("rate_limit", new_workers=2, wait_seconds=60)
    report.add_error(song_id=42, title="Imagine", error="404 not found")
    path = report.save()
"""

import json
from datetime import datetime
from pathlib import Path

from music_teacher_ai.config.settings import REPORTS_DIR

# Maximum errors stored inline in the report (keeps files manageable).
_MAX_INLINE_ERRORS = 200


class PipelineReport:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self.started_at: datetime = datetime.now()
        self._counters: dict[str, int] = {}
        self._events: list[dict] = []
        self._errors: list[dict] = []

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def increment(self, key: str, by: int = 1) -> None:
        """Increment a named counter (e.g. "downloaded", "failed", "skipped")."""
        self._counters[key] = self._counters.get(key, 0) + by

    def set(self, key: str, value) -> None:
        """Set a named counter to an exact value."""
        self._counters[key] = value

    def add_event(self, message: str, **kwargs) -> None:
        """Record a notable event (rate limit, source switch, hard stop, etc.)."""
        self._events.append({"time": datetime.now().isoformat(), "message": message, **kwargs})

    def add_error(self, **kwargs) -> None:
        """Record a per-item failure. Capped at _MAX_INLINE_ERRORS."""
        if len(self._errors) < _MAX_INLINE_ERRORS:
            self._errors.append({"time": datetime.now().isoformat(), **kwargs})

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> Path:
        """Write the report to REPORTS_DIR and return its path."""
        finished_at = datetime.now()
        duration = (finished_at - self.started_at).total_seconds()

        payload = {
            "stage": self.stage,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round(duration, 1),
            **self._counters,
            "events": self._events,
            "errors": self._errors,
        }

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = self.started_at.strftime("%Y%m%d_%H%M%S")
        path = REPORTS_DIR / f"{self.stage}_{ts}.json"
        path.write_text(json.dumps(payload, indent=2, default=str))
        return path
