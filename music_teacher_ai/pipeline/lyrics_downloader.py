import re

from rich.console import Console
from sqlmodel import select

from music_teacher_ai.core.lyrics_client import fetch_lyrics
from music_teacher_ai.database.models import Artist, Song, Lyrics, IngestionFailure
from music_teacher_ai.database.sqlite import get_session

console = Console()


def _count_words(text: str) -> tuple[int, int]:
    words = re.findall(r"\b[a-z']+\b", text.lower())
    return len(words), len(set(words))


def download_lyrics(batch_size: int = 50) -> None:
    """Download lyrics for songs that don't have them yet."""
    with get_session() as session:
        songs_with_lyrics_ids = {
            row[0] for row in session.exec(select(Lyrics.song_id)).all()
        }
        songs = session.exec(select(Song)).all()
        pending = [s for s in songs if s.id not in songs_with_lyrics_ids]

    console.print(f"[cyan]Downloading lyrics for {len(pending)} songs[/cyan]")
    downloaded = 0
    failed = 0

    for song in pending:
        with get_session() as session:
            artist = session.get(Artist, song.artist_id)
            if not artist:
                continue
            try:
                text = fetch_lyrics(song.title, artist.name)
                if not text:
                    raise ValueError("Lyrics not found")

                word_count, unique_words = _count_words(text)
                session.add(
                    Lyrics(
                        song_id=song.id,
                        lyrics_text=text,
                        word_count=word_count,
                        unique_words=unique_words,
                    )
                )
                session.commit()
                downloaded += 1
            except Exception as exc:
                session.add(
                    IngestionFailure(
                        song_id=song.id,
                        stage="lyrics",
                        error_message=str(exc),
                    )
                )
                session.commit()
                failed += 1

        if (downloaded + failed) % batch_size == 0:
            console.print(f"  downloaded={downloaded} failed={failed}")

    console.print(f"[green]Lyrics download complete.[/green] downloaded={downloaded} failed={failed}")
