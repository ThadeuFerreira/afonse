"""
MCP (Model Context Protocol) server exposing Music Teacher AI tools to AI agents.

Run with:
    python -m music_teacher_ai.api.mcp_server
"""
import json
from typing import Any, Callable

from music_teacher_ai.application.config_service import get_status as cfg_get_status
from music_teacher_ai.application.config_service import update_credentials as cfg_update_credentials
from music_teacher_ai.application.enrichment_service import EnrichRequest, run_enrichment
from music_teacher_ai.application.errors import ValidationError
from music_teacher_ai.application.playlist_service import (
    create_playlist as svc_create_playlist,
    export_playlist as svc_export_playlist,
    get_playlist as svc_get_playlist,
    list_playlists as svc_list_playlists,
)
from music_teacher_ai.application.search_service import SearchRequest, keyword_search_with_expansion
from music_teacher_ai.application.search_service import semantic_query as svc_semantic_query
from music_teacher_ai.search.keyword_search import search_songs
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.database.models import Lyrics
from sqlmodel import select


TOOLS = [
    {
        "name": "search_songs",
        "description": (
            "Search songs in the local knowledge base by keyword, year, artist, or genre. "
            "Returns {results: [...], database_expansion_triggered: bool}. "
            "When results are below the expansion threshold and genre/artist/year are provided, "
            "a background discovery job is started automatically to grow the database."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "word": {"type": "string", "description": "Keyword to search in lyrics"},
                "year": {"type": "integer", "description": "Exact release year"},
                "year_min": {"type": "integer", "description": "Minimum release year"},
                "year_max": {"type": "integer", "description": "Maximum release year"},
                "artist": {"type": "string", "description": "Artist name filter"},
                "genre": {"type": "string", "description": "Genre filter"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    },
    {
        "name": "process_candidates",
        "description": (
            "Process pending song candidates from the staging table. "
            "Inserts new songs into the main database and marks each candidate as "
            "processed or rejected. Optionally filter by query_origin."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query_origin": {
                    "type": "string",
                    "description": "Filter by origin query, e.g. 'genre:jazz' (optional)",
                },
            },
        },
    },
    {
        "name": "semantic_search",
        "description": (
            "Search songs using a natural language theme or concept. "
            "Examples: 'songs about friendship', 'songs about overcoming fear'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Semantic search query"},
                "top_k": {"type": "integer", "description": "Number of results (default 10)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_lyrics",
        "description": "Retrieve the full lyrics for a song by its database ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "integer", "description": "Song ID from search results"},
            },
            "required": ["song_id"],
        },
    },
    {
        "name": "find_similar_lyrics",
        "description": (
            "Find songs whose lyrics are semantically similar to a given song, song ID, or text fragment. "
            "Use song_id or song_title to find songs similar to a known track. "
            "Use text to find songs similar to a lyric fragment or theme description."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "song_id": {"type": "integer", "description": "Song ID to find similar songs for"},
                "song_title": {"type": "string", "description": "Song title to match (partial match supported)"},
                "artist": {"type": "string", "description": "Artist filter when using song_title"},
                "text": {"type": "string", "description": "Lyric fragment or theme, e.g. 'dreaming about freedom'"},
                "top_k": {"type": "integer", "description": "Number of results (default 10)"},
                "min_score": {"type": "number", "description": "Minimum similarity score 0.0–1.0 (default 0.0)"},
            },
        },
    },
    {
        "name": "find_vocabulary_examples",
        "description": (
            "Find songs that contain a specific word and optionally filter by year range. "
            "Useful for finding vocabulary in context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "words": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of words to search for",
                },
                "year": {"type": "integer"},
                "year_min": {"type": "integer"},
                "year_max": {"type": "integer"},
                "limit": {"type": "integer"},
            },
            "required": ["words"],
        },
    },
    {
        "name": "create_playlist",
        "description": (
            "Create a playlist from a search query and save it locally. "
            "Supports keyword, semantic, and similarity queries."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Playlist name"},
                "description": {"type": "string"},
                "word": {"type": "string", "description": "Keyword to search in lyrics"},
                "year": {"type": "integer"},
                "year_min": {"type": "integer"},
                "year_max": {"type": "integer"},
                "artist": {"type": "string"},
                "genre": {"type": "string"},
                "semantic_query": {"type": "string", "description": "Theme query e.g. 'songs about hope'"},
                "similar_text": {"type": "string", "description": "Text to find similar songs for"},
                "similar_song_id": {"type": "integer"},
                "limit": {"type": "integer", "description": "Max songs (default 20)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "list_playlists",
        "description": "List all saved playlists.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_playlist",
        "description": "Get a saved playlist by its slug ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string", "description": "Playlist slug"},
            },
            "required": ["playlist_id"],
        },
    },
    {
        "name": "export_playlist",
        "description": "Export a playlist as M3U, M3U8, or JSON text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "playlist_id": {"type": "string"},
                "format": {"type": "string", "description": "json, m3u, or m3u8 (default m3u)"},
            },
            "required": ["playlist_id"],
        },
    },
    {
        "name": "enrich_database",
        "description": (
            "Expand the song knowledge base by fetching candidates from external APIs. "
            "Provide at least one of genre, artist, or year. "
            "Runs metadata enrichment, lyrics download, vocabulary index, and embeddings "
            "on newly inserted songs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "genre": {"type": "string", "description": "Last.fm genre tag, e.g. 'jazz'"},
                "artist": {"type": "string", "description": "Artist name to fetch top tracks for"},
                "year": {"type": "integer", "description": "Release year to search"},
                "limit": {"type": "integer", "description": "Max new songs to insert (default 100, max 1000)"},
            },
        },
    },
    {
        "name": "get_config",
        "description": (
            "Return the current credential configuration status. "
            "Values are masked — this is safe to call without authentication."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "configure",
        "description": (
            "Set or update API credentials stored in .env. "
            "Requires the admin_token (found in .env as ADMIN_TOKEN or printed by "
            "'music-teacher config'). Only recognised credential keys are accepted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "admin_token": {
                    "type": "string",
                    "description": "ADMIN_TOKEN from .env — required to authorise credential changes",
                },
                "credentials": {
                    "type": "object",
                    "description": (
                        "Map of credential key → new value. "
                        "Allowed keys: GENIUS_ACCESS_TOKEN, SPOTIFY_CLIENT_ID, "
                        "SPOTIFY_CLIENT_SECRET, LASTFM_API_KEY, DATABASE_PATH, API_CACHE_DIR"
                    ),
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["admin_token", "credentials"],
        },
    },
]


