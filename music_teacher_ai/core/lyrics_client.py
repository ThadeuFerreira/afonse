import logging
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
logger = logging.getLogger(__name__)


def _debug_enabled() -> bool:
    return os.getenv("DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


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
        if _debug_enabled():
            logger.warning(
                "genius client reinit token_present=%s token_prefix=%s",
                bool(token),
                token[:6] if token else "",
            )
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
        if _debug_enabled():
            logger.warning("genius search start title=%r artist=%r", title, artist)
        song = genius.search_song(title, artist)
        if song and song.lyrics:
            if _debug_enabled():
                logger.warning(
                    "genius search hit title=%r artist=%r matched_title=%r matched_artist=%r",
                    title,
                    artist,
                    getattr(song, "title", ""),
                    (
                        getattr(getattr(song, "artist", None), "name", None)
                        or getattr(song, "artist", "")
                    ),
                )
            return normalize_lyrics(song.lyrics)
        if _debug_enabled():
            logger.warning("genius search not_found title=%r artist=%r", title, artist)
    except GeniusTokenMissingError:
        raise
    except Exception as exc:
        if _debug_enabled():
            logger.warning(
                "genius search error title=%r artist=%r error=%s",
                title,
                artist,
                exc,
            )
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
