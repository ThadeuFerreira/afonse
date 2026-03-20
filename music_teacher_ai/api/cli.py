from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import func, select

from music_teacher_ai.application.enrichment_service import EnrichRequest, run_enrichment
from music_teacher_ai.application.errors import ValidationError
from music_teacher_ai.application.playlist_service import (
    create_playlist as svc_create_playlist,
)
from music_teacher_ai.application.playlist_service import (
    delete_playlist as svc_delete_playlist,
)
from music_teacher_ai.application.playlist_service import (
    export_playlist as svc_export_playlist,
)
from music_teacher_ai.application.playlist_service import (
    get_playlist as svc_get_playlist,
)
from music_teacher_ai.application.playlist_service import (
    list_playlists as svc_list_playlists,
)
from music_teacher_ai.application.playlist_service import (
    refresh_playlist as svc_refresh_playlist,
)
from music_teacher_ai.application.search_service import SearchRequest, keyword_search_with_expansion
from music_teacher_ai.application.search_service import semantic_query as svc_semantic_query
from music_teacher_ai.database.models import Chart, Embedding, Lyrics, Song
from music_teacher_ai.database.sqlite import create_db, get_session

app = typer.Typer(help="Music Teacher AI – manage and query the local knowledge base.")
playlist_app = typer.Typer(help="Create and manage song playlists.")
exercise_app = typer.Typer(help="Generate listening and fill-in-the-blank exercises.")
app.add_typer(playlist_app, name="playlist")
app.add_typer(exercise_app, name="exercise")
console = Console()


@app.command()
def migrate_db():
    """Run explicit database migrations and integrity index creation."""
    from music_teacher_ai.database.sqlite import migrate_db as run_migrations

    run_migrations()
    console.print("[green]Database migration complete.[/green]")


@app.command()
def init():
    """Initialize the knowledge base from the built-in song seed."""
    from music_teacher_ai.ingestion.seed_ingestion import seed_songs
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index

    console.print("[bold green]Creating database schema...[/bold green]")
    create_db()

    console.print("[bold green]Step 1/4 – Seeding songs...[/bold green]")
    result = seed_songs()
    console.print(
        f"  inserted={result['inserted']} "
        f"upgraded={result['upgraded']} "
        f"skipped={result['skipped']}"
    )

    console.print("[bold green]Step 2/4 – Downloading lyrics...[/bold green]")
    download_lyrics()

    console.print("[bold green]Step 3/4 – Building vocabulary index...[/bold green]")
    build_vocabulary_index()

    console.print("[bold green]Step 4/4 – Generating embeddings...[/bold green]")
    generate_embeddings()

    console.print("[bold green]Initialization complete.[/bold green]")


@app.command()
def status():
    """Show database statistics."""
    with get_session() as session:
        songs = session.exec(select(func.count()).select_from(Song)).one()
        lyrics = session.exec(select(func.count()).select_from(Lyrics)).one()
        embeddings = session.exec(select(func.count()).select_from(Embedding)).one()
        years = session.exec(
            select(func.count(func.distinct(Chart.date)))
        ).one()

    from music_teacher_ai.config.settings import DATABASE_PATH

    db_size_bytes = Path(DATABASE_PATH).stat().st_size if Path(DATABASE_PATH).exists() else 0

    table = Table(title="Music Teacher AI – Database Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Songs", str(songs))
    table.add_row("Lyrics", str(lyrics))
    table.add_row("Embeddings", str(embeddings))
    table.add_row("Chart entries", str(years))
    table.add_row("Database size", str(db_size_bytes))
    console.print(table)


@app.command()
def update(
    artist: str = typer.Argument(..., help="Artist name to add to the knowledge base."),
    genre: Optional[str] = typer.Option(None, "--genre", help="Genre to search for."),
    year: Optional[int] = typer.Option(None, "--year", help="Year to search for."),
    word: Optional[str] = typer.Option(None, "--word", help="Word to search for."),
    limit: int = typer.Option(10, "--limit", help="Maximum number of songs to process."),
):
    """Add an artist's songs and download their lyrics."""
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings
    from music_teacher_ai.pipeline.expansion import run_expansion_sync
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index

    console.print(f"[cyan]Discovering songs for artist: {artist!r}[/cyan]")
    result = run_expansion_sync(artist=artist, genre=genre, year=year, word=word)
    console.print(
        f"[green]Discovery complete:[/green] "
        f"inserted={result['processed']} rejected={result['rejected']}"
    )

    download_lyrics()
    build_vocabulary_index()
    generate_embeddings()
    console.print("[green]Update complete.[/green]")


@app.command()
def enrich(
    genre: Optional[str] = typer.Option(None, "--genre", help="Last.fm genre tag to search, e.g. 'jazz'."),
    artist: Optional[str] = typer.Option(None, "--artist", help="Artist name to fetch top tracks for."),
    year: Optional[int] = typer.Option(None, "--year", help="Release year to search."),
    limit: int = typer.Option(100, "--limit", help="Maximum new songs to insert (max 1000)."),
    max_pages: int = typer.Option(20, "--max-pages", hidden=True, help="Maximum API pages to fetch."),
    no_pipeline: bool = typer.Option(False, "--no-pipeline", help="Insert songs only; skip metadata/lyrics/embedding stages."),
):
    """
    Expand the knowledge base with songs from external APIs.

    At least one of --genre, --artist, or --year must be provided.

    Examples:

      music-teacher enrich --genre rock

      music-teacher enrich --artist "Adele"

      music-teacher enrich --year 1995

      music-teacher enrich --genre jazz --limit 200
    """
    try:
        result = run_enrichment(
            EnrichRequest(
                genre=genre,
                artist=artist,
                year=year,
                limit=limit,
                max_pages=max_pages,
                run_pipeline=not no_pipeline,
            )
        )
    except ValidationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if result["new_songs_inserted"] == 0:
        console.print("[yellow]No new songs were added.[/yellow]")


