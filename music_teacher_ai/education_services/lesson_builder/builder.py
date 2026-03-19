"""
Lesson builder.

Orchestrates fill-in-blank exercises, vocabulary analysis, and phrasal verb
detection into a single Lesson object that can be serialised for API responses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from music_teacher_ai.education_services.exercises.fill_in_blank import (
    FillInBlankExercise,
    generate as generate_exercise,
)
from music_teacher_ai.education_services.vocabulary.analyzer import (
    VocabularyAnalysis,
    analyze as analyze_vocabulary,
)
from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import (
    PhrasalVerbReport,
    detect as detect_phrasal_verbs,
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    song_id: int
    song_title: str
    artist: str
    lyrics_preview: str             # first 200 chars of lyrics
    exercise: FillInBlankExercise
    vocabulary: VocabularyAnalysis
    phrasal_verbs: PhrasalVerbReport

    def to_dict(self) -> dict:
        """Serialise to a JSON-friendly dict for API responses."""
        return {
            "song_id": self.song_id,
            "song_title": self.song_title,
            "artist": self.artist,
            "lyrics_preview": self.lyrics_preview,
            "exercise": {
                "text_with_blanks": self.exercise.text_with_blanks,
                "answer_key": self.exercise.answer_key,
                "total_words": self.exercise.total_words,
                "blanked_count": self.exercise.blanked_count,
                "blanks": [
                    {"number": b.number, "word": b.word}
                    for b in self.exercise.blanks
                ],
            },
            "vocabulary": {
                "total_unique_words": self.vocabulary.total_unique_words,
                "dominant_level": self.vocabulary.dominant_level,
                "level_counts": self.vocabulary.level_counts,
                "level_percentages": self.vocabulary.level_percentages,
                "words_by_level": {
                    level: [
                        {"word": e.word, "occurrences": e.occurrences}
                        for e in entries
                    ]
                    for level, entries in self.vocabulary.words_by_level.items()
                    if entries
                },
            },
            "phrasal_verbs": {
                "total_matches": self.phrasal_verbs.total_matches,
                "unique_phrasal_verbs": self.phrasal_verbs.unique_phrasal_verbs,
                "matches": [
                    {
                        "phrasal_verb": m.phrasal_verb,
                        "matched_text": m.matched_text,
                        "line_number": m.line_number,
                        "line_text": m.line_text,
                    }
                    for m in self.phrasal_verbs.matches
                ],
            },
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_lesson(
    song_id: int,
    lyrics: str,
    song_title: str = "",
    artist: str = "",
    num_blanks: int = 10,
    min_word_length: int = 4,
) -> Lesson:
    """
    Build a complete lesson for a song.

    Args:
        song_id:         Database ID (passed through for reference).
        lyrics:          Raw lyrics text.
        song_title:      Song title.
        artist:          Artist name.
        num_blanks:      Number of fill-in-blank gaps to create.
        min_word_length: Minimum word length for blanking / vocab analysis.

    Returns:
        Lesson containing exercise, vocabulary analysis, and phrasal verb report.
    """
    exercise = generate_exercise(
        lyrics,
        song_title=song_title,
        artist=artist,
        num_blanks=num_blanks,
        min_word_length=min_word_length,
    )
    vocabulary = analyze_vocabulary(
        lyrics,
        song_title=song_title,
        artist=artist,
        min_word_length=min_word_length,
    )
    phrasal_verbs = detect_phrasal_verbs(
        lyrics,
        song_title=song_title,
        artist=artist,
    )

    preview = lyrics.strip()[:200]
    if len(lyrics.strip()) > 200:
        preview += "…"

    return Lesson(
        song_id=song_id,
        song_title=song_title,
        artist=artist,
        lyrics_preview=preview,
        exercise=exercise,
        vocabulary=vocabulary,
        phrasal_verbs=phrasal_verbs,
    )
