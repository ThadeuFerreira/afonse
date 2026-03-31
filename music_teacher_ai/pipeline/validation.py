"""
Ingestion data validation.

Validates song title, artist, and lyrics fields before they are written to
the database.  Corrupt records (JSON fragments, URLs in title/artist, suspiciously
short or long values) are rejected so they never enter the main songs table.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://|www\.", re.I)
_JSON_RE = re.compile(r"^\s*[\[{]")  # starts with [ or {
_EMBED_RE = re.compile(r'"[a-z_]+"\s*:')  # "key": pattern inside text
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

MAX_TITLE_LEN = 200
MAX_ARTIST_LEN = 200
MIN_LYRICS_LEN = 20  # chars — shorter is almost certainly a fetch error
MAX_LYRICS_LEN = 10_000

# Word-count thresholds
# Real song lyrics are typically under 500 words.
# 500–1000 words is unusual but not impossible — flagged as suspicious.
# Over 1000 words is almost certainly metadata noise — hard-blocked.
SUSPICIOUS_WORD_COUNT = 500
MAX_WORD_COUNT = 1000

_WORD_RE = re.compile(r"\b[a-z']+\b", re.I)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        """Record a hard failure — sets ok=False."""
        self.issues.append(msg)
        self.ok = False

    def warn(self, msg: str) -> None:
        """Record a soft warning — ok stays True."""
        self.warnings.append(msg)

    def __str__(self) -> str:
        parts = self.issues + [f"[warn] {w}" for w in self.warnings]
        return "; ".join(parts) if parts else "ok"


# ---------------------------------------------------------------------------
# Field validators
# ---------------------------------------------------------------------------


def validate_title(title: Optional[str]) -> ValidationResult:
    r = ValidationResult(ok=True)
    if not title or not title.strip():
        r.add("title is empty")
        return r
    if len(title) > MAX_TITLE_LEN:
        r.add(f"title too long ({len(title)} chars, max {MAX_TITLE_LEN})")
    if _URL_RE.search(title):
        r.add("title contains URL")
    if _JSON_RE.match(title):
        r.add("title looks like JSON")
    if _CTRL_RE.search(title):
        r.add("title contains control characters")
    return r


def validate_artist(artist: Optional[str]) -> ValidationResult:
    r = ValidationResult(ok=True)
    if not artist or not artist.strip():
        r.add("artist is empty")
        return r
    if len(artist) > MAX_ARTIST_LEN:
        r.add(f"artist too long ({len(artist)} chars, max {MAX_ARTIST_LEN})")
    if _URL_RE.search(artist):
        r.add("artist contains URL")
    if _JSON_RE.match(artist):
        r.add("artist looks like JSON")
    if _CTRL_RE.search(artist):
        r.add("artist contains control characters")
    return r


def validate_lyrics(lyrics: Optional[str]) -> ValidationResult:
    r = ValidationResult(ok=True)
    if not lyrics or not lyrics.strip():
        r.add("lyrics are empty")
        return r
    text = lyrics.strip()
    if len(text) < MIN_LYRICS_LEN:
        r.add(f"lyrics too short ({len(text)} chars, min {MIN_LYRICS_LEN})")
    if len(text) > MAX_LYRICS_LEN:
        r.add(f"lyrics too long ({len(text)} chars, max {MAX_LYRICS_LEN})")
    # Word-count checks: real songs are typically < 500 words.
    word_count = len(_WORD_RE.findall(text))
    if word_count > MAX_WORD_COUNT:
        r.add(f"lyrics too long ({word_count} words, hard limit {MAX_WORD_COUNT})")
        return r  # no further checks needed
    if word_count > SUSPICIOUS_WORD_COUNT:
        r.warn(
            f"lyrics word count suspicious ({word_count} words, typical max {SUSPICIOUS_WORD_COUNT})"
        )
    # Detect JSON fragment stored as lyrics
    if _JSON_RE.match(text):
        r.add("lyrics start with JSON bracket")
        return r
    if _EMBED_RE.search(text[:500]):
        # Only flag when the JSON-key pattern appears *densely* in the first 500 chars
        count = len(_EMBED_RE.findall(text[:500]))
        if count >= 3:
            r.add(f"lyrics contain {count} JSON-key patterns (possible metadata fragment)")
    # Attempt JSON parse — valid JSON stored as lyrics is almost always wrong
    try:
        json.loads(text)
        r.add("lyrics parse as valid JSON — likely a metadata fragment")
    except (json.JSONDecodeError, ValueError):
        pass
    if _CTRL_RE.search(text):
        r.add("lyrics contain control characters")
    return r


# ---------------------------------------------------------------------------
# Composite validator
# ---------------------------------------------------------------------------


def validate_song(
    title: Optional[str],
    artist: Optional[str],
    lyrics: Optional[str] = None,
) -> ValidationResult:
    """Run all applicable validators and merge results."""
    combined = ValidationResult(ok=True)
    for r in [validate_title(title), validate_artist(artist)]:
        if not r.ok:
            combined.issues.extend(r.issues)
            combined.ok = False
    if lyrics is not None:
        r = validate_lyrics(lyrics)
        if not r.ok:
            combined.issues.extend(r.issues)
            combined.ok = False
    return combined


# ---------------------------------------------------------------------------
# Pipeline scope helper
# ---------------------------------------------------------------------------


def songs_needing_lyrics() -> set[int]:
    """
    Return the set of song IDs that the pipeline should process.

    A song needs (re-)processing when it either:
      - has no row in the Lyrics table, OR
      - has a lyrics row that fails validation (corrupt / metadata fragment).

    This keeps enrich_metadata and download_lyrics scoped to songs that still
    need work rather than re-scanning every song in the database.
    """
    from sqlmodel import select

    from music_teacher_ai.database.models import Lyrics
    from music_teacher_ai.database.sqlite import get_session

    with get_session() as session:
        all_lyrics = session.exec(select(Lyrics)).all()

    suspicious_ids: set[int] = set()
    good_ids: set[int] = set()
    for lyr in all_lyrics:
        if validate_lyrics(lyr.lyrics_text).ok:
            good_ids.add(lyr.song_id)
        else:
            suspicious_ids.add(lyr.song_id)

    # Songs with no lyrics row at all
    with get_session() as session:
        from sqlmodel import select

        from music_teacher_ai.database.models import Song

        all_song_ids = {row for row in session.exec(select(Song.id)).all()}

    no_lyrics_ids = all_song_ids - good_ids - suspicious_ids
    return no_lyrics_ids | suspicious_ids
