from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from music_teacher_ai.application.enrichment_service import EnrichRequest as EnrichServiceRequest
from music_teacher_ai.application.enrichment_service import run_enrichment
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
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.database.models import Song, Artist, Lyrics
from music_teacher_ai.playlists.models import PlaylistQuery
from music_teacher_ai.search.keyword_search import search_songs
from sqlmodel import select

_bearer = HTTPBearer()
_LOCALHOST = {"127.0.0.1", "::1", "localhost"}


def _require_admin(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> None:
    """FastAPI dependency: localhost-only + valid ADMIN_TOKEN Bearer token."""
    host = request.client.host if request.client else ""
    if host not in _LOCALHOST:
        raise HTTPException(status_code=403, detail="Config endpoint only accessible from localhost")
    from music_teacher_ai.config.credentials import verify_admin_token
    if not verify_admin_token(credentials.credentials):
        raise HTTPException(status_code=401, detail="Invalid admin token")

app = FastAPI(
    title="Music Teacher AI",
    description="API for discovering songs suitable for English language learning.",
    version="0.1.0",
)


class QueryRequest(BaseModel):
    query: str
    top_k: int = 10


class SimilarTextRequest(BaseModel):
    text: str
    top_k: int = 10
    min_score: float = 0.0


class EnrichRequest(BaseModel):
    genre: Optional[str] = None
    artist: Optional[str] = None
    year: Optional[int] = None
    limit: int = 100


@app.get("/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

@app.get("/config")
def get_config():
    """Return current credential status — values are masked, no auth required."""
    from music_teacher_ai.config.credentials import current_status
    return current_status()


class ConfigUpdateRequest(BaseModel):
    """Map of credential key → new value. Only recognised keys are accepted."""
    credentials: dict[str, str]


@app.post("/config", dependencies=[Security(_require_admin)])
def post_config(req: ConfigUpdateRequest):
    """
    Update credentials stored in .env.

    Requires:
    - Request from 127.0.0.1 / ::1 (localhost only)
    - Authorization: Bearer <ADMIN_TOKEN> header

    Only keys listed in ALLOWED_KEYS are accepted; unknown keys are rejected
    with 400 so callers cannot write arbitrary values into .env.
    """
    from music_teacher_ai.application.config_service import update_credentials

    try:
        return update_credentials(req.credentials)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/status")
def status():
    from sqlmodel import func
    from music_teacher_ai.database.models import Embedding, Lyrics, VocabularyIndex
    with get_session() as session:
        return {
            "songs": session.exec(select(func.count()).select_from(Song)).one(),
            "lyrics": session.exec(select(func.count()).select_from(Lyrics)).one(),
            "embeddings": session.exec(select(func.count()).select_from(Embedding)).one(),
            "vocabulary_entries": session.exec(select(func.count()).select_from(VocabularyIndex)).one(),
        }


@app.get("/songs")
def list_songs(
    year: Optional[int] = None,
    artist: Optional[str] = None,
    genre: Optional[str] = None,
    limit: int = Query(20, le=100),
):
    return search_songs(year=year, artist=artist, genre=genre, limit=limit)


@app.get("/songs/{song_id}")
def get_song(song_id: int):
    with get_session() as session:
        song = session.get(Song, song_id)
        if not song:
            raise HTTPException(status_code=404, detail="Song not found")
        artist = session.get(Artist, song.artist_id)
        return {
            **song.dict(),
            "artist_name": artist.name if artist else None,
        }


@app.get("/lyrics/{song_id}")
def get_lyrics(song_id: int):
    with get_session() as session:
        lyr = session.exec(select(Lyrics).where(Lyrics.song_id == song_id)).first()
        if not lyr:
            raise HTTPException(status_code=404, detail="Lyrics not found")
        return lyr.dict()


@app.get("/search")
def keyword_search(
    word: Optional[str] = None,
    year: Optional[int] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
    artist: Optional[str] = None,
    genre: Optional[str] = None,
    limit: int = Query(20, le=100),
):
    return keyword_search_with_expansion(
        SearchRequest(
        word=word, year=year, year_min=year_min,
        year_max=year_max, artist=artist, genre=genre, limit=limit,
        )
    )


@app.post("/query")
def semantic_query(req: QueryRequest):
    try:
        return svc_semantic_query(req.query, top_k=req.top_k)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/similar/song/{song_id}")
def similar_by_song(
    song_id: int,
    top_k: int = Query(10, le=50),
    min_score: float = Query(0.0),
):
    from music_teacher_ai.search.similar_search import find_similar_by_song
    try:
        return find_similar_by_song(song_id, top_k=top_k, min_score=min_score)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/similar/text")
def similar_by_text(req: SimilarTextRequest):
    from music_teacher_ai.search.similar_search import find_similar_by_text
    try:
        return find_similar_by_text(req.text, top_k=req.top_k, min_score=req.min_score)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

@app.post("/enrich")
def enrich(req: EnrichRequest):
    """
    Expand the knowledge base with songs fetched by genre, artist, or year.

    At least one of genre, artist, or year must be provided.
    Runs the full pipeline (metadata → lyrics → vocab → embeddings) on new songs.
    """
    try:
        return run_enrichment(
            EnrichServiceRequest(
                genre=req.genre,
                artist=req.artist,
                year=req.year,
                limit=req.limit,
            )
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ---------------------------------------------------------------------------
# Playlists
# ---------------------------------------------------------------------------

class PlaylistCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    query: PlaylistQuery


@app.post("/playlists", status_code=201)
def create_playlist(req: PlaylistCreateRequest):
    try:
        playlist = svc_create_playlist(
            {
                "name": req.name,
                "description": req.description,
                "word": req.query.word,
                "year": req.query.year,
                "year_min": req.query.year_min,
                "year_max": req.query.year_max,
                "artist": req.query.artist,
                "genre": req.query.genre,
                "semantic_query": req.query.semantic_query,
                "similar_text": req.query.similar_text,
                "similar_song_id": req.query.similar_song_id,
                "limit": req.query.limit,
            }
        )
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return playlist


@app.get("/playlists")
def list_playlists():
    return svc_list_playlists()


@app.get("/playlists/{playlist_id}")
def get_playlist(playlist_id: str):
    try:
        return svc_get_playlist(playlist_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(playlist_id: str):
    try:
        svc_delete_playlist(playlist_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/playlists/{playlist_id}/refresh")
def refresh_playlist(playlist_id: str):
    try:
        return svc_refresh_playlist(playlist_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


_CONTENT_TYPES = {
    "json": "application/json",
    "m3u": "audio/x-mpegurl",
    "m3u8": "application/x-mpegURL",
}

@app.get("/playlists/{playlist_id}/export")
def export_playlist(
    playlist_id: str,
    fmt: str = Query("m3u", description="Export format: json, m3u, m3u8"),
):
    try:
        content = svc_export_playlist(playlist_id, fmt)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    media_type = _CONTENT_TYPES.get(fmt.lower(), "text/plain")
    return Response(content=content, media_type=media_type)
