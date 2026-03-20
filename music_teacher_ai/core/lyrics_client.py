import os
import re
import threading
from typing import Optional

import lyricsgenius
from dotenv import load_dotenv

from music_teacher_ai.core.api_cache import cached_api

# Thread-local storage so each worker thread gets its own Genius session.
# lyricsgenius uses requests.Session internally which is not thread-safe.
_thread_local = threading.local()


class GeniusTokenMissingError(RuntimeError):
    """Raised when GENIUS_ACCESS_TOKEN is not configured."""


def _get_token() -> str:
    """Read the Genius token from the environment, reloading .env if needed."""
    token = os.getenv("GENIUS_ACCESS_TOKEN", "")
    if not token:
        load_dotenv()
        token = os.getenv("GENIUS_ACCESS_TOKEN", "")
    return token


def get_genius() -> lyricsgenius.Genius:
    token = _get_token()
    if not token:
        raise GeniusTokenMissingError(
            "GENIUS_ACCESS_TOKEN is not set. "
            "Run 'music-teacher config' to add your Genius API token."
        )
    # Re-create the client when the token changes (e.g. after config update)
    existing: lyricsgenius.Genius | None = getattr(_thread_local, "genius", None)
    if existing is None or getattr(_thread_local, "genius_token", None) != token:
        _thread_local.genius = lyricsgenius.Genius(
            token,
            skip_non_songs=True,
            excluded_terms=["(Remix)", "(Live)"],
            remove_section_headers=True,
            verbose=False,
        )
        _thread_local.genius_token = token
    return _thread_local.genius


@cached_api("genius")
def fetch_lyrics(title: str, artist: str) -> Optional[str]:
    genius = get_genius()
    try:
        song = genius.search_song(title, artist)
        if song and song.lyrics:
            return normalize_lyrics(song.lyrics)
    except GeniusTokenMissingError:
        raise
    except Exception:
        pass
    return None


def normalize_lyrics(raw: str) -> str:
    # Remove section headers like [Chorus], [Verse 1], etc.
    text = re.sub(r"\[.*?\]", "", raw)
    # Remove leading title line that Genius prepends
    text = re.sub(r"^.*?Lyrics\n", "", text, flags=re.IGNORECASE)
    # Normalize whitespace
    text = re.sub(r"\r\n|\r", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
