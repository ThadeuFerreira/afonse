import re

from rich.console import Console
from sqlmodel import delete, select

from music_teacher_ai.database.models import Lyrics, VocabularyIndex
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.reporter import PipelineReport

console = Console()

_STOPWORDS = {
    "i",
    "me",
    "my",
    "myself",
    "we",
    "our",
    "you",
    "your",
    "he",
    "she",
    "it",
    "they",
    "them",
    "what",
    "which",
    "who",
    "this",
    "that",
    "these",
    "those",
    "am",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "shall",
    "can",
    "need",
    "dare",
    "ought",
    "used",
    "to",
    "of",
    "in",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "as",
    "into",
    "through",
    "during",
    "before",
    "after",
    "above",
    "below",
    "between",
    "out",
    "off",
    "over",
    "under",
    "again",
    "then",
    "so",
    "if",
    "or",
    "and",
    "but",
    "not",
    "no",
    "nor",
    "the",
    "a",
    "an",
    "up",
    "down",
    "just",
    "more",
    "also",
}


def _extract_words(text: str) -> set[str]:
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def build_vocabulary_index(rebuild: bool = False) -> None:
    report = PipelineReport("vocabulary")
    with get_session() as session:
        if rebuild:
            session.exec(delete(VocabularyIndex))
            session.commit()
            indexed_ids: set[int] = set()
        else:
            indexed_ids = {
                row if isinstance(row, int) else row[0]
                for row in session.exec(select(VocabularyIndex.song_id).distinct()).all()
            }

        lyrics_rows = session.exec(select(Lyrics)).all()
        pending = [row for row in lyrics_rows if row.song_id not in indexed_ids]

    total = len(pending)
    report.set("total", total)
    console.print(f"[cyan]Indexing vocabulary for {total} songs[/cyan]")
    indexed = 0
    total_words = 0

    for lyr in pending:
        words = _extract_words(lyr.lyrics_text)
        with get_session() as session:
            for word in words:
                session.add(VocabularyIndex(word=word, song_id=lyr.song_id))
            session.commit()
        indexed += 1
        total_words += len(words)
        if indexed % 100 == 0:
            console.print(f"  indexed={indexed}")

    report.set("indexed", indexed)
    report.set("total_word_entries", total_words)
    report_path = report.save()

    console.print(
        f"[green]Vocabulary index complete.[/green] indexed={indexed} songs, {total_words} word entries"
    )
    console.print(f"[dim]Report: {report_path}[/dim]")
