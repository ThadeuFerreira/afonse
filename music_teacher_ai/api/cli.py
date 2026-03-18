from datetime import date
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from sqlmodel import select, func

from music_teacher_ai.database.sqlite import create_db, get_session
from music_teacher_ai.database.models import Song, Lyrics, Embedding, Chart, IngestionFailure

app = typer.Typer(help="Music Teacher AI – manage and query the local knowledge base.")
playlist_app = typer.Typer(help="Create and manage song playlists.")
app.add_typer(playlist_app, name="playlist")
console = Console()


@app.command()
def init(
    start: int = typer.Option(1960, help="First year to ingest from Billboard."),
    end: int = typer.Option(None, help="Last year to ingest (default: current year)."),
):
    """Initialize the knowledge base from scratch."""
    from music_teacher_ai.pipeline.charts_ingestion import ingest_charts
    from music_teacher_ai.pipeline.metadata_enrichment import enrich_metadata
    from music_teacher_ai.pipeline.lyrics_downloader import download_lyrics
    from music_teacher_ai.pipeline.vocabulary_indexer import build_vocabulary_index
    from music_teacher_ai.pipeline.embedding_pipeline import generate_embeddings

    console.print("[bold green]Creating database schema...[/bold green]")
    create_db()

    console.print("[bold green]Step 1/5 – Fetching Billboard charts...[/bold green]")
    ingest_charts(start=start, end=end or date.today().year)

    console.print("[bold green]Step 2/5 – Enriching metadata via Spotify...[/bold green]")
    enrich_metadata()

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
    limit: int = typer.Option(20),
):
    """Search the knowledge base."""
    if query:
        from music_teacher_ai.search.semantic_search import semantic_search
        results = semantic_search(query, top_k=limit)
    else:
        from music_teacher_ai.search.keyword_search import search_songs
        results = search_songs(
            word=word, year=year, year_min=year_min,
            year_max=year_max, artist=artist, limit=limit,
        )

    if not results:
        console.print("[yellow]No results found.[/yellow]")
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
            from music_teacher_ai.core.spotify_client import get_client
            sp = get_client()
            r = sp.search(q="Imagine", type="track", limit=1)
            assert r["tracks"]["items"], "No results"

        with check("Spotify: search_track() for 'Imagine'"):
            from music_teacher_ai.core.spotify_client import search_track
            meta = search_track("Imagine", "John Lennon")
            assert meta is not None, "Returned None"
            assert meta.spotify_id

        with check("Spotify: audio features populated"):
            from music_teacher_ai.core.spotify_client import search_track
            meta = search_track("Imagine", "John Lennon")
            assert meta and meta.tempo and meta.energy is not None

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
    # 5. Database
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
    # 6. Embedding model
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
    # 7. FAISS
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
    year: Optional[int] = typer.Option(None),
    year_min: Optional[int] = typer.Option(None),
    year_max: Optional[int] = typer.Option(None),
    artist: Optional[str] = typer.Option(None),
    genre: Optional[str] = typer.Option(None),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="Semantic/theme query"),
    similar_text: Optional[str] = typer.Option(None, "--similar-text", help="Text to find similar songs for"),
    similar_song_id: Optional[int] = typer.Option(None, "--similar-song-id"),
    limit: int = typer.Option(20, help="Max songs in playlist"),
):
    """Create a playlist from a search query."""
    from music_teacher_ai.playlists.models import PlaylistQuery
    import music_teacher_ai.playlists.manager as pm

    pq = PlaylistQuery(
        word=word,
        year=year,
        year_min=year_min,
        year_max=year_max,
        artist=artist,
        genre=genre,
        semantic_query=query,
        similar_text=similar_text,
        similar_song_id=similar_song_id,
        limit=limit,
    )

    try:
        playlist = pm.create(name=name, description=description, query=pq)
    except FileExistsError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    _print_playlist(playlist)
    console.print(f"[green]Saved to data/playlists/{playlist.id}/[/green]")


@playlist_app.command("show")
def playlist_show(
    playlist_id: str = typer.Argument(..., help="Playlist slug (from 'playlist list')"),
):
    """Display a saved playlist."""
    import music_teacher_ai.playlists.manager as pm
    try:
        playlist = pm.get(playlist_id)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    _print_playlist(playlist)


@playlist_app.command("list")
def playlist_list():
    """List all saved playlists."""
    import music_teacher_ai.playlists.manager as pm

    playlists = pm.list_all()
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
    import music_teacher_ai.playlists.manager as pm

    if not yes:
        typer.confirm(f"Delete playlist '{playlist_id}'?", abort=True)
    try:
        pm.delete(playlist_id)
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
    import music_teacher_ai.playlists.manager as pm

    try:
        content = pm.export_format(playlist_id, fmt)
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
    import music_teacher_ai.playlists.manager as pm

    try:
        playlist = pm.refresh(playlist_id)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    _print_playlist(playlist)
    console.print(f"[green]Refreshed '{playlist_id}' — {len(playlist.songs)} songs.[/green]")


def main():
    app()
