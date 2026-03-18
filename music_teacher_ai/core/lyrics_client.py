import re
from typing import Optional
import lyricsgenius

from music_teacher_ai.config.settings import GENIUS_ACCESS_TOKEN


_genius: lyricsgenius.Genius | None = None


def get_genius() -> lyricsgenius.Genius:
    global _genius
    if _genius is None:
        _genius = lyricsgenius.Genius(
            GENIUS_ACCESS_TOKEN,
            skip_non_songs=True,
            excluded_terms=["(Remix)", "(Live)"],
            remove_section_headers=True,
            verbose=False,
        )
    return _genius


def fetch_lyrics(title: str, artist: str) -> Optional[str]:
    genius = get_genius()
    try:
        song = genius.search_song(title, artist)
        if song and song.lyrics:
            return normalize_lyrics(song.lyrics)
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
