"""
Phrasal verb detector.

Scans lyrics for known English phrasal verbs using a curated list.
Each detected instance records the full matched phrase, the base verb,
and the line(s) it appears on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Curated phrasal verb list  (verb + particle(s))
# ---------------------------------------------------------------------------

_PHRASAL_VERBS: list[str] = [
    # break
    "break down",
    "break in",
    "break into",
    "break off",
    "break out",
    "break through",
    "break up",
    # bring
    "bring about",
    "bring along",
    "bring back",
    "bring down",
    "bring in",
    "bring out",
    "bring up",
    # call
    "call back",
    "call for",
    "call off",
    "call on",
    "call out",
    "call up",
    # carry
    "carry on",
    "carry out",
    "carry over",
    # come
    "come about",
    "come across",
    "come along",
    "come apart",
    "come back",
    "come down",
    "come forward",
    "come in",
    "come off",
    "come on",
    "come out",
    "come over",
    "come through",
    "come up",
    # cut
    "cut back",
    "cut down",
    "cut in",
    "cut off",
    "cut out",
    # fall
    "fall apart",
    "fall back",
    "fall behind",
    "fall down",
    "fall for",
    "fall in",
    "fall off",
    "fall out",
    "fall over",
    "fall through",
    # get
    "get across",
    "get along",
    "get around",
    "get away",
    "get back",
    "get by",
    "get down",
    "get in",
    "get into",
    "get off",
    "get on",
    "get out",
    "get over",
    "get through",
    "get together",
    "get up",
    # give
    "give away",
    "give back",
    "give in",
    "give out",
    "give up",
    # go
    "go about",
    "go along",
    "go away",
    "go back",
    "go by",
    "go down",
    "go for",
    "go in",
    "go off",
    "go on",
    "go out",
    "go over",
    "go through",
    "go up",
    # grow
    "grow apart",
    "grow into",
    "grow out",
    "grow up",
    # hold
    "hold back",
    "hold down",
    "hold off",
    "hold on",
    "hold out",
    "hold up",
    # keep
    "keep away",
    "keep back",
    "keep down",
    "keep off",
    "keep on",
    "keep out",
    "keep up",
    # let
    "let down",
    "let go",
    "let in",
    "let off",
    "let out",
    "let up",
    # look
    "look after",
    "look ahead",
    "look back",
    "look down",
    "look for",
    "look forward",
    "look in",
    "look into",
    "look out",
    "look over",
    "look through",
    "look up",
    # make
    "make for",
    "make out",
    "make over",
    "make up",
    # pick
    "pick out",
    "pick up",
    # pull
    "pull apart",
    "pull away",
    "pull back",
    "pull down",
    "pull in",
    "pull off",
    "pull out",
    "pull through",
    "pull up",
    # put
    "put aside",
    "put away",
    "put back",
    "put down",
    "put in",
    "put off",
    "put on",
    "put out",
    "put through",
    "put together",
    "put up",
    # run
    "run across",
    "run after",
    "run away",
    "run down",
    "run in",
    "run into",
    "run off",
    "run out",
    "run over",
    "run through",
    "run up",
    # set
    "set aside",
    "set back",
    "set in",
    "set off",
    "set out",
    "set up",
    # show
    "show off",
    "show up",
    # stand
    "stand back",
    "stand by",
    "stand down",
    "stand for",
    "stand out",
    "stand up",
    # take
    "take after",
    "take apart",
    "take away",
    "take back",
    "take down",
    "take in",
    "take off",
    "take on",
    "take out",
    "take over",
    "take part",
    "take place",
    "take up",
    # think
    "think about",
    "think ahead",
    "think back",
    "think over",
    "think through",
    # throw
    "throw away",
    "throw back",
    "throw in",
    "throw off",
    "throw out",
    "throw up",
    # turn
    "turn around",
    "turn back",
    "turn down",
    "turn in",
    "turn off",
    "turn on",
    "turn out",
    "turn over",
    "turn up",
    # wake / work / wear
    "wake up",
    "work out",
    "work through",
    "wear out",
    "wear down",
]

# Pre-compile patterns: each pattern is case-insensitive, word-boundary aware.
# Built once at module load.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (pv, re.compile(r"\b" + re.escape(pv) + r"\b", re.IGNORECASE)) for pv in _PHRASAL_VERBS
]


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PhrasalVerbMatch:
    phrasal_verb: str  # canonical form e.g. "give up"
    base_verb: str  # first word e.g. "give"
    matched_text: str  # exact text from lyrics e.g. "giving up"
    line_number: int  # 1-based
    line_text: str  # the full line


@dataclass
class PhrasalVerbReport:
    song_title: str
    artist: str
    matches: list[PhrasalVerbMatch]
    unique_phrasal_verbs: list[str]  # deduplicated canonical forms
    total_matches: int


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect(
    lyrics: str,
    song_title: str = "",
    artist: str = "",
) -> PhrasalVerbReport:
    """
    Detect phrasal verbs in song lyrics.

    Args:
        lyrics:     Raw lyrics text.
        song_title: Song title (metadata only).
        artist:     Artist name (metadata only).

    Returns:
        PhrasalVerbReport with all matches and a deduplicated summary.
    """
    lines = lyrics.strip().splitlines()
    matches: list[PhrasalVerbMatch] = []

    for line_no, line in enumerate(lines, start=1):
        for pv, pattern in _PATTERNS:
            for m in pattern.finditer(line):
                matches.append(
                    PhrasalVerbMatch(
                        phrasal_verb=pv,
                        base_verb=pv.split()[0],
                        matched_text=m.group(0),
                        line_number=line_no,
                        line_text=line.strip(),
                    )
                )

    unique = sorted({m.phrasal_verb for m in matches})

    return PhrasalVerbReport(
        song_title=song_title,
        artist=artist,
        matches=matches,
        unique_phrasal_verbs=unique,
        total_matches=len(matches),
    )
