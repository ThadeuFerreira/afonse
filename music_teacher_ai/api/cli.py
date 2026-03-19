from datetime import date
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select, func

from music_teacher_ai.application.enrichment_service import EnrichRequest, run_enrichment
from music_teacher_ai.application.errors import ValidationError
from music_teacher_ai.application.playlist_service import (
    create_playlist as svc_create_playlist,
    delete_playlist as svc_delete_playlist,
    export_playlist as svc_export_playlist,
    get_playlist as svc_get_playlist,
    list_playlists as svc_list_playlists,
    refresh_playlist as svc_refresh_playlist,
)
from music_teacher_ai.application.search_service import SearchRequest, keyword_search_with_expansion
from music_teacher_ai.application.search_service import semantic_query as svc_semantic_query
from music_teacher_ai.database.sqlite import create_db, get_session
from music_teacher_ai.database.models import Song, Lyrics, Embedding, Chart, IngestionFailure

app = typer.Typer(help="Music Teacher AI – manage and query the local knowledge base.")
playlist_app = typer.Typer(help="Create and manage song playlists.")
app.add_typer(playlist_app, name="playlist")
console = Console()


@app.command()
def migrate_db():
    """Run explicit database migrations and integrity index creation."""
    from music_teacher_ai.database.sqlite import migrate_db as run_migrations

    run_migrations()
    console.print("[green]Database migration complete.[/green]")


@app.command()
def init(
    start: int = typer.Option(1960, help="First year to ingest from Billboard."),
    end: int = typer.Option(None, help="Last year to ingest (default: current year)."),
    workers: int = typer.Option(5, "--workers", "-w", help="Parallel workers for Billboard fetch. Raise carefully — aggressive values may trigger rate-limiting."),
    quick: bool = typer.Option(False, "--quick", help="Quick start: top 10 songs/year since 2000 only (~25 years × 10 songs)."),
):
    """Initialize the knowledge base from scratch."""
    from music_teacher_ai.pipeline.charts_ingestion import ingest_charts
    from music_teacher_ai.pipeline.metadata_enrichment import enrich_metadata
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

    chart_limit = 10 if quick else None
    # Validate start and end years before computing the effective range.
    if start is None or not isinstance(start, int):
        start = date.today().year - 1
    if end is None or not isinstance(end, int):
        end = date.today().year - 1
    if start > end:
        start = date.today().year - 2
        end = date.today().year - 1
    if start < 1960:
        start = 1960
    if end < 1961:
        end = 1961

    # Apply quick-mode override after validation so the sanitized end is kept.
    chart_start = 2000 if quick else start

    if quick:
        console.print(
            "[bold yellow]Quick mode:[/bold yellow] fetching top 10 songs/year from 2000 to present. "
            "Run without --quick for full history."
        )

    console.print("[bold green]Creating database schema...[/bold green]")
    create_db()

    console.print("[bold green]Step 1/5 – Fetching Billboard charts...[/bold green]")
    ingest_charts(start=chart_start, end=end or date.today().year, workers=workers, limit=chart_limit)

    console.print("[bold green]Step 2/5 – Enriching metadata...[/bold green]")
    enrich_metadata(init_quick=quick)

    console.print("[bold green]Step 3/5 – Downloading lyrics...[/bold green]")
    download_lyrics()

    console.print("[bold green]Step 4/5 – Building vocabulary index...[/bold green]")
    build_vocabulary_index()

    console.print("[bold green]Step 5/5 – Generating embeddings...[/bold green]")
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

    table = Table(title="Music Teacher AI – Database Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Songs", str(songs))
    table.add_row("Lyrics", str(lyrics))
    table.add_row("Embeddings", str(embeddings))
    table.add_row("Chart entries", str(years))
    console.print(table)


@app.command()
def update(
    genre: Optional[str] = typer.Option(None, help="Genre to fetch from Spotify."),
    artist: Optional[str] = typer.Option(None, help="Artist discography to fetch."),
    year: Optional[int] = typer.Option(None, help="Year to re-ingest from Billboard."),
):
    """Incrementally update the knowledge base."""
    from music_teacher_ai.pipeline.metadata_enrichment import enrich_metadata
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

    if year:
        from music_teacher_ai.pipeline.charts_ingestion import ingest_charts
        ingest_charts(start=year, end=year)
    elif genre or artist:
        console.print(f"[yellow]Fetching Spotify tracks for genre={genre!r} artist={artist!r}[/yellow]")
        _spotify_update(genre=genre, artist=artist)
    else:
        console.print("[red]Provide --genre, --artist, or --year.[/red]")
        raise typer.Exit(1)

    enrich_metadata()
    download_lyrics()
    build_vocabulary_index()
    generate_embeddings()
    console.print("[green]Update complete.[/green]")