@app.command("retry-failed")
def retry_failed():
    """Retry previously failed ingestion steps."""
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.metadata_enrichment import enrich_metadata

    console.print("[cyan]Retrying failed ingestion steps...[/cyan]")
    enrich_metadata()
    download_lyrics()
    console.print("[green]Retry complete.[/green]")


@app.command("rebuild-embeddings")
def rebuild_embeddings():
    """Rebuild the entire FAISS embedding index."""
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings
    generate_embeddings(rebuild=True)


@app.command()
def search(
    word: Optional[str] = typer.Option(None, help="Keyword to search in lyrics."),
    query: Optional[str] = typer.Option(None, help="Semantic query (e.g. 'songs about freedom')."),
    year: Optional[int] = typer.Option(None),
    year_min: Optional[int] = typer.Option(None),
    year_max: Optional[int] = typer.Option(None),
    artist: Optional[str] = typer.Option(None),
    genre: Optional[str] = typer.Option(None),
    limit: int = typer.Option(20),
    lyrics: bool = typer.Option(
        False,
        "--lyrics",
        help="Include lyrics preview in results.",
    ),
):
    """Search the knowledge base."""
    if query:
        results = svc_semantic_query(query, top_k=limit)
    else:
        response = keyword_search_with_expansion(
            SearchRequest(
                word=word,
                year=year,
                year_min=year_min,
                year_max=year_max,
                artist=artist,
                genre=genre,
                limit=limit,
            )
        )
        results = response["results"]

    if not results:
        console.print("[yellow]No results found locally.[/yellow]")
        from music_teacher_ai.pipeline.expansion import trigger_expansion
        if trigger_expansion(genre=genre, artist=artist, year=year, word=word):
            console.print("[dim]Triggering discovery job — future searches may return new songs.[/dim]")
        return

    if lyrics:
        song_ids: list[int] = []
        for row in results:
            song_id = row.get("song_id") or row.get("id")
            if isinstance(song_id, int):
                song_ids.append(song_id)

        lyrics_by_song_id: dict[int, str] = {}
        if song_ids:
            with get_session() as session:
                lyric_rows = session.exec(
                    select(Lyrics).where(Lyrics.song_id.in_(song_ids))
                ).all()
            for lyr in lyric_rows:
                # Keep table readable while still exposing lyrics from search.
                text = (lyr.lyrics_text or "").strip().replace("\n", " ")
                lyrics_by_song_id[lyr.song_id] = (
                    text[:200] + ("..." if len(text) > 200 else "")
                )

        for row in results:
            song_id = row.get("song_id") or row.get("id")
            row["lyrics"] = lyrics_by_song_id.get(song_id, "")

    table = Table()
    for col in results[0].keys():
        table.add_column(col.title())
    for row in results:
        table.add_row(*[str(v) for v in row.values()])
    console.print(table)


