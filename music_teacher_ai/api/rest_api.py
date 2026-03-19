from pathlib import Path
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
    from music_teacher_ai.config.settings import DATABASE_PATH
    from sqlmodel import func
    from music_teacher_ai.database.models import Artist, Embedding, Lyrics, VocabularyIndex

    db_size_bytes = DATABASE_PATH.stat().st_size if DATABASE_PATH.exists() else 0
    with get_session() as session:
        return {
            "database_file_size_bytes": db_size_bytes,
            "songs": session.exec(select(func.count()).select_from(Song)).one(),
            "lyrics": session.exec(select(func.count()).select_from(Lyrics)).one(),
            "embeddings": session.exec(select(func.count()).select_from(Embedding)).one(),
            "vocabulary_entries": session.exec(select(func.count()).select_from(VocabularyIndex)).one(),
            "songs_with_artists": session.exec(
                select(func.count())
                .select_from(Song)
                .join(Artist, Song.artist_id == Artist.id)
            ).one(),
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
                "song": req.query.song,
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


# ---------------------------------------------------------------------------
# Education endpoints
# ---------------------------------------------------------------------------

def _get_lyrics_text(song_id: int) -> str:
    """Fetch lyrics text for a song or raise 404."""
    with get_session() as session:
        lyr = session.exec(select(Lyrics).where(Lyrics.song_id == song_id)).first()
        if not lyr:
            raise HTTPException(status_code=404, detail="Lyrics not found for this song")
        return lyr.lyrics_text


def _get_song_meta(song_id: int) -> tuple[str, str]:
    """Return (title, artist_name) for a song or raise 404."""
    with get_session() as session:
        song = session.get(Song, song_id)
        if not song:
            raise HTTPException(status_code=404, detail="Song not found")
        artist = session.get(Artist, song.artist_id)
        return song.title, (artist.name if artist else "")


@app.get("/education/exercise/{song_id}")
def education_exercise(
    song_id: int,
    num_blanks: int = Query(10, ge=1, le=30),
    min_word_length: int = Query(4, ge=2),
):
    """Generate a fill-in-the-blank exercise from a song's lyrics."""
    from music_teacher_ai.education_services.exercises.fill_in_blank import generate

    title, artist_name = _get_song_meta(song_id)
    lyrics = _get_lyrics_text(song_id)
    ex = generate(lyrics, song_title=title, artist=artist_name,
                  num_blanks=num_blanks, min_word_length=min_word_length)
    return {
        "song_id": song_id,
        "song_title": ex.song_title,
        "artist": ex.artist,
        "text_with_blanks": ex.text_with_blanks,
        "answer_key": ex.answer_key,
        "blanked_count": ex.blanked_count,
        "total_words": ex.total_words,
        "blanks": [{"number": b.number, "word": b.word} for b in ex.blanks],
    }


@app.get("/education/vocabulary/{song_id}")
def education_vocabulary(
    song_id: int,
    min_word_length: int = Query(3, ge=1),
):
    """Analyse vocabulary difficulty (CEFR levels) in a song's lyrics."""
    from music_teacher_ai.education_services.vocabulary.analyzer import analyze

    title, artist_name = _get_song_meta(song_id)
    lyrics = _get_lyrics_text(song_id)
    result = analyze(lyrics, song_title=title, artist=artist_name,
                     min_word_length=min_word_length)
    return {
        "song_id": song_id,
        "song_title": result.song_title,
        "artist": result.artist,
        "total_unique_words": result.total_unique_words,
        "dominant_level": result.dominant_level,
        "level_counts": result.level_counts,
        "level_percentages": result.level_percentages,
        "words_by_level": {
            level: [{"word": e.word, "occurrences": e.occurrences} for e in entries]
            for level, entries in result.words_by_level.items()
            if entries
        },
    }


@app.get("/education/phrasal-verbs/{song_id}")
def education_phrasal_verbs(song_id: int):
    """Detect phrasal verbs in a song's lyrics."""
    from music_teacher_ai.education_services.phrase_detection.phrasal_verbs import detect

    title, artist_name = _get_song_meta(song_id)
    lyrics = _get_lyrics_text(song_id)
    report = detect(lyrics, song_title=title, artist=artist_name)
    return {
        "song_id": song_id,
        "song_title": report.song_title,
        "artist": report.artist,
        "total_matches": report.total_matches,
        "unique_phrasal_verbs": report.unique_phrasal_verbs,
        "matches": [
            {
                "phrasal_verb": m.phrasal_verb,
                "matched_text": m.matched_text,
                "line_number": m.line_number,
                "line_text": m.line_text,
            }
            for m in report.matches
        ],
    }


class GapFillRequest(BaseModel):
    song_id: int
    mode: str = "random"            # "random" | "manual"
    level: int = 20                 # percentage for random mode (1–100)
    words: Optional[list[str]] = None  # word list for manual mode
    output: Optional[str] = None    # filename override


@app.post("/exercise/gap")
def exercise_gap(req: GapFillRequest):
    """
    Generate a listening fill-the-gaps exercise and save it as a .txt file.

    Returns the filename that was written to data/exercises/.
    """
    from music_teacher_ai.config.settings import EXERCISES_DIR
    from music_teacher_ai.education_services.exercises.gap_fill import (
        export,
        generate_manual,
        generate_random,
    )

    title, artist_name = _get_song_meta(req.song_id)
    lyrics = _get_lyrics_text(req.song_id)

    if req.mode == "manual":
        if not req.words:
            raise HTTPException(status_code=422, detail="words list required for manual mode")
        ex = generate_manual(lyrics, req.words, song_title=title, artist=artist_name)
    else:
        ex = generate_random(lyrics, song_title=title, artist=artist_name, level=req.level)

    # Sanitize the caller-supplied filename: keep only the basename and reject
    # names that contain path separators or attempt directory traversal.
    safe_filename: Optional[str] = None
    if req.output is not None:
        safe_filename = Path(req.output).name   # strips any leading directory parts
        resolved = (EXERCISES_DIR / safe_filename).resolve()
        if not str(resolved).startswith(str(EXERCISES_DIR.resolve())):
            raise HTTPException(status_code=400, detail="Invalid output filename")

    out_path = export(ex, EXERCISES_DIR, safe_filename)
    return {"file": out_path.name, "path": str(out_path)}


class LessonRequest(BaseModel):
    song_id: int
    num_blanks: int = 10
    min_word_length: int = 4


@app.post("/education/lesson")
def education_lesson(req: LessonRequest):
    """Build a complete lesson (exercise + vocabulary + phrasal verbs) for a song."""
    from music_teacher_ai.education_services.lesson_builder.builder import build_lesson

    title, artist_name = _get_song_meta(req.song_id)
    lyrics = _get_lyrics_text(req.song_id)
    lesson = build_lesson(
        song_id=req.song_id,
        lyrics=lyrics,
        song_title=title,
        artist=artist_name,
        num_blanks=req.num_blanks,
        min_word_length=req.min_word_length,
    )
    return lesson.to_dict()


# ---------------------------------------------------------------------------
# Playlist export helpers
# ---------------------------------------------------------------------------

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