def _spotify_update(genre: Optional[str], artist: Optional[str]) -> None:
    import spotipy
    from music_teacher_ai.core.spotify_client import get_client, _parse_track
    from music_teacher_ai.database.models import Artist as ArtistModel, Song as SongModel
    from sqlmodel import select

    sp = get_client()
    if artist:
        results = sp.search(q=f"artist:{artist}", type="artist", limit=1)
        items = results.get("artists", {}).get("items", [])
        if not items:
            console.print(f"[red]Artist not found: {artist}[/red]")
            return
        artist_id = items[0]["id"]
        albums = sp.artist_albums(artist_id, album_type="album", limit=50)
        for album in albums.get("items", []):
            tracks = sp.album_tracks(album["id"])
            for track in tracks.get("items", []):
                full = sp.track(track["id"])
                _upsert_track(sp, full)
    elif genre:
        results = sp.search(q=f"genre:{genre}", type="track", limit=50)
        for track in results.get("tracks", {}).get("items", []):
            _upsert_track(sp, track)


def _upsert_track(sp, item: dict) -> None:
    from music_teacher_ai.core.spotify_client import _parse_track
    from music_teacher_ai.database.models import Artist as ArtistModel, Song as SongModel, Album
    from sqlmodel import select
    import json

    meta = _parse_track(sp, item)
    with get_session() as session:
        artist = session.exec(
            select(ArtistModel).where(ArtistModel.spotify_id == meta.artist_spotify_id)
        ).first()
        if not artist:
            artist = ArtistModel(
                name=meta.artist,
                spotify_id=meta.artist_spotify_id,
                genres=json.dumps(meta.genres),
            )
            session.add(artist)
            session.flush()

        song = session.exec(
            select(SongModel).where(SongModel.spotify_id == meta.spotify_id)
        ).first()
        if not song:
            song = SongModel(
                spotify_id=meta.spotify_id,
                title=meta.title,
                artist_id=artist.id,
                release_year=meta.release_year,
                popularity=meta.popularity,
                duration_ms=meta.duration_ms,
                tempo=meta.tempo,
                valence=meta.valence,
                energy=meta.energy,
                danceability=meta.danceability,
            )
            session.add(song)
        session.commit()


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
        from music_teacher_ai.pipeline.expansion import EXPANSION_THRESHOLD, trigger_expansion
        if trigger_expansion(genre=genre, artist=artist, year=year, word=word):
            console.print("[dim]Triggering discovery job — future searches may return new songs.[/dim]")
        return

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
        find_similar_by_title,
        find_similar_by_text,
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


@app.command()
def exercise(
    song_id: int = typer.Argument(..., help="Song database ID"),
    num_blanks: int = typer.Option(10, "--blanks", "-n", help="Number of blanks to create."),
    min_word_length: int = typer.Option(4, "--min-length", help="Minimum word length to blank."),
):
    """Generate a fill-in-the-blank exercise from a song's lyrics."""
    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.education_services.exercises.fill_in_blank import generate
    from sqlmodel import select

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

    from rich.panel import Panel
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


@app.command()
def lesson(
    song_id: int = typer.Argument(..., help="Song database ID"),
    num_blanks: int = typer.Option(10, "--blanks", "-n", help="Number of fill-in-blank gaps."),
    min_word_length: int = typer.Option(4, "--min-length", help="Minimum word length."),
):
    """Build a complete English lesson for a song (exercise + vocabulary + phrasal verbs)."""
    from music_teacher_ai.database.models import Artist, Lyrics, Song
    from music_teacher_ai.education_services.lesson_builder.builder import build_lesson
    from rich.panel import Panel
    from sqlmodel import select

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
    import traceback
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
            from music_teacher_ai.core.spotify_client import get_client, SpotifyPremiumRequiredError
            from spotipy.exceptions import SpotifyException
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
            from music_teacher_ai.core.spotify_client import search_track, SpotifyPremiumRequiredError
            meta = search_track("Imagine", "John Lennon")
            assert meta is not None, "Returned None"
            assert meta.spotify_id

        with check("Spotify: audio features populated"):
            from music_teacher_ai.core.spotify_client import search_track, SpotifyPremiumRequiredError
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
        from music_teacher_ai.database.sqlite import get_session
        from music_teacher_ai.database.models import Artist
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
        from music_teacher_ai.config.settings import EMBEDDING_MODEL, EMBEDDING_DIM
        model = SentenceTransformer(EMBEDDING_MODEL)
        vec = model.encode(["test"], normalize_embeddings=True)
        assert vec.shape == (1, EMBEDDING_DIM), f"Got {vec.shape}"

    # ------------------------------------------------------------------
    # 9. FAISS
    # ------------------------------------------------------------------
    with check("FAISS: index create / add / search"):
        import numpy as np
        import faiss
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
        update_env,
        read_env,
        mask,
        FIELD_MAP,
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


def main():
    app()