@app.command()
def similar(
    song: Optional[str] = typer.Option(None, help="Song title to find similar songs for."),
    song_id: Optional[int] = typer.Option(None, help="Song ID to find similar songs for."),
    text: Optional[str] = typer.Option(None, help="Lyric fragment or theme to match against."),
    artist: Optional[str] = typer.Option(None, help="Artist filter when using --song."),
    top: int = typer.Option(10, help="Number of results."),
    min_score: float = typer.Option(0.0, help="Minimum similarity score (0.0–1.0)."),
):
    """Find songs with lyrically similar content."""
    from music_teacher_ai.search.similar_search import (
        find_similar_by_song,
        find_similar_by_text,
        find_similar_by_title,
    )

    try:
        if song_id is not None:
            results = find_similar_by_song(song_id, top_k=top, min_score=min_score)
        elif song:
            results = find_similar_by_title(song, artist=artist, top_k=top, min_score=min_score)
        elif text:
            results = find_similar_by_text(text, top_k=top, min_score=min_score)
        else:
            console.print("[red]Provide --song, --song-id, or --text.[/red]")
            raise typer.Exit(1)
    except (ValueError, FileNotFoundError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if not results:
        console.print("[yellow]No similar songs found.[/yellow]")
        return

    table = Table(title="Similar Songs")
    for col in results[0].keys():
        table.add_column(col.title())
    for row in results:
        table.add_row(*[str(v) for v in row.values()])
    console.print(table)


# ---------------------------------------------------------------------------
# Exercise sub-commands  (music-teacher exercise <sub-command>)
# ---------------------------------------------------------------------------

@exercise_app.command("show")
def exercise_show(
    song_id: int = typer.Argument(..., help="Song database ID"),
    num_blanks: int = typer.Option(10, "--blanks", "-n", help="Number of blanks to create."),
    min_word_length: int = typer.Option(4, "--min-length", help="Minimum word length to blank."),
):
    """Generate a numbered fill-in-the-blank exercise from a song's lyrics."""
    from rich.panel import Panel
    from sqlmodel import select

    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.education_services.exercises.fill_in_blank import generate

    with get_session() as session:
        lyr = session.exec(select(Lyrics).where(Lyrics.song_id == song_id)).first()
        if not lyr:
            console.print(f"[red]No lyrics found for song ID {song_id}.[/red]")
            raise typer.Exit(1)
        song = session.get(Song, song_id)
        artist_obj = session.get(Artist, song.artist_id) if song else None
        title = song.title if song else ""
        artist_name = artist_obj.name if artist_obj else ""

    ex = generate(lyr.lyrics_text, song_title=title, artist=artist_name,
                  num_blanks=num_blanks, min_word_length=min_word_length)

    console.print(Panel(
        f"[bold]{ex.song_title}[/bold] — {ex.artist}",
        title="Fill-in-the-Blank Exercise",
        border_style="cyan",
        expand=False,
    ))
    console.print()
    console.print(ex.text_with_blanks)
    console.print()

    table = Table(title="Answer Key", show_header=True, header_style="green")
    table.add_column("#", width=4)
    table.add_column("Word")
    for b in ex.blanks:
        table.add_row(str(b.number), b.word)
    console.print(table)


@exercise_app.command("lesson")
def exercise_lesson(
    song_id: int = typer.Argument(..., help="Song database ID"),
    num_blanks: int = typer.Option(10, "--blanks", "-n", help="Number of fill-in-blank gaps."),
    min_word_length: int = typer.Option(4, "--min-length", help="Minimum word length."),
):
    """Build a complete English lesson for a song (exercise + vocabulary + phrasal verbs)."""
    from rich.panel import Panel
    from sqlmodel import select

    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

    with get_session() as session:
        lyr = session.exec(select(Lyrics).where(Lyrics.song_id == song_id)).first()
        if not lyr:
            console.print(f"[red]No lyrics found for song ID {song_id}.[/red]")
            raise typer.Exit(1)
        song = session.get(Song, song_id)
        artist_obj = session.get(Artist, song.artist_id) if song else None
        title = song.title if song else ""
        artist_name = artist_obj.name if artist_obj else ""

    les = build_lesson(
        song_id=song_id,
        lyrics=lyr.lyrics_text,
        song_title=title,
        artist=artist_name,
        num_blanks=num_blanks,
        min_word_length=min_word_length,
    )

    console.print(Panel(
        f"[bold]{les.song_title}[/bold] — {les.artist}",
        title="Music Lesson",
        border_style="cyan",
        expand=False,
    ))

    # Exercise
    console.print("\n[bold cyan]── Fill-in-the-Blank Exercise ──[/bold cyan]")
    console.print(les.exercise.text_with_blanks)
    console.print()
    key_table = Table(title="Answer Key", header_style="green")
    key_table.add_column("#", width=4)
    key_table.add_column("Word")
    for b in les.exercise.blanks:
        key_table.add_row(str(b.number), b.word)
    console.print(key_table)

    # Vocabulary
    console.print("\n[bold cyan]── Vocabulary Analysis (CEFR) ──[/bold cyan]")
    vocab = les.vocabulary
    voc_table = Table(header_style="cyan")
    voc_table.add_column("Level", width=6)
    voc_table.add_column("Words", width=7)
    voc_table.add_column("%", width=6)
    voc_table.add_column("Examples")
    for lv in ["A1", "A2", "B1", "B2", "C1", "C2"]:
        count = vocab.level_counts[lv]
        pct = vocab.level_percentages[lv]
        examples = ", ".join(e.word for e in vocab.words_by_level[lv][:5])
        marker = " ◀" if lv == vocab.dominant_level else ""
        voc_table.add_row(lv + marker, str(count), f"{pct}%", examples)
    console.print(voc_table)

    # Phrasal verbs
    pv = les.phrasal_verbs
    console.print(f"\n[bold cyan]── Phrasal Verbs ({pv.total_matches} matches) ──[/bold cyan]")
    if pv.unique_phrasal_verbs:
        console.print(", ".join(pv.unique_phrasal_verbs))
    else:
        console.print("[dim]None detected.[/dim]")


@exercise_app.command("generate")
def exercise_generate(
    song: Optional[str] = typer.Option(
        None,
        "--song",
        help="Song ID (numeric) or song title to search for.",
    ),
    semantic: Optional[str] = typer.Option(None, "--semantic", help="Semantic query, e.g. 'songs about dreams'."),
    playlist: Optional[str] = typer.Option(None, "--playlist", help="Playlist slug — generates one section per song."),
    words: Optional[str] = typer.Option(None, "--words", help="Space-separated words to blank (manual mode), e.g. 'imagine world heaven'."),
    random_mode: bool = typer.Option(False, "--random", help="Randomly blank words based on --level."),
    level: int = typer.Option(20, "--level", help="Percentage of words to blank in random mode (10, 20, or 30)."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output filename (default: exercise_YYYYMMDD_HHMM.txt)."),
):
    """
    Generate a listening fill-the-gaps exercise and export it to a .txt file.

    Examples:

      music-teacher exercise generate --song "Imagine" --random --level 20

      music-teacher exercise generate --song "Imagine" --words "imagine world heaven"

      music-teacher exercise generate --playlist dream_playlist --level 30

      music-teacher exercise generate --semantic "songs about dreams" --random
    """
    from sqlmodel import select

    from music_teacher_ai.config.settings import EXERCISES_DIR
    from music_teacher_ai.database.models import Artist, Lyrics
    from music_teacher_ai.education_services.exercises.gap_fill import (
        generate_manual,
        generate_random,
        render_text,
    )

    if not any([song, semantic, playlist]):
        console.print("[red]Provide --song, --semantic, or --playlist.[/red]")
        raise typer.Exit(1)
    if not words and not random_mode:
        console.print("[red]Provide --words for manual mode or --random for random selection.[/red]")
        raise typer.Exit(1)

    def _expand_and_exit(word: Optional[str] = None) -> None:
        """Trigger background expansion using the same path as the search command."""
        from music_teacher_ai.pipeline.jobs import get_job_runner
        triggered = get_job_runner().trigger_expansion(word=word)
        if triggered:
            console.print(
                "[dim]Triggering discovery job — run the same command again in a few minutes.[/dim]"
            )
        raise typer.Exit(1)

    # ---- resolve lyrics entries ----
    entries: list[tuple[str, str, str]] = []  # (lyrics_text, title, artist)

    if playlist:
        from music_teacher_ai.playlists.manager import get as get_playlist
        try:
            pl = get_playlist(playlist)
        except FileNotFoundError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        with get_session() as session:
            for ps in pl.songs:
                lyr = session.exec(select(Lyrics).where(Lyrics.song_id == ps.song_id)).first()
                if lyr:
                    entries.append((lyr.lyrics_text, ps.title, ps.artist))
        if not entries:
            console.print("[yellow]No lyrics found for any song in the playlist.[/yellow]")
            # Use first song title as expansion hint if available
            hint = pl.songs[0].title if pl.songs else None
            _expand_and_exit(word=hint)

    elif semantic:
        from music_teacher_ai.search.semantic_search import semantic_search
        try:
            results = semantic_search(semantic, top_k=5)
        except FileNotFoundError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)
        if not results:
            console.print("[yellow]No songs found for that query.[/yellow]")
            _expand_and_exit(word=semantic)
        with get_session() as session:
            for r in results:   # walk all candidates until one has lyrics
                lyr = session.exec(select(Lyrics).where(Lyrics.song_id == r["id"])).first()
                if lyr:
                    entries.append((lyr.lyrics_text, r["title"], r["artist"]))
                    break
        if not entries:
            console.print("[yellow]No lyrics found for any of the top semantic results.[/yellow]")
            _expand_and_exit(word=results[0]["title"] if results else None)

    else:  # --song
        from music_teacher_ai.database.models import Song as SongModel

        with get_session() as session:
            # If --song is numeric, treat it as exact song ID.
            by_id = song.isdigit() if song else False
            if by_id:
                s = session.get(SongModel, int(song))
                if not s:
                    console.print(f"[yellow]Song ID {song} not found.[/yellow]")
                    raise typer.Exit(1)
                lyr = session.exec(select(Lyrics).where(Lyrics.song_id == s.id)).first()
                if not lyr or not (lyr.lyrics_text or "").strip():
                    console.print(f"[yellow]Lyrics not yet downloaded for song ID {song}.[/yellow]")
                    raise typer.Exit(1)
                artist_obj = session.get(Artist, s.artist_id)
                entries.append((lyr.lyrics_text, s.title, artist_obj.name if artist_obj else ""))
            else:
                # Title search constrained to songs that actually have lyrics.
                # Prefer locally-seeded/manual tracks first when multiple rows match.
                rows = session.exec(
                    select(SongModel, Lyrics, Artist)
                    .join(Lyrics, Lyrics.song_id == SongModel.id)
                    .join(Artist, Artist.id == SongModel.artist_id)
                    .where(SongModel.title.ilike(f"%{song}%"))
                    .where(Lyrics.lyrics_text != None)  # noqa: E711
                    .order_by(
                        SongModel.metadata_source.in_(["failed", "lyrics_only"]).desc(),
                        SongModel.id.desc(),
                    )
                    .limit(1)
                ).all()
                if not rows:
                    console.print(
                        f"[yellow]No song with lyrics found matching title '{song}'.[/yellow]"
                    )
                    _expand_and_exit(word=song)
                s, lyr, artist_obj = rows[0]
                entries.append((lyr.lyrics_text, s.title, artist_obj.name if artist_obj else ""))

    # ---- build exercise text ----
    word_list = words.split() if words else []
    sections: list[str] = []

    for lyrics_text, title, artist_name in entries:
        if word_list:
            ex = generate_manual(lyrics_text, word_list, song_title=title, artist=artist_name)
        else:
            ex = generate_random(lyrics_text, song_title=title, artist=artist_name, level=level)
        sections.append(render_text(ex))

    separator = "\n\n" + "=" * 60 + "\n\n"
    full_text = separator.join(sections)

    # ---- export ----
    from music_teacher_ai.education_services.exercises.gap_fill import export_text
    out_path = export_text(full_text, EXERCISES_DIR, output)

    console.print(f"[green]Exercise saved to {out_path}[/green]")
    console.print(f"[dim]{len(entries)} song(s) · {len(sections)} section(s)[/dim]")


@app.command()
def doctor(
    skip_spotify: bool = typer.Option(False, "--skip-spotify", help="Skip Spotify API check."),
    skip_genius: bool = typer.Option(False, "--skip-genius", help="Skip Genius API check."),
    skip_billboard: bool = typer.Option(False, "--skip-billboard", help="Skip Billboard check."),
):
    """
    Run a health check on every system component and report pass/fail.

    Checks credentials, external APIs, local model, database, and FAISS index.
    No data is written to the real database.
    """
    import os
    import tempfile
    from pathlib import Path

    from rich.table import Table as RichTable

    results: list[tuple[str, str, str]] = []  # (component, status, detail)

    def check(name: str):
        """Context manager: records PASS/FAIL for a named check."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            try:
                yield
                results.append((name, "[green]PASS[/green]", ""))
            except Exception as exc:
                results.append((name, "[red]FAIL[/red]", str(exc)))

        return _ctx()

    # ------------------------------------------------------------------
    # 1. Environment / credentials
    # ------------------------------------------------------------------
    with check("Env: SPOTIFY_CLIENT_ID set"):
        assert os.getenv("SPOTIFY_CLIENT_ID"), "Not set"

    with check("Env: SPOTIFY_CLIENT_SECRET set"):
        assert os.getenv("SPOTIFY_CLIENT_SECRET"), "Not set"

    with check("Env: GENIUS_ACCESS_TOKEN set"):
        assert os.getenv("GENIUS_ACCESS_TOKEN"), "Not set"

    # ------------------------------------------------------------------
    # 2. Spotify
    # ------------------------------------------------------------------
    if not skip_spotify:
        with check("Spotify: authentication"):
            from spotipy.exceptions import SpotifyException

            from music_teacher_ai.core.spotify_client import SpotifyPremiumRequiredError, get_client
            sp = get_client()
            try:
                r = sp.search(q="Imagine", type="track", limit=1)
                assert r["tracks"]["items"], "No results"
            except SpotifyException as exc:
                if exc.http_status == 403:
                    raise SpotifyPremiumRequiredError(
                        "403 – app owner needs Spotify Premium or Extended Quota Mode. "
                        "See: https://developer.spotify.com/documentation/web-api/concepts/quota-modes"
                    ) from exc
                raise

        with check("Spotify: search_track() for 'Imagine'"):
            from music_teacher_ai.core.spotify_client import (
                SpotifyPremiumRequiredError,
                search_track,
            )
            meta = search_track("Imagine", "John Lennon")
            assert meta is not None, "Returned None"
            assert meta.spotify_id

        with check("Spotify: audio features populated"):
            from music_teacher_ai.core.spotify_client import (
                SpotifyPremiumRequiredError,
                search_track,
            )
            meta = search_track("Imagine", "John Lennon")
            assert meta and meta.energy is not None

    # ------------------------------------------------------------------
    # 3. Billboard
    # ------------------------------------------------------------------
    if not skip_billboard:
        with check("Billboard: fetch Hot 100 for year 2000"):
            from music_teacher_ai.core.billboard_client import fetch_chart_for_year
            entries = fetch_chart_for_year(2000)
            assert len(entries) == 100, f"Got {len(entries)} entries"

    # ------------------------------------------------------------------
    # 4. Genius
    # ------------------------------------------------------------------
    if not skip_genius:
        with check("Genius: fetch lyrics for 'Imagine'"):
            from music_teacher_ai.core.lyrics_client import fetch_lyrics
            lyrics = fetch_lyrics("Imagine", "John Lennon")
            assert lyrics and len(lyrics) > 100, "Lyrics too short or None"

    # ------------------------------------------------------------------
    # 5. MusicBrainz (no credentials needed)
    # ------------------------------------------------------------------
    with check("MusicBrainz: search 'Imagine'"):
        from music_teacher_ai.core.musicbrainz_client import search_track as mb_search
        meta = mb_search("Imagine", "John Lennon")
        assert meta is not None, "No result from MusicBrainz"
        assert meta.title

    # ------------------------------------------------------------------
    # 6. Last.fm (optional)
    # ------------------------------------------------------------------
    with check("Last.fm: LASTFM_API_KEY set"):
        assert os.getenv("LASTFM_API_KEY"), "Not set (optional – genres/tags will be skipped)"

    with check("Last.fm: get tags for 'Imagine'"):
        from music_teacher_ai.core.lastfm_client import get_tags, is_configured
        if not is_configured():
            raise AssertionError("LASTFM_API_KEY not set — skipping")
        tags = get_tags("Imagine", "John Lennon")
        assert isinstance(tags, list)

    # ------------------------------------------------------------------
    # 7. Database
    # ------------------------------------------------------------------
    with check("Database: schema creation"):
        with tempfile.TemporaryDirectory() as tmp:
            import os as _os
            _os.environ["DATABASE_PATH"] = str(Path(tmp) / "test.db")
            import importlib

            import music_teacher_ai.config.settings as _s
            import music_teacher_ai.database.sqlite as _db
            importlib.reload(_s)
            importlib.reload(_db)
            _db.create_db()

    with check("Database: insert and query"):
        from music_teacher_ai.database.models import Artist
        from music_teacher_ai.database.sqlite import get_session
        with get_session() as s:
            a = Artist(name="__smoke_test__")
            s.add(a)
            s.commit()
            fetched = s.get(Artist, a.id)
            assert fetched.name == "__smoke_test__"

    # ------------------------------------------------------------------
    # 8. Embedding model
    # ------------------------------------------------------------------
    with check("Embeddings: model loads"):
        from sentence_transformers import SentenceTransformer

        from music_teacher_ai.config.settings import EMBEDDING_MODEL
        SentenceTransformer(EMBEDDING_MODEL)

    with check("Embeddings: correct vector shape (384-dim)"):
        import numpy as np
        from sentence_transformers import SentenceTransformer

        from music_teacher_ai.config.settings import EMBEDDING_DIM, EMBEDDING_MODEL
        model = SentenceTransformer(EMBEDDING_MODEL)
        vec = model.encode(["test"], normalize_embeddings=True)
        assert vec.shape == (1, EMBEDDING_DIM), f"Got {vec.shape}"

    # ------------------------------------------------------------------
    # 9. FAISS
    # ------------------------------------------------------------------
    with check("FAISS: index create / add / search"):
        import faiss
        import numpy as np

        from music_teacher_ai.config.settings import EMBEDDING_DIM
        idx = faiss.IndexFlatIP(EMBEDDING_DIM)
        v = np.random.randn(1, EMBEDDING_DIM).astype(np.float32)
        v /= np.linalg.norm(v)
        idx.add(v)
        d, i = idx.search(v, 1)
        assert i[0][0] == 0

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------
    table = RichTable(title="Music Teacher AI – System Health Check", show_lines=True)
    table.add_column("Component", style="cyan", min_width=40)
    table.add_column("Status", min_width=8)
    table.add_column("Detail", style="dim")

    passed = sum(1 for _, s, _ in results if "PASS" in s)
    for name, status, detail in results:
        table.add_row(name, status, detail)

    console.print()
    console.print(table)
    console.print()

    total = len(results)
    if passed == total:
        console.print(f"[bold green]All {total} checks passed.[/bold green]")
    else:
        failed = total - passed
        console.print(f"[bold red]{failed}/{total} checks failed.[/bold red]")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Playlist sub-commands
# ---------------------------------------------------------------------------

def _print_playlist(playlist) -> None:
    """Pretty-print a single playlist to the terminal."""
    from rich.panel import Panel
    header = f"[bold]{playlist.name}[/bold]"
    if playlist.description:
        header += f"\n[dim]{playlist.description}[/dim]"
    header += f"\n[dim]Created: {playlist.created_at} · {len(playlist.songs)} songs[/dim]"
    console.print(Panel(header, expand=False))

    table = Table(show_header=True, header_style="cyan")
    table.add_column("#", width=4)
    table.add_column("Title")
    table.add_column("Artist")
    table.add_column("Year", width=6)
    for i, song in enumerate(playlist.songs, 1):
        table.add_row(str(i), song.title, song.artist, str(song.year or ""))
    console.print(table)


@playlist_app.command("create")
def playlist_create(
    name: str = typer.Argument(..., help="Playlist name, e.g. 'Dream Vocabulary'"),
    description: Optional[str] = typer.Option(None, "--description", "-d"),
    word: Optional[str] = typer.Option(None, help="Keyword to search in lyrics"),
    song: Optional[str] = typer.Option(None, "--song", help="Song title to search for, e.g. 'Dream On'"),
    year: Optional[int] = typer.Option(None),
    year_min: Optional[int] = typer.Option(None),
    year_max: Optional[int] = typer.Option(None),
    artist: Optional[str] = typer.Option(None),
    genre: Optional[str] = typer.Option(None),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Semantic/theme query"),
    similar_text: Optional[str] = typer.Option(None, "--similar-text", help="Text to find similar songs for"),
    similar_song_id: Optional[int] = typer.Option(None, "--similar-song-id"),
    limit: int = typer.Option(20, help="Max songs in playlist (hard cap: 100)"),
):
    """Create a playlist from a search query."""
    try:
        playlist = svc_create_playlist(
            {
                "name": name,
                "description": description,
                "word": word,
                "song": song,
                "year": year,
                "year_min": year_min,
                "year_max": year_max,
                "artist": artist,
                "genre": genre,
                "semantic_query": query,
                "similar_text": similar_text,
                "similar_song_id": similar_song_id,
                "limit": limit,
            }
        )
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    from music_teacher_ai.playlists.models import Playlist

    playlist_model = Playlist.model_validate(playlist)
    _print_playlist(playlist_model)
    console.print(f"[green]Saved to data/playlists/{playlist_model.id}/[/green]")


@playlist_app.command("show")
def playlist_show(
    playlist_id: str = typer.Argument(..., help="Playlist slug (from 'playlist list')"),
):
    """Display a saved playlist."""
    try:
        from music_teacher_ai.playlists.models import Playlist

        playlist = Playlist.model_validate(svc_get_playlist(playlist_id))
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _print_playlist(playlist)


@playlist_app.command("list")
def playlist_list():
    """List all saved playlists."""
    from music_teacher_ai.playlists.models import Playlist

    playlists = [Playlist.model_validate(p) for p in svc_list_playlists()]
    if not playlists:
        console.print("[yellow]No playlists found.[/yellow]")
        return

    table = Table(title="Saved Playlists")
    table.add_column("ID (slug)", style="cyan")
    table.add_column("Name")
    table.add_column("Songs", width=6)
    table.add_column("Created", width=12)
    for p in playlists:
        table.add_row(p.id, p.name, str(len(p.songs)), p.created_at)
    console.print(table)


@playlist_app.command("delete")
def playlist_delete(
    playlist_id: str = typer.Argument(..., help="Playlist slug to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a saved playlist."""
    if not yes:
        typer.confirm(f"Delete playlist '{playlist_id}'?", abort=True)
    try:
        svc_delete_playlist(playlist_id)
        console.print(f"[green]Deleted '{playlist_id}'.[/green]")
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)


