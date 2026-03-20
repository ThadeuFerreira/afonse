import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedQuery:
    word: Optional[str] = None
    year: Optional[int] = None
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    artist: Optional[str] = None
    genre: Optional[str] = None
    semantic_query: Optional[str] = None


# Matches: "90s", "60s" (two-digit), "1990s", "1960s", "2020s" (four-digit)
_DECADE_RE = re.compile(r"\b((?:19|20)\d0s|\d0s)\b")
_YEAR_RE = re.compile(r"\b(1[6-9]\d{2}|20[0-2]\d)\b")
_WORD_RE = re.compile(r'\bword[s]?\s+["\']?(\w+)["\']?', re.IGNORECASE)
_ARTIST_RE = re.compile(r'\bby\s+["\']?([A-Za-z\s]+)["\']?', re.IGNORECASE)


def parse_natural_language(query: str) -> ParsedQuery:
    """
    Lightweight rule-based parser. Converts natural language queries into
    structured search parameters without requiring an LLM.

    Examples:
        "songs from the 90s with the word dream"
        → year_min=1990, year_max=1999, word="dream"

        "songs about friendship by Adele"
        → semantic_query="songs about friendship", artist="Adele"
    """
    result = ParsedQuery()

    # Decade detection: "90s" → 1990–1999, "1990s" → 1990–1999, "2020s" → 2020–2029
    decade_match = _DECADE_RE.search(query)
    if decade_match:
        decade_str = decade_match.group(1)          # e.g. "90s" or "1990s"
        digits = decade_str.rstrip("s")             # "90" or "1990"
        decade_val = int(digits)
        if decade_val < 100:                        # two-digit shorthand: 90 → 1990
            decade_val += 1900
        result.year_min = decade_val
        result.year_max = decade_val + 9

    # Exact year: "in 1995", "from 2003"
    if not result.year_min:
        year_match = _YEAR_RE.search(query)
        if year_match:
            result.year = int(year_match.group(1))

    # Keyword: "with the word X" or "containing X"
    word_match = _WORD_RE.search(query)
    if word_match:
        result.word = word_match.group(1).lower()
    else:
        # Look for "containing <word>"
        containing = re.search(r'\bcontaining\s+["\']?(\w+)["\']?', query, re.IGNORECASE)
        if containing:
            result.word = containing.group(1).lower()

    # Artist: "by <name>"
    artist_match = _ARTIST_RE.search(query)
    if artist_match:
        result.artist = artist_match.group(1).strip()

    # If the query talks about themes/concepts, treat it as semantic
    semantic_triggers = ["about", "theme", "feeling", "mood", "topic", "concept"]
    if any(t in query.lower() for t in semantic_triggers):
        result.semantic_query = query

    return result
