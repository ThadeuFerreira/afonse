from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Response
from pydantic import BaseModel

from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.database.models import Song, Artist, Lyrics
from music_teacher_ai.playlists.models import PlaylistQuery
from music_teacher_ai.search.keyword_search import search_songs
from music_teacher_ai.search.semantic_search import semantic_search
from sqlmodel import select

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


@app.get("/health")
def health():
    return {"status": "ok"}


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
    return search_songs(
        word=word, year=year, year_min=year_min,
        year_max=year_max, artist=artist, genre=genre, limit=limit,
    )


@app.post("/query")
def semantic_query(req: QueryRequest):
    try:
        return semantic_search(req.query, top_k=req.top_k)
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
# Playlists
# ---------------------------------------------------------------------------

class PlaylistCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    query: PlaylistQuery


@app.post("/playlists", status_code=201)
def create_playlist(req: PlaylistCreateRequest):
    import music_teacher_ai.playlists.manager as pm
    try:
        playlist = pm.create(name=req.name, description=req.description, query=req.query)
    except FileExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return playlist.model_dump()


@app.get("/playlists")
def list_playlists():
    import music_teacher_ai.playlists.manager as pm
    return [p.model_dump() for p in pm.list_all()]


@app.get("/playlists/{playlist_id}")
def get_playlist(playlist_id: str):
    import music_teacher_ai.playlists.manager as pm
    try:
        return pm.get(playlist_id).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(playlist_id: str):
    import music_teacher_ai.playlists.manager as pm
    try:
        pm.delete(playlist_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/playlists/{playlist_id}/refresh")
def refresh_playlist(playlist_id: str):
    import music_teacher_ai.playlists.manager as pm
    try:
        return pm.refresh(playlist_id).model_dump()
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
    import music_teacher_ai.playlists.manager as pm
    try:
        content = pm.export_format(playlist_id, fmt)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    media_type = _CONTENT_TYPES.get(fmt.lower(), "text/plain")
    return Response(content=content, media_type=media_type)