@playlist_app.command("export")
def playlist_export(
    playlist_id: str = typer.Argument(..., help="Playlist slug"),
    fmt: str = typer.Option("m3u", "--format", "-f", help="Format: json, m3u, m3u8"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: print to stdout)"),
):
    """Export a playlist to a specific format."""
    try:
        content = svc_export_playlist(playlist_id, fmt)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]Exported to {output}[/green]")
    else:
        console.print(content)


@playlist_app.command("refresh")
def playlist_refresh(
    playlist_id: str = typer.Argument(..., help="Playlist slug to refresh"),
):
    """Re-run the stored query and update the playlist with fresh results."""
    try:
        from music_teacher_ai.playlists.models import Playlist

        playlist = Playlist.model_validate(svc_refresh_playlist(playlist_id))
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    _print_playlist(playlist)
    console.print(f"[green]Refreshed '{playlist_id}' — {len(playlist.songs)} songs.[/green]")


def _maybe_upgrade_demo(env: dict, updates: dict) -> None:
    """
    If Genius is now configured and the DB contains demo songs, replace their
    hardcoded lyrics with real ones downloaded from Genius.
    """
    import os

    from sqlmodel import select

    from music_teacher_ai.database.models import Song
    from music_teacher_ai.database.sqlite import get_session

    genius_key = updates.get("GENIUS_ACCESS_TOKEN") or env.get("GENIUS_ACCESS_TOKEN") or os.getenv("GENIUS_ACCESS_TOKEN")
    if not genius_key:
        return

    try:
        with get_session() as session:
            demo_count = len(session.exec(
                select(Song).where(Song.metadata_source == "demo")
            ).all())
    except Exception:
        return

    if not demo_count:
        return

    console.print(
        f"\n[cyan]Genius credentials set — replacing hardcoded lyrics for "
        f"{demo_count} demo song(s) with real downloads...[/cyan]"
    )
    from music_teacher_ai.ingestion.seed_ingestion import seed_songs
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics

    result = seed_songs()
    if result["upgraded"]:
        console.print(f"  [green]Upgraded {result['upgraded']} demo song(s)[/green]")
    download_lyrics()


