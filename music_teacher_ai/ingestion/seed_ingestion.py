"""
Seed the database with well-known songs from songs_seed.json.

Upserts Artist and Song rows (matching by name / title+artist_id) so the
function is safe to call multiple times.  All seeded songs are marked with
metadata_source='lyrics_only' — they never go through Billboard / Spotify /
MusicBrainz enrichment.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import select

from music_teacher_ai.database.models import Artist, Song
from music_teacher_ai.database.sqlite import get_session

_SEED_FILE = Path(__file__).resolve().parent / "songs_seed.json"


def seed_songs() -> dict[str, int]:
    """Load songs_seed.json and upsert artists + songs into the database.

    Returns {"inserted": N, "skipped": N}.
    """
    entries = json.loads(_SEED_FILE.read_text())
    inserted = skipped = 0

    with get_session() as session:
        for entry in entries:
            title: str = entry["title"]
            artist_name: str = entry["artist"]
            year: int | None = entry.get("year")

            # Upsert artist
            artist = session.exec(
                select(Artist).where(Artist.name == artist_name)
            ).first()
            if not artist:
                artist = Artist(name=artist_name)
                session.add(artist)
                session.flush()  # populate artist.id

            # Upsert song (skip if title+artist already exists)
            existing = session.exec(
                select(Song)
                .where(Song.title == title)
                .where(Song.artist_id == artist.id)
            ).first()
            if existing:
                skipped += 1
                continue

            session.add(Song(
                title=title,
                artist_id=artist.id,
                release_year=year,
                metadata_source="lyrics_only",
            ))
            inserted += 1

        session.commit()

    return {"inserted": inserted, "skipped": skipped}
