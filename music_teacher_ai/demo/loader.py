"""
Minimal Mode demo dataset loader.

Auto-activates when the songs table is empty (fresh install or no init).
Populates the database with 10 well-known songs using the same schema as
the full database so all core features work immediately.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_DEMO_PATH = Path(__file__).resolve().parent / "demo_songs.json"

# Keys whose absence in the environment triggers a credential warning.
_CREDENTIAL_KEYS = [
    ("GENIUS_ACCESS_TOKEN", "Genius API"),
    ("SPOTIFY_CLIENT_ID", "Spotify API"),
    ("LASTFM_API_KEY", "Last.fm API"),
]


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def is_db_empty() -> bool:
    """Return True when the songs table has no rows (DB is uninitialised)."""
    from sqlmodel import func, select

    from music_teacher_ai.database.models import Song
    from music_teacher_ai.database.sqlite import get_session

    try:
        with get_session() as session:
            count = session.exec(select(func.count()).select_from(Song)).one()
            return count == 0
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_demo_songs() -> int:
    """
    Insert the 10 demo songs (artists + songs + lyrics) into the database.

    Idempotent: songs already present (matched by title + artist) are skipped.

    Returns:
        Number of songs actually inserted.
    """
    from sqlmodel import select

    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.database.sqlite import get_session

    raw: list[dict] = json.loads(_DEMO_PATH.read_text(encoding="utf-8"))
    inserted = 0

    with get_session() as session:
        for entry in raw:
            # get-or-create artist
            artist_row = session.exec(
                select(Artist).where(Artist.name == entry["artist"])
            ).first()
            if not artist_row:
                artist_row = Artist(name=entry["artist"])
                session.add(artist_row)
                session.flush()

            # skip if song already exists
            existing = session.exec(
                select(Song)
                .where(Song.title == entry["title"])
                .where(Song.artist_id == artist_row.id)
            ).first()
            if existing:
                song_id = existing.id
            else:
                song = Song(
                    title=entry["title"],
                    artist_id=artist_row.id,
                    release_year=entry.get("year"),
                )
                session.add(song)
                session.flush()
                song_id = song.id
                inserted += 1

            # insert lyrics if absent
            lyr = session.exec(
                select(Lyrics).where(Lyrics.song_id == song_id)
            ).first()
            if not lyr and entry.get("lyrics"):
                session.add(Lyrics(song_id=song_id, lyrics_text=entry["lyrics"]))

        session.commit()

    return inserted


# ---------------------------------------------------------------------------
# Auto-activation
# ---------------------------------------------------------------------------

def auto_load_demo_if_needed() -> bool:
    """
    Check whether the DB is empty and, if so, populate it with demo data.

    Called at CLI startup so the very first invocation of any command already
    has data.  Prints the minimal-mode banner when demo data is loaded.

    Returns:
        True if minimal mode was activated (demo data was loaded).
    """
    from music_teacher_ai.database.sqlite import create_db

    create_db()   # idempotent — creates schema if absent

    if not is_db_empty():
        return False

    load_demo_songs()
    print_minimal_banner()
    return True


# ---------------------------------------------------------------------------
# User-facing messages
# ---------------------------------------------------------------------------

def print_minimal_banner() -> None:
    """Print the minimal-mode startup notice."""
    from rich.console import Console
    from rich.panel import Panel

    console = Console()
    console.print(Panel(
        "[bold yellow]Running in MINIMAL MODE[/bold yellow]\n\n"
        "A demo dataset with 10 songs has been loaded.\n"
        "External APIs are [dim]disabled[/dim].\n\n"
        "To enable full functionality:\n\n"
        "  1. Configure API credentials  →  [cyan]music-teacher config[/cyan]\n"
        "  2. Initialise the full DB     →  [cyan]music-teacher init[/cyan]",
        title="Music Teacher AI",
        border_style="yellow",
        expand=False,
    ))
    _print_credential_warning()


def _print_credential_warning() -> None:
    """Print which API credentials are missing, if any."""
    from rich.console import Console

    missing = [label for key, label in _CREDENTIAL_KEYS if not os.getenv(key)]
    if not missing:
        return

    console = Console()
    lines = ["No API credentials detected.\n", "External services disabled:"]
    for label in missing:
        lines.append(f"  [dim]- {label}[/dim]")
    lines += [
        "",
        "Database enrichment and expansion features will not be available.",
        "Run [cyan]music-teacher config[/cyan] to set up credentials.",
    ]
    console.print("\n".join(lines))