@app.command()
def config(
    show: bool = typer.Option(False, "--show", help="Print current credential status and exit."),
):
    """
    Set or update API credentials stored in .env.

    Each prompt shows the current value (masked for secrets). Press Enter to
    keep the existing value. The ADMIN_TOKEN used to protect the REST and MCP
    config endpoints is displayed once — it is also readable from .env at any time.
    """
    from rich.panel import Panel
    from rich.table import Table as RichTable

    from music_teacher_ai.config.credentials import (
        FIELDS,
        current_status,
        get_admin_token,
        mask,
        read_env,
        update_env,
    )

    if show:
        table = RichTable(title="Credential Status", show_lines=True)
        table.add_column("Key", style="cyan")
        table.add_column("Label")
        table.add_column("Required", width=8)
        table.add_column("Set", width=5)
        table.add_column("Value")
        for row in current_status():
            req = "[yellow]yes[/yellow]" if row["required"] else "no"
            set_icon = "[green]✓[/green]" if row["set"] else "[red]✗[/red]"
            table.add_row(row["key"], row["label"], req, set_icon, row["masked_value"])
        console.print(table)
        return

    # Ensure admin token exists before prompting anything else
    token = get_admin_token()

    env = read_env()
    updates: dict[str, str] = {}

    console.print()
    console.print("[bold]Configure API credentials[/bold]  (press Enter to keep current value)")
    console.print()

    for field in FIELDS:
        current = env.get(field.key, "")
        current_display = mask(current) if field.secret else (current or "(not set)")
        label = f"{field.label}"
        if field.required:
            label += " [yellow]*required[/yellow]"
        if field.help:
            label += f"\n  [dim]{field.help}[/dim]"

        prompt_text = f"{label}\n  current: {current_display}\n  new value"
        new_value = typer.prompt(
            prompt_text,
            default="",
            hide_input=field.secret,
            show_default=False,
        ).strip()

        if new_value:
            updates[field.key] = new_value
        console.print()

    if updates:
        update_env(updates)
        console.print(f"[green]Saved {len(updates)} credential(s) to .env[/green]")
    else:
        console.print("[dim]No changes made.[/dim]")

    # If Genius is now configured and demo songs are present, replace hardcoded lyrics
    _maybe_upgrade_demo(env, updates)

    # Display admin token (first generation or reminder)
    console.print()
    console.print(Panel(
        f"[bold]REST / MCP admin token[/bold]\n\n"
        f"  [cyan]{token}[/cyan]\n\n"
        f"  Use as [bold]Authorization: Bearer <token>[/bold] header for [bold]POST /config[/bold].\n"
        f"  For MCP, pass as [bold]admin_token[/bold] in the tool inputs.\n"
        f"  The token is also stored in [dim].env[/dim] as [bold]ADMIN_TOKEN[/bold].",
        title="Admin Token",
        border_style="yellow",
        expand=False,
    ))


