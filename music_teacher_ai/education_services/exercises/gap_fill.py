"""
Listening "fill-the-gaps" exercise generator.

Produces a text where selected words are replaced with underscore blanks whose
length reflects the original word (word_length × 1.33, minimum 3 characters).
Punctuation adjacent to blanked words is preserved.

Two selection modes are supported:

  random  – blanks approximately `level` percent of all word positions.
  manual  – blanks every occurrence of each explicitly supplied word.

The architecture is open: future strategies (verbs, nouns, phrasal-verbs …)
only need to provide a list of (start, end, word) spans to ``_apply_blanks``.
"""
from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BLANK_SCALE = 1.33          # blank is 33% longer than the word
_MIN_BLANK = 3               # minimum underscore count


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

SelectionMode = Literal["random", "manual"]

Span = tuple[int, int, str]    # (start_char, end_char, word_text)


@dataclass
class GapFillExercise:
    song_title: str
    artist: str
    text_with_gaps: str          # lyrics with blanks substituted
    answer_key: list[str]        # words in order of appearance
    total_words: int
    blanked_count: int
    mode: SelectionMode
    level: Optional[int] = None          # percentage used in random mode
    selected_words: Optional[list[str]] = None  # words used in manual mode


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _blank_for(word: str) -> str:
    """Return an underscore blank scaled to the word's length."""
    length = max(_MIN_BLANK, math.ceil(len(word) * _BLANK_SCALE))
    return "_" * length


def _tokenize(text: str) -> list[Span]:
    """Return (start, end, word) for every alphabetic token in *text*."""
    return [(m.start(), m.end(), m.group()) for m in re.finditer(r"[a-zA-Z]+", text)]


def _apply_blanks(text: str, spans: list[Span]) -> tuple[str, list[str]]:
    """
    Replace each span in *text* with an underscore blank.

    Spans must be non-overlapping.  Adjacent punctuation (e.g. the ``!`` in
    ``world!``) is untouched because the regex captures only alphabetic runs.

    Returns (text_with_gaps, answer_key).
    """
    if not spans:
        return text, []

    parts: list[str] = []
    answer_key: list[str] = []
    prev = 0

    for start, end, word in sorted(spans, key=lambda s: s[0]):
        parts.append(text[prev:start])
        parts.append(_blank_for(word))
        answer_key.append(word)
        prev = end

    parts.append(text[prev:])
    return "".join(parts), answer_key


# ---------------------------------------------------------------------------
# Public generation API
# ---------------------------------------------------------------------------

def generate_random(
    lyrics: str,
    song_title: str = "",
    artist: str = "",
    level: int = 20,
    seed: Optional[int] = None,
) -> GapFillExercise:
    """
    Blank approximately *level* percent of all word positions at random.

    Args:
        lyrics:     Raw lyrics text.
        song_title: Metadata (display only).
        artist:     Metadata (display only).
        level:      Percentage of words to blank (1–100).
        seed:       Optional RNG seed for reproducibility in tests.

    Returns:
        GapFillExercise with randomly blanked words.
    """
    level = max(1, min(100, level))
    all_spans = _tokenize(lyrics)
    total = len(all_spans)
    target = max(1, round(total * level / 100))

    rng = random.Random(seed)
    chosen = sorted(rng.sample(all_spans, min(target, total)), key=lambda s: s[0])

    text_with_gaps, answer_key = _apply_blanks(lyrics, chosen)

    return GapFillExercise(
        song_title=song_title,
        artist=artist,
        text_with_gaps=text_with_gaps,
        answer_key=answer_key,
        total_words=total,
        blanked_count=len(chosen),
        mode="random",
        level=level,
    )


def generate_manual(
    lyrics: str,
    words: list[str],
    song_title: str = "",
    artist: str = "",
) -> GapFillExercise:
    """
    Blank every occurrence of each word in *words* (case-insensitive).

    Args:
        lyrics:     Raw lyrics text.
        words:      Words to blank (all occurrences, case-insensitive).
        song_title: Metadata (display only).
        artist:     Metadata (display only).

    Returns:
        GapFillExercise with all occurrences of the chosen words blanked.
    """
    target_set = {w.lower() for w in words}
    chosen = [span for span in _tokenize(lyrics) if span[2].lower() in target_set]

    text_with_gaps, answer_key = _apply_blanks(lyrics, chosen)
    total = len(_tokenize(lyrics))

    return GapFillExercise(
        song_title=song_title,
        artist=artist,
        text_with_gaps=text_with_gaps,
        answer_key=answer_key,
        total_words=total,
        blanked_count=len(chosen),
        mode="manual",
        selected_words=sorted(target_set),
    )


# ---------------------------------------------------------------------------
# Formatting and export
# ---------------------------------------------------------------------------

def render_text(exercise: GapFillExercise) -> str:
    """Return the full exercise as a printable string with a header."""
    header = f"Song: {exercise.song_title}"
    if exercise.artist:
        header += f" – {exercise.artist}"

    mode_note = (
        f"[Random – {exercise.level}% blanked]"
        if exercise.mode == "random"
        else f"[Manual – words: {', '.join(exercise.selected_words or [])}]"
    )

    return "\n".join([
        header,
        mode_note,
        "",
        exercise.text_with_gaps,
        "",
        f"({exercise.blanked_count} of {exercise.total_words} words blanked)",
    ])


def export(
    exercise: GapFillExercise,
    output_dir: Path,
    filename: Optional[str] = None,
) -> Path:
    """
    Write the exercise to a .txt file in *output_dir*.

    Args:
        exercise:   The generated exercise.
        output_dir: Directory to write the file (created if absent).
        filename:   Override the default ``exercise_YYYYMMDD_HHMM.txt`` name.

    Returns:
        Path to the written file.
    """
    return export_text(render_text(exercise), output_dir, filename)


def export_text(
    text: str,
    output_dir: Path,
    filename: Optional[str] = None,
) -> Path:
    """
    Write arbitrary *text* to a .txt file in *output_dir*.

    Useful when multiple songs have been rendered into a single combined string.

    Args:
        text:       Content to write.
        output_dir: Directory to write the file (created if absent).
        filename:   Override the default ``exercise_YYYYMMDD_HHMM.txt`` name.

    Returns:
        Path to the written file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if not filename:
        filename = f"exercise_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
    path = output_dir / filename
    path.write_text(text, encoding="utf-8")
    return path
