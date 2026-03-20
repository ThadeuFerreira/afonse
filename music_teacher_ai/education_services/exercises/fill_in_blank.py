"""
Fill-in-the-blank exercise generator.

Selects content words from song lyrics and replaces them with numbered blank
placeholders.  Stop words (articles, prepositions, auxiliaries, pronouns) are
never blanked so the resulting exercise remains grammatically coherent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Word lists
# ---------------------------------------------------------------------------

_STOP_WORDS: frozenset[str] = frozenset({
    # Articles
    "a", "an", "the",
    # Coordinating conjunctions
    "and", "but", "or", "nor", "for", "yet", "so", "both", "either",
    # Prepositions
    "in", "on", "at", "to", "for", "of", "with", "by", "from", "up",
    "about", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "around", "along",
    # Personal pronouns
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "he", "him", "his", "himself",
    "she", "her", "hers", "herself", "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves",
    # Interrogatives / relatives
    "what", "which", "who", "whom", "whose", "where", "when", "why", "how",
    # Demonstratives
    "this", "that", "these", "those",
    # Auxiliaries
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having", "do", "does", "did", "doing",
    "will", "would", "shall", "should", "may", "might", "must",
    "can", "could", "need", "dare", "ought",
    # Common function adverbs
    "not", "no", "nor", "just", "also", "very", "too", "so", "more",
    "most", "only", "here", "there", "now", "then", "still", "already",
    "again", "really", "quite", "rather",
    # Subordinating conjunctions
    "if", "when", "while", "as", "because", "since", "though",
    "although", "until", "unless", "than", "else", "whether",
    # Misc
    "oh", "ah", "yeah", "hey", "like", "well", "even",
})


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Blank:
    number: int
    word: str


@dataclass
class FillInBlankExercise:
    song_title: str
    artist: str
    text_with_blanks: str       # lyrics with _(N)_ substitutions
    answer_key: list[str]       # ordered list of blanked words
    blanks: list[Blank]         # same data, structured
    total_words: int
    blanked_count: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate(
    lyrics: str,
    song_title: str = "",
    artist: str = "",
    num_blanks: int = 10,
    min_word_length: int = 4,
) -> FillInBlankExercise:
    """
    Generate a fill-in-the-blank exercise from song lyrics.

    Args:
        lyrics:          Raw lyrics text.
        song_title:      Song title (for display only).
        artist:          Artist name (for display only).
        num_blanks:      Maximum number of words to blank out.
        min_word_length: Ignore words shorter than this (avoids blanking
                         short words like "be" or "run").

    Returns:
        FillInBlankExercise with numbered blanks and an answer key.
    """
    lines = lyrics.strip().splitlines()

    # --- collect candidates: unique content words in order of appearance ---
    seen: set[str] = set()
    candidates: list[str] = []          # lowercase unique content words

    for line in lines:
        for word in re.findall(r"\b[a-zA-Z]+\b", line):
            lower = word.lower()
            if lower not in _STOP_WORDS and len(lower) >= min_word_length and lower not in seen:
                seen.add(lower)
                candidates.append(lower)
            if len(candidates) >= num_blanks:
                break
        if len(candidates) >= num_blanks:
            break

    blank_set = set(candidates[:num_blanks])

    # --- build blanked text ---
    blank_counter = 0
    total_words = 0
    blanks: list[Blank] = []
    blanked_lines: list[str] = []

    for line in lines:
        def _replace(match: re.Match) -> str:   # noqa: E731
            nonlocal blank_counter, total_words
            word = match.group(0)
            total_words += 1
            if word.lower() in blank_set:
                blank_counter += 1
                blanks.append(Blank(number=blank_counter, word=word))
                blank_set.discard(word.lower())     # blank each word once only
                return f"_({blank_counter})_"
            return word

        blanked_lines.append(re.sub(r"\b[a-zA-Z]+\b", _replace, line))

    return FillInBlankExercise(
        song_title=song_title,
        artist=artist,
        text_with_blanks="\n".join(blanked_lines),
        answer_key=[b.word for b in blanks],
        blanks=blanks,
        total_words=total_words,
        blanked_count=len(blanks),
    )
