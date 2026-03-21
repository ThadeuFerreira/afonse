"""
Lyrics download pipeline stage.

Fetches lyrics from Genius in parallel using a thread pool that adapts to
rate-limit responses:

  - Starts with `initial_workers` concurrent requests (default 5).
  - Songs are processed in chunks of `workers × 20`.
  - On any 429 / rate-limit response in a chunk, the stage:
      1. Puts the affected songs back at the front of the queue.
      2. Waits 60 seconds.
      3. Halves the worker count.
  - When workers reach 1 and a 429 still occurs, the stage records a hard
    rate limit, stops fetching, and proceeds — partially downloaded lyrics
    are better than none.
  - A JSON report is written to REPORTS_DIR on completion.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from sqlmodel import select

from music_teacher_ai.core.lyrics_client import (
    GeniusBlockedByCloudflareError,
    GeniusTokenMissingError,
    fetch_lyrics,
)
from music_teacher_ai.database.models import Artist, IngestionFailure, Lyrics, Song
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.pipeline.reporter import PipelineReport

console = Console()

_RATE_LIMIT_WAIT = 60  # seconds to wait after a 429


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "too many" in msg or "rate limit" in msg


def _count_words(text: str) -> tuple[int, int]:
    words = re.findall(r"\b[a-z']+\b", text.lower())
    return len(words), len(set(words))


def _fetch_one(title: str, artist: str) -> tuple[str, Optional[str]]:
    """
    Fetch lyrics for one song.  Returns (status, payload):
      ("ok", lyrics_text)
      ("not_found", None)
      ("rate_limit", error_message)
      ("error", error_message)
    """
    try:
        text = fetch_lyrics(title, artist)
        if not text:
            return ("not_found", None)
        return ("ok", text)
    except GeniusTokenMissingError:
        raise  # propagate — caught by the caller to abort the whole run
    except GeniusBlockedByCloudflareError as exc:
        return ("blocked", str(exc))
    except Exception as exc:
        if _is_rate_limit(exc):
            return ("rate_limit", str(exc))
        return ("error", str(exc))


def download_lyrics(initial_workers: int = 5) -> None:
    """Download lyrics for songs that don't have a Lyrics row yet."""
    import os

    from music_teacher_ai.core.lyrics_client import _get_token
    from music_teacher_ai.pipeline.validation import validate_lyrics

    # Allow overriding worker count via env — use 1–2 on VPS to avoid Cloudflare
    env_workers = os.getenv("GENIUS_WORKERS")
    if env_workers:
        initial_workers = max(1, int(env_workers))

    if not _get_token():
        console.print(
            "[bold red]GENIUS_ACCESS_TOKEN is not configured — cannot download lyrics.[/bold red]\n"
            "Run [cyan]music-teacher config[/cyan] to set your Genius API token, then retry."
        )
        return

    report = PipelineReport("lyrics")

    with get_session() as session:
        songs_with_lyrics = select(Lyrics.song_id)
        songs = session.exec(
            select(Song).where(~Song.id.in_(songs_with_lyrics))
        ).all()

        artist_map: dict[int, str] = {}
        for song in songs:
            artist = session.get(Artist, song.artist_id)
            artist_map[song.id] = artist.name if artist else ""

    pending_songs = songs
    debug_not_found_samples: list[dict[str, str]] = []
    total = len(pending_songs)
    console.print(
        f"[cyan]Downloading lyrics for {total} songs "
        f"(initial workers: {initial_workers})[/cyan]"
    )
    report.set("total", total)

    if not total:
        report.save()
        return

    workers = initial_workers
    remaining: list[Song] = list(pending_songs)
    hard_limited = False
    downloaded = failed = not_found = rate_limit_events = blocked = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TextColumn(
            "[green]✓{task.fields[downloaded]}[/green] "
            "[red]✗{task.fields[failed]}[/red] "
            "[dim]workers={task.fields[workers]}[/dim]"
        ),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(
            "Downloading lyrics",
            total=total,
            downloaded=0,
            failed=0,
            workers=workers,
        )

        while remaining and not hard_limited:
            chunk_size = workers * 20
            chunk = remaining[:chunk_size]

            futures = {}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for song in chunk:
                    futures[pool.submit(_fetch_one, song.title, artist_map[song.id])] = song

                rate_limited: list[Song] = []
                ok_batch: list[tuple[Song, str]] = []
                fail_batch: list[tuple[Song, str]] = []

                for future in as_completed(futures):
                    song = futures[future]
                    try:
                        status, data = future.result()
                    except GeniusTokenMissingError as exc:
                        progress.stop()
                        console.print(f"[bold red]{exc}[/bold red]")
                        report.save()
                        return

                    if status == "ok":
                        ok_batch.append((song, data))
                    elif status == "rate_limit":
                        rate_limited.append(song)
                        report.add_event(
                            "rate_limit",
                            song_id=song.id,
                            title=song.title,
                            error=data,
                        )
                    elif status == "not_found":
                        fail_batch.append((song, "Lyrics not found on Genius"))
                        if len(debug_not_found_samples) < 25:
                            debug_not_found_samples.append({
                                "song_id": str(song.id),
                                "title": song.title,
                                "artist": artist_map[song.id],
                            })
                        report.add_error(
                            song_id=song.id,
                            title=song.title,
                            artist=artist_map[song.id],
                            error="not_found",
                        )
                        not_found += 1
                    elif status == "blocked":
                        fail_batch.append((song, "blocked_by_cloudflare"))
                        report.add_error(
                            song_id=song.id,
                            title=song.title,
                            artist=artist_map[song.id],
                            error="blocked_by_cloudflare",
                        )
                        blocked += 1
                    else:
                        fail_batch.append((song, data))
                        report.add_error(
                            song_id=song.id,
                            title=song.title,
                            artist=artist_map[song.id],
                            error=data,
                        )

            # --- Batch DB writes (outside the thread pool) ---
            if ok_batch:
                with get_session() as session:
                    for song, text in ok_batch:
                        vr = validate_lyrics(text)
                        if not vr.ok:
                            # Hard failure — reject entirely
                            fail_batch.append((song, f"Lyrics validation failed: {vr}"))
                            report.add_error(
                                song_id=song.id,
                                title=song.title,
                                artist=artist_map[song.id],
                                error=str(vr),
                            )
                            continue
                        wc, uw = _count_words(text)
                        if vr.warnings:
                            # Soft warning — store but log
                            report.add_event(
                                "lyrics_warning",
                                song_id=song.id,
                                title=song.title,
                                warnings="; ".join(vr.warnings),
                            )
                        session.add(Lyrics(
                            song_id=song.id,
                            lyrics_text=text,
                            word_count=wc,
                            unique_words=uw,
                        ))
                    session.commit()
                downloaded += sum(
                    1 for song, _ in ok_batch
                    if not any(song.id == fs.id for fs, _ in fail_batch)
                )

            if fail_batch:
                with get_session() as session:
                    for song, error_msg in fail_batch:
                        session.add(IngestionFailure(
                            song_id=song.id,
                            stage="lyrics",
                            error_message=error_msg,
                        ))
                    session.commit()
                failed += len(fail_batch)

            progress.update(
                task,
                advance=len(ok_batch) + len(fail_batch),
                downloaded=downloaded,
                failed=failed,
                workers=workers,
            )

            # --- Adaptive rate-limit response ---
            if rate_limited:
                rate_limit_events += 1
                remaining = rate_limited + remaining[chunk_size:]

                if workers <= 1:
                    hard_limited = True
                    report.add_event("hard_rate_limit", songs_skipped=len(remaining))
                    console.log(
                        f"[bold red]Hard rate limit reached — stopping lyrics download. "
                        f"{len(remaining)} songs skipped.[/bold red]"
                    )
                else:
                    workers = max(1, workers // 2)
                    report.add_event(
                        "backoff",
                        new_workers=workers,
                        wait_seconds=_RATE_LIMIT_WAIT,
                        songs_retrying=len(rate_limited),
                    )
                    console.log(
                        f"[yellow]Rate limited (429). Waiting {_RATE_LIMIT_WAIT}s, "
                        f"workers → {workers}, retrying {len(rate_limited)} songs.[/yellow]"
                    )
                    time.sleep(_RATE_LIMIT_WAIT)
                    progress.update(task, workers=workers)
            else:
                remaining = remaining[chunk_size:]

    report.set("downloaded", downloaded)
    report.set("failed", failed)
    report.set("not_found", not_found)
    report.set("blocked_by_cloudflare", blocked)
    report.set("rate_limit_events", rate_limit_events)
    report.set("hard_limited", int(hard_limited))
    report.set("final_workers", workers)
    if debug_not_found_samples:
        report.add_event(
            "not_found_samples",
            kind="debug",
            count=len(debug_not_found_samples),
            samples=debug_not_found_samples,
        )

    # Root-cause diagnosis — written to the report so the user can understand
    # a bulk failure without having to read through individual error entries.
    if total > 0:
        not_found_rate = not_found / total
        error_rate = (failed - not_found) / total if failed > not_found else 0

        if downloaded == 0 and blocked > 0:
            report.add_event(
                (
                    f"{blocked}/{total} songs were blocked by Cloudflare bot checks. "
                    "This VPS IP is likely challenged by Genius."
                ),
                kind="diagnosis",
                cause="cloudflare_challenge",
            )
        elif downloaded == 0 and not_found == total:
            from music_teacher_ai.core.lyrics_client import _get_token
            token_present = bool(_get_token())
            if token_present:
                report.add_event(
                    (
                        "100% of songs returned 'not found'. "
                        "Possible causes: (1) API cache poisoned from a previous run "
                        "without a valid token — run: music-teacher doctor --clear-cache null; "
                        "(2) Genius token is set but invalid — verify at genius.com/api-clients; "
                        "(3) All songs genuinely absent from Genius (unlikely at this scale)."
                    ),
                    kind="diagnosis",
                    cause="all_not_found",
                )
            else:
                report.add_event(
                    "GENIUS_ACCESS_TOKEN is not set. No API calls were made.",
                    kind="diagnosis",
                    cause="missing_token",
                )
        elif not_found_rate > 0.5:
            report.add_event(
                f"{not_found_rate:.0%} of songs not found on Genius. "
                "Check that artist names match Genius spelling, or that the Genius token is valid.",
                kind="diagnosis",
                cause="high_not_found_rate",
            )
        elif error_rate > 0.3:
            report.add_event(
                f"{error_rate:.0%} of songs failed with API errors. "
                "Check the errors list in this report for details.",
                kind="diagnosis",
                cause="high_error_rate",
            )

    report_path = report.save()

    console.print(
        f"[green]Lyrics download complete.[/green] "
        f"downloaded={downloaded} failed={failed} not_found={not_found} "
        f"blocked={blocked} rate_limit_events={rate_limit_events} hard_limited={hard_limited}"
    )
    console.print(f"[dim]Report: {report_path}[/dim]")