@app.command()
def inspect(
    target: str = typer.Argument("songs", help="What to inspect: 'songs'"),
    limit: int = typer.Option(500, "--limit", help="Maximum songs to scan."),
    fix: bool = typer.Option(False, "--fix", help="Delete invalid records automatically."),
):
    """
    Scan the database for corrupted or suspicious records.

    Examples:

      music-teacher inspect songs

      music-teacher inspect songs --limit 1000

      music-teacher inspect songs --fix
    """
    from sqlmodel import select

    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.validation import (
        validate_artist,
        validate_lyrics,
        validate_title,
    )

    if target != "songs":
        console.print(f"[red]Unknown target '{target}'. Use: songs[/red]")
        raise typer.Exit(1)

    issues_found = 0

    with get_session() as session:
        songs = session.exec(select(Song).limit(limit)).all()
        total = len(songs)
        console.print(f"[cyan]Scanning {total} songs…[/cyan]")

        for song in songs:
            artist_obj = session.get(Artist, song.artist_id)
            artist_name = artist_obj.name if artist_obj else ""
            lyr = session.exec(
                select(Lyrics).where(Lyrics.song_id == song.id)
            ).first()

            song_issues: list[str] = []

            tr = validate_title(song.title)
            if not tr.ok:
                song_issues.extend(f"title: {i}" for i in tr.issues)

            ar = validate_artist(artist_name)
            if not ar.ok:
                song_issues.extend(f"artist: {i}" for i in ar.issues)

            if lyr:
                lr = validate_lyrics(lyr.lyrics_text)
                if not lr.ok:
                    song_issues.extend(f"lyrics: {i}" for i in lr.issues)

            if song_issues:
                issues_found += 1
                console.print(
                    f"[yellow]Song ID {song.id}[/yellow] "
                    f"[bold]{song.title!r}[/bold] – {artist_name!r}"
                )
                for iss in song_issues:
                    console.print(f"  [red]✗[/red] {iss}")
                if fix:
                    if lyr and any("lyrics" in i for i in song_issues):
                        session.delete(lyr)
                        console.print(f"  [dim]Deleted corrupt lyrics for song {song.id}[/dim]")
                    if any(i.startswith("title") or i.startswith("artist") for i in song_issues):
                        session.delete(song)
                        console.print(f"  [dim]Deleted corrupt song record {song.id}[/dim]")

        if fix and issues_found:
            session.commit()

    if issues_found:
        console.print(
            f"\n[yellow]Found {issues_found} suspicious record(s).[/yellow]"
            + (" Fixed." if fix else " Run with [bold]--fix[/bold] to delete them.")
        )
    else:
        console.print(f"[green]All {total} songs passed validation.[/green]")