def _handle_search_songs(inputs: dict[str, Any]) -> Any:
    return keyword_search_with_expansion(
        SearchRequest(
            word=inputs.get("word"),
            year=inputs.get("year"),
            year_min=inputs.get("year_min"),
            year_max=inputs.get("year_max"),
            artist=inputs.get("artist"),
            genre=inputs.get("genre"),
            limit=inputs.get("limit", 20),
        )
    )


def _handle_process_candidates(inputs: dict[str, Any]) -> Any:
    from music_teacher_ai.pipeline.expansion import process_candidates

    return process_candidates(query_origin=inputs.get("query_origin"))


def _handle_semantic_search(inputs: dict[str, Any]) -> Any:
    return svc_semantic_query(inputs["query"], top_k=inputs.get("top_k", 10))


def _handle_get_lyrics(inputs: dict[str, Any]) -> Any:
    with get_session() as session:
        lyr = session.exec(select(Lyrics).where(Lyrics.song_id == inputs["song_id"])).first()
        if not lyr:
            return {"error": "Lyrics not found"}
        return {"song_id": lyr.song_id, "lyrics": lyr.lyrics_text}


def _handle_find_similar_lyrics(inputs: dict[str, Any]) -> Any:
    from music_teacher_ai.search.similar_search import (
        find_similar_by_song,
        find_similar_by_text,
        find_similar_by_title,
    )

    top_k = inputs.get("top_k", 10)
    min_score = inputs.get("min_score", 0.0)
    if "song_id" in inputs:
        return find_similar_by_song(inputs["song_id"], top_k=top_k, min_score=min_score)
    if "song_title" in inputs:
        return find_similar_by_title(
            inputs["song_title"],
            artist=inputs.get("artist"),
            top_k=top_k,
            min_score=min_score,
        )
    if "text" in inputs:
        return find_similar_by_text(inputs["text"], top_k=top_k, min_score=min_score)
    return {"error": "Provide song_id, song_title, or text."}


def _handle_find_vocabulary_examples(inputs: dict[str, Any]) -> Any:
    result = []
    for word in inputs.get("words", []):
        result.append(
            {
                "word": word,
                "songs": search_songs(
                    word=word,
                    year=inputs.get("year"),
                    year_min=inputs.get("year_min"),
                    year_max=inputs.get("year_max"),
                    limit=inputs.get("limit", 10),
                ),
            }
        )
    return result


def _handle_create_playlist(inputs: dict[str, Any]) -> Any:
    return svc_create_playlist(inputs)


def _handle_list_playlists(_: dict[str, Any]) -> Any:
    return svc_list_playlists()


def _handle_get_playlist(inputs: dict[str, Any]) -> Any:
    return svc_get_playlist(inputs["playlist_id"])


def _handle_export_playlist(inputs: dict[str, Any]) -> Any:
    return svc_export_playlist(inputs["playlist_id"], inputs.get("format", "m3u"))


def _handle_enrich_database(inputs: dict[str, Any]) -> Any:
    return run_enrichment(
        EnrichRequest(
            genre=inputs.get("genre"),
            artist=inputs.get("artist"),
            year=inputs.get("year"),
            limit=inputs.get("limit", 100),
        )
    )


def _handle_get_config(_: dict[str, Any]) -> Any:
    return cfg_get_status()


def _handle_configure(inputs: dict[str, Any]) -> Any:
    from music_teacher_ai.config.credentials import verify_admin_token

    if not verify_admin_token(inputs.get("admin_token", "")):
        return {"error": "Invalid admin_token"}
    credentials = inputs.get("credentials", {})
    if not isinstance(credentials, dict):
        return {"error": "credentials must be an object"}
    return cfg_update_credentials(credentials)


_HANDLERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "search_songs": _handle_search_songs,
    "process_candidates": _handle_process_candidates,
    "semantic_search": _handle_semantic_search,
    "get_lyrics": _handle_get_lyrics,
    "find_similar_lyrics": _handle_find_similar_lyrics,
    "find_vocabulary_examples": _handle_find_vocabulary_examples,
    "create_playlist": _handle_create_playlist,
    "list_playlists": _handle_list_playlists,
    "get_playlist": _handle_get_playlist,
    "export_playlist": _handle_export_playlist,
    "enrich_database": _handle_enrich_database,
    "get_config": _handle_get_config,
    "configure": _handle_configure,
}


def dispatch(tool_name: str, inputs: dict[str, Any]) -> Any:
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        return handler(inputs)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    # Simple stdio-based MCP loop
    import sys

    print(json.dumps({"tools": TOOLS}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            tool_name = request.get("tool")
            inputs = request.get("inputs", {})
            result = dispatch(tool_name, inputs)
            print(json.dumps({"result": result}), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}), flush=True)
