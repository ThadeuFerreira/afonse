"""
Vocabulary difficulty analyzer.

Classifies words from song lyrics into CEFR levels (A1–C2) using an
embedded frequency-based word list.  Words not found in the list are
treated as C2 (advanced / rare).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# CEFR level type
# ---------------------------------------------------------------------------

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]

# ---------------------------------------------------------------------------
# Embedded word list  (frequency-derived, manually curated)
# Each entry: word → CEFR level
# This is a representative subset — production systems should use a full list
# ---------------------------------------------------------------------------

_WORD_LEVELS: dict[str, CefrLevel] = {
    # A1 ─ most basic everyday words
    "hello": "A1", "goodbye": "A1", "yes": "A1", "no": "A1",
    "house": "A1", "home": "A1", "family": "A1", "friend": "A1",
    "love": "A1", "happy": "A1", "sad": "A1", "big": "A1",
    "small": "A1", "good": "A1", "bad": "A1", "new": "A1",
    "old": "A1", "open": "A1", "close": "A1", "come": "A1",
    "go": "A1", "walk": "A1", "run": "A1", "eat": "A1",
    "drink": "A1", "sleep": "A1", "work": "A1", "play": "A1",
    "look": "A1", "see": "A1", "hear": "A1", "know": "A1",
    "think": "A1", "want": "A1", "need": "A1", "make": "A1",
    "take": "A1", "give": "A1", "tell": "A1", "ask": "A1",
    "help": "A1", "like": "A1", "talk": "A1", "live": "A1",
    "life": "A1", "time": "A1", "day": "A1", "night": "A1",
    "morning": "A1", "water": "A1", "food": "A1", "money": "A1",
    "school": "A1", "book": "A1", "door": "A1", "road": "A1",
    "city": "A1", "country": "A1", "world": "A1", "name": "A1",
    "people": "A1", "man": "A1", "woman": "A1", "girl": "A1",
    "boy": "A1", "child": "A1", "baby": "A1", "hand": "A1",
    "face": "A1", "eye": "A1", "heart": "A1", "head": "A1",
    "year": "A1", "place": "A1", "thing": "A1", "number": "A1",
    "sky": "A1", "sun": "A1", "rain": "A1", "light": "A1",
    "dark": "A1", "cold": "A1", "hot": "A1", "fire": "A1",
    # A2 ─ elementary
    "dream": "A2", "break": "A2", "begin": "A2", "change": "A2",
    "carry": "A2", "bring": "A2", "stand": "A2", "find": "A2",
    "leave": "A2", "keep": "A2", "start": "A2", "try": "A2",
    "turn": "A2", "feel": "A2", "follow": "A2", "move": "A2",
    "show": "A2", "stop": "A2", "build": "A2", "create": "A2",
    "drive": "A2", "fall": "A2", "grow": "A2", "hold": "A2",
    "learn": "A2", "meet": "A2", "spend": "A2", "wait": "A2",
    "catch": "A2", "watch": "A2", "write": "A2", "read": "A2",
    "teach": "A2", "send": "A2", "pay": "A2", "sell": "A2",
    "buy": "A2", "lose": "A2", "win": "A2", "save": "A2",
    "remember": "A2", "forget": "A2", "understand": "A2",
    "believe": "A2", "wonder": "A2", "happen": "A2",
    "story": "A2", "picture": "A2", "music": "A2", "dance": "A2",
    "song": "A2", "voice": "A2", "smile": "A2", "laugh": "A2",
    "cry": "A2", "fight": "A2", "kiss": "A2", "touch": "A2",
    "word": "A2", "answer": "A2", "question": "A2", "problem": "A2",
    "beautiful": "A2", "wonderful": "A2", "strong": "A2", "free": "A2",
    "ready": "A2", "alone": "A2", "together": "A2", "forever": "A2",
    # B1 ─ intermediate
    "achieve": "B1", "affect": "B1", "allow": "B1", "appear": "B1",
    "attract": "B1", "avoid": "B1", "cause": "B1", "challenge": "B1",
    "choose": "B1", "complete": "B1", "consider": "B1", "contain": "B1",
    "continue": "B1", "control": "B1", "cover": "B1", "decide": "B1",
    "describe": "B1", "design": "B1", "develop": "B1", "discover": "B1",
    "discuss": "B1", "doubt": "B1", "enjoy": "B1", "enter": "B1",
    "escape": "B1", "exist": "B1", "expect": "B1", "experience": "B1",
    "explain": "B1", "express": "B1", "focus": "B1", "force": "B1",
    "include": "B1", "increase": "B1", "indicate": "B1", "influence": "B1",
    "introduce": "B1", "involve": "B1", "join": "B1", "mention": "B1",
    "notice": "B1", "offer": "B1", "prepare": "B1", "produce": "B1",
    "protect": "B1", "provide": "B1", "reach": "B1", "realize": "B1",
    "receive": "B1", "recognize": "B1", "reduce": "B1", "refer": "B1",
    "remain": "B1", "replace": "B1", "require": "B1", "respect": "B1",
    "result": "B1", "search": "B1", "suggest": "B1", "support": "B1",
    "survive": "B1", "threat": "B1", "trust": "B1", "value": "B1",
    "vision": "B1", "anger": "B1", "anxiety": "B1", "beauty": "B1",
    "comfort": "B1", "courage": "B1", "desire": "B1", "emotion": "B1",
    "energy": "B1", "faith": "B1", "freedom": "B1", "glory": "B1",
    "grace": "B1", "grief": "B1", "guilt": "B1", "habit": "B1",
    "honor": "B1", "hope": "B1", "imagination": "B1", "memory": "B1",
    "passion": "B1", "patience": "B1", "peace": "B1", "power": "B1",
    "pride": "B1", "purpose": "B1", "silence": "B1", "spirit": "B1",
    "strength": "B1", "wisdom": "B1",
    # B2 ─ upper-intermediate
    "abandon": "B2", "absorb": "B2", "acknowledge": "B2", "adapt": "B2",
    "adequate": "B2", "advocate": "B2", "ambition": "B2", "analyze": "B2",
    "anticipate": "B2", "appreciate": "B2", "approach": "B2", "arise": "B2",
    "assert": "B2", "assess": "B2", "assign": "B2", "assume": "B2",
    "attach": "B2", "attribute": "B2", "capture": "B2", "clarify": "B2",
    "collaborate": "B2", "commit": "B2", "communicate": "B2", "complex": "B2",
    "concentrate": "B2", "conclude": "B2", "confirm": "B2", "conflict": "B2",
    "consequence": "B2", "contribute": "B2", "convince": "B2", "cooperate": "B2",
    "dedicate": "B2", "define": "B2", "demonstrate": "B2", "determine": "B2",
    "diminish": "B2", "diverse": "B2", "emphasize": "B2", "encounter": "B2",
    "enhance": "B2", "establish": "B2", "evaluate": "B2", "evolve": "B2",
    "examine": "B2", "expose": "B2", "generate": "B2", "identify": "B2",
    "illustrate": "B2", "implement": "B2", "imply": "B2", "impose": "B2",
    "intend": "B2", "interpret": "B2", "investigate": "B2", "justify": "B2",
    "maintain": "B2", "manage": "B2", "modify": "B2", "monitor": "B2",
    "motivate": "B2", "negotiate": "B2", "obtain": "B2", "overcome": "B2",
    "participate": "B2", "perceive": "B2", "perform": "B2", "persist": "B2",
    "portray": "B2", "possess": "B2", "predict": "B2", "prevent": "B2",
    "promote": "B2", "propose": "B2", "pursue": "B2", "reflect": "B2",
    "reject": "B2", "rely": "B2", "resolve": "B2", "reveal": "B2",
    "seek": "B2", "select": "B2", "separate": "B2", "significant": "B2",
    "stimulate": "B2", "submit": "B2", "sustain": "B2", "transform": "B2",
    # C1 ─ advanced
    "abstract": "C1", "accumulate": "C1", "acquaint": "C1", "acute": "C1",
    "aggregate": "C1", "alleviate": "C1", "allocate": "C1", "ambiguous": "C1",
    "amplify": "C1", "articulate": "C1", "aspire": "C1", "augment": "C1",
    "coherent": "C1", "competent": "C1", "comprehend": "C1", "comprise": "C1",
    "concise": "C1", "conducive": "C1", "confront": "C1", "contemplate": "C1",
    "contradiction": "C1", "controversy": "C1", "convey": "C1", "critique": "C1",
    "culminate": "C1", "deduce": "C1", "deliberate": "C1", "depict": "C1",
    "derive": "C1", "detrimental": "C1", "discern": "C1", "disregard": "C1",
    "distinguish": "C1", "dominate": "C1", "elaborate": "C1", "elicit": "C1",
    "eloquent": "C1", "embody": "C1", "emerge": "C1", "encompass": "C1",
    "endure": "C1", "explicit": "C1", "facilitate": "C1", "formulate": "C1",
    "fundamental": "C1", "hypothesize": "C1", "implication": "C1",
    "inevitable": "C1", "inherent": "C1", "integrate": "C1", "intricate": "C1",
    "manifest": "C1", "nuance": "C1", "objective": "C1", "obsolete": "C1",
    "paradigm": "C1", "phenomenon": "C1", "pragmatic": "C1",
    "prominent": "C1", "reconcile": "C1", "reinforce": "C1", "scrutinize": "C1",
    "simultaneous": "C1", "speculate": "C1", "subsequent": "C1", "supplement": "C1",
    "synthesize": "C1", "theorem": "C1", "underlying": "C1", "universal": "C1",
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class WordEntry:
    word: str           # lowercase normalised form
    level: CefrLevel
    occurrences: int
    lines: list[int]    # 1-based line numbers where word appears


@dataclass
class VocabularyAnalysis:
    song_title: str
    artist: str
    total_unique_words: int
    level_counts: dict[str, int]    # e.g. {"A1": 12, "A2": 8, ...}
    level_percentages: dict[str, float]
    dominant_level: CefrLevel
    words_by_level: dict[str, list[WordEntry]]
    all_words: list[WordEntry]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    lyrics: str,
    song_title: str = "",
    artist: str = "",
    min_word_length: int = 3,
) -> VocabularyAnalysis:
    """
    Analyse vocabulary difficulty in song lyrics.

    Args:
        lyrics:          Raw lyrics text.
        song_title:      Song title (metadata only).
        artist:          Artist name (metadata only).
        min_word_length: Words shorter than this are ignored.

    Returns:
        VocabularyAnalysis with per-level counts and word details.
    """
    lines = lyrics.strip().splitlines()

    # word → {level, occurrences, lines}
    word_data: dict[str, dict] = {}

    for line_no, line in enumerate(lines, start=1):
        for raw in re.findall(r"\b[a-zA-Z]+\b", line):
            word = raw.lower()
            if len(word) < min_word_length:
                continue
            if word not in word_data:
                level: CefrLevel = _WORD_LEVELS.get(word, "C2")
                word_data[word] = {"level": level, "occurrences": 0, "lines": []}
            word_data[word]["occurrences"] += 1
            word_data[word]["lines"].append(line_no)

    # Build WordEntry list
    all_words = [
        WordEntry(
            word=w,
            level=d["level"],
            occurrences=d["occurrences"],
            lines=d["lines"],
        )
        for w, d in word_data.items()
    ]
    all_words.sort(key=lambda e: e.word)

    # Aggregate counts
    levels: list[CefrLevel] = ["A1", "A2", "B1", "B2", "C1", "C2"]
    level_counts: dict[str, int] = {lv: 0 for lv in levels}
    words_by_level: dict[str, list[WordEntry]] = {lv: [] for lv in levels}

    for entry in all_words:
        level_counts[entry.level] += 1
        words_by_level[entry.level].append(entry)

    total = len(all_words) or 1
    level_percentages = {lv: round(level_counts[lv] / total * 100, 1) for lv in levels}

    dominant_level: CefrLevel = max(level_counts, key=lambda lv: level_counts[lv])  # type: ignore[assignment]

    return VocabularyAnalysis(
        song_title=song_title,
        artist=artist,
        total_unique_words=len(all_words),
        level_counts=level_counts,
        level_percentages=level_percentages,
        dominant_level=dominant_level,
        words_by_level=words_by_level,
        all_words=all_words,
    )