@app.command()
def repair(
    target: str = typer.Argument(..., help="Target type: 'song'"),
    record_id: int = typer.Argument(..., help="Record ID to repair"),
):
    """
    Re-fetch metadata and lyrics for a specific song.

    Backs up the current record, clears corrupted fields, then fetches fresh
    data from external APIs.  Rolls back if validation fails.

    Example:

      music-teacher repair song 262
    """

    from sqlmodel import select

    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.database.sqlite import get_session
    from music_teacher_ai.pipeline.validation import validate_lyrics, validate_title

    if target != "song":
        console.print(f"[red]Unknown target '{target}'. Use: song <id>[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        song = session.get(Song, record_id)
        if not song:
            console.print(f"[red]Song {record_id} not found.[/red]")
            raise typer.Exit(1)

        artist_obj = session.get(Artist, song.artist_id)
        artist_name = artist_obj.name if artist_obj else ""
        console.print(
            f"[cyan]Repairing song {record_id}:[/cyan] "
            f"[bold]{song.title!r}[/bold] – {artist_name!r}"
        )

        # --- Backup current state ---
        backup_lyrics   = None
        lyr = session.exec(select(Lyrics).where(Lyrics.song_id == record_id)).first()
        if lyr:
            backup_lyrics = lyr.lyrics_text

        # --- Validate title first ---
        if not validate_title(song.title).ok:
            console.print("[yellow]Title looks corrupt — cannot safely re-fetch. Aborting.[/yellow]")
            raise typer.Exit(1)

        # --- Re-fetch metadata ---
        console.print("[dim]  Re-fetching metadata…[/dim]")
        try:
            from music_teacher_ai.pipeline.metadata_enrichment import (
                _apply_metadata,
                _enrich_with_lastfm,
                _try_musicbrainz,
            )
            meta = _try_musicbrainz(song.title, artist_name)
            if meta:
                meta = _enrich_with_lastfm(meta)
                song.metadata_source = None   # force re-apply
                _apply_metadata(session, song, artist_obj, meta)
                console.print("[green]  Metadata updated.[/green]")
            else:
                console.print("[yellow]  No metadata found — keeping existing.[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]  Metadata fetch failed: {exc}[/yellow]")

        # --- Re-fetch lyrics ---
        console.print("[dim]  Re-fetching lyrics…[/dim]")
        try:
            from music_teacher_ai.core.lyrics_client import fetch_lyrics
            from music_teacher_ai.pipeline.validation import validate_lyrics

            new_lyrics = fetch_lyrics(song.title, artist_name)
            if new_lyrics:
                vr = validate_lyrics(new_lyrics)
                if vr.ok:
                    if lyr:
                        lyr.lyrics_text = new_lyrics
                        session.add(lyr)
                    else:
                        import re as _re
                        words = _re.findall(r"\b[a-z']+\b", new_lyrics.lower())
                        session.add(Lyrics(
                            song_id=record_id,
                            lyrics_text=new_lyrics,
                            word_count=len(words),
                            unique_words=len(set(words)),
                        ))
                    console.print("[green]  Lyrics updated.[/green]")
                else:
                    console.print(f"[yellow]  New lyrics failed validation ({vr}) — reverting.[/yellow]")
                    if lyr and backup_lyrics:
                        lyr.lyrics_text = backup_lyrics
                        session.add(lyr)
            else:
                console.print("[yellow]  No lyrics found — keeping existing.[/yellow]")
        except Exception as exc:
            console.print(f"[yellow]  Lyrics fetch failed: {exc}[/yellow]")
            if lyr and backup_lyrics:
                lyr.lyrics_text = backup_lyrics
                session.add(lyr)

        session.commit()
        console.print(f"[green]Repair complete for song {record_id}.[/green]")


@app.command()
def start(
    minimal: bool = typer.Option(False, "--minimal", help="Start with the built-in demo dataset."),
    host: str = typer.Option("127.0.0.1", "--host", help="API server host."),
    port: int = typer.Option(8000, "--port", help="API server port."),
):
    """
    Start the REST API server, optionally in minimal/demo mode.

    In minimal mode the built-in 10-song demo dataset is loaded automatically
    and no API credentials are required.

    Example:

      music-teacher start --minimal

      music-teacher start --host 0.0.0.0 --port 8080
    """
    from music_teacher_ai.database.sqlite import create_db
    from music_teacher_ai.demo.loader import (
        auto_load_demo_if_needed,
        load_demo_songs,
        print_minimal_banner,
    )

    create_db()

    if minimal:
        load_demo_songs()
        print_minimal_banner()
    else:
        auto_load_demo_if_needed()

    try:
        import uvicorn

        from music_teacher_ai.api.rest_api import app as api_app
        console.print(f"[green]Starting API server on {host}:{port}[/green]")
        console.print(f"[cyan]Web interface available at: http://{host}:{port}/web[/cyan]")
        uvicorn.run(api_app, host=host, port=port)
    except ImportError:
        console.print(
            "[yellow]uvicorn not installed — API server not started.[/yellow]\n"
            "Install with: [cyan]pip install uvicorn[/cyan]"
        )


def main():
    from music_teacher_ai.demo.loader import auto_load_demo_if_needed
    auto_load_demo_if_needed()
    app()
