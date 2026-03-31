"""
Seed the database with well-known songs from songs_seed.json.

Upserts Artist and Song rows (matching by name / title+artist_id) so the
function is safe to call multiple times.  All seeded songs are marked with
metadata_source='lyrics_only' — they never go through Billboard / Spotify /
MusicBrainz enrichment.

Demo songs (metadata_source='demo') are upgraded to 'lyrics_only' and their
hardcoded lyrics are deleted so download_lyrics() will fetch real ones.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import select

from music_teacher_ai.database.models import Artist, Lyrics, Song
from music_teacher_ai.database.sqlite import get_session

_SEED_FILE = Path(__file__).resolve().parent / "songs_seed.json"


def seed_songs() -> dict[str, int]:
    """Load songs_seed.json and upsert artists + songs into the database.

    Demo songs are upgraded to real seed entries (hardcoded lyrics removed).

    Returns {"inserted": N, "upgraded": N, "skipped": N}.
    """
    entries = json.loads(_SEED_FILE.read_text())
    inserted = upgraded = skipped = 0

    with get_session() as session:
        for entry in entries:
            title: str = entry["title"]
            artist_name: str = entry["artist"]
            year: int | None = entry.get("year")

            # Upsert artist
            artist = session.exec(select(Artist).where(Artist.name == artist_name)).first()
            if not artist:
                artist = Artist(name=artist_name)
                session.add(artist)
                session.flush()  # populate artist.id

            existing = session.exec(
                select(Song).where(Song.title == title).where(Song.artist_id == artist.id)
            ).first()

            if existing:
                if existing.metadata_source == "demo":
                    # Upgrade: replace hardcoded demo lyrics so real ones get fetched
                    existing.metadata_source = "lyrics_only"
                    if year and not existing.release_year:
                        existing.release_year = year
                    session.add(existing)
                    # Remove hardcoded lyrics (word_count is None on demo lyrics)
                    lyr = session.exec(select(Lyrics).where(Lyrics.song_id == existing.id)).first()
                    if lyr is not None and lyr.word_count is None:
                        session.delete(lyr)
                    upgraded += 1
                else:
                    skipped += 1
                continue

            session.add(
                Song(
                    title=title,
                    artist_id=artist.id,
                    release_year=year,
                    metadata_source="lyrics_only",
                )
            )
            inserted += 1

        session.commit()

    return {"inserted": inserted, "upgraded": upgraded, "skipped": skipped}
