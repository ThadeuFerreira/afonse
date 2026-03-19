"""
MCP (Model Context Protocol) server exposing Music Teacher AI tools to AI agents.

Run with:
    python -m music_teacher_ai.api.mcp_server
"""
import json
from typing import Any

from music_teacher_ai.search.keyword_search import search_songs
from music_teacher_ai.search.semantic_search import semantic_search
from music_teacher_ai.database.sqlite import get_session
from music_teacher_ai.database.models import Lyrics
from sqlmodel import select


TOOLS = [
    {
        "name": "search_songs",
        "description": (
            "Search songs in the local knowledge base by keyword, year, artist, or genre. "
            "Returns a list of matching songs with metadata."
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


def dispatch(tool_name: str, inputs: dict[str, Any]) -> Any:
    if tool_name == "search_songs":
        return search_songs(**inputs)

    if tool_name == "semantic_search":
        return semantic_search(inputs["query"], top_k=inputs.get("top_k", 10))

    if tool_name == "get_lyrics":
        with get_session() as session:
            lyr = session.exec(
                select(Lyrics).where(Lyrics.song_id == inputs["song_id"])
            ).first()
            if not lyr:
                return {"error": "Lyrics not found"}
            return {"song_id": lyr.song_id, "lyrics": lyr.lyrics_text}

    if tool_name == "find_similar_lyrics":
        from music_teacher_ai.search.similar_search import (
            find_similar_by_song,
            find_similar_by_title,
            find_similar_by_text,
        )
        top_k = inputs.get("top_k", 10)
        min_score = inputs.get("min_score", 0.0)
        try:
            if "song_id" in inputs:
                return find_similar_by_song(inputs["song_id"], top_k=top_k, min_score=min_score)
            elif "song_title" in inputs:
                return find_similar_by_title(
                    inputs["song_title"],
                    artist=inputs.get("artist"),
                    top_k=top_k,
                    min_score=min_score,
                )
            elif "text" in inputs:
                return find_similar_by_text(inputs["text"], top_k=top_k, min_score=min_score)
            else:
                return {"error": "Provide song_id, song_title, or text."}
        except (ValueError, FileNotFoundError) as exc:
            return {"error": str(exc)}

    if tool_name == "find_vocabulary_examples":
        results = []
        for word in inputs.get("words", []):
            hits = search_songs(
                word=word,
                year=inputs.get("year"),
                year_min=inputs.get("year_min"),
                year_max=inputs.get("year_max"),
                limit=inputs.get("limit", 10),
            )
            results.append({"word": word, "songs": hits})
        return results

    if tool_name == "create_playlist":
        import music_teacher_ai.playlists.manager as pm
        from music_teacher_ai.playlists.models import PlaylistQuery
        try:
            pq = PlaylistQuery(
                word=inputs.get("word"),
                year=inputs.get("year"),
                year_min=inputs.get("year_min"),
                year_max=inputs.get("year_max"),
                artist=inputs.get("artist"),
                genre=inputs.get("genre"),
                semantic_query=inputs.get("semantic_query"),
                similar_text=inputs.get("similar_text"),
                similar_song_id=inputs.get("similar_song_id"),
                limit=inputs.get("limit", 20),
            )
            playlist = pm.create(
                name=inputs["name"],
                description=inputs.get("description"),
                query=pq,
            )
            return playlist.model_dump()
        except (FileExistsError, ValueError) as exc:
            return {"error": str(exc)}

    if tool_name == "list_playlists":
        import music_teacher_ai.playlists.manager as pm
        return [p.model_dump() for p in pm.list_all()]

    if tool_name == "get_playlist":
        import music_teacher_ai.playlists.manager as pm
        try:
            return pm.get(inputs["playlist_id"]).model_dump()
        except FileNotFoundError as exc:
            return {"error": str(exc)}

    if tool_name == "export_playlist":
        import music_teacher_ai.playlists.manager as pm
        try:
            return pm.export_format(inputs["playlist_id"], inputs.get("format", "m3u"))
        except (FileNotFoundError, ValueError) as exc:
            return {"error": str(exc)}

    if tool_name == "get_config":
        from music_teacher_ai.config.credentials import current_status
        return current_status()

    if tool_name == "configure":
        from music_teacher_ai.config.credentials import (
            verify_admin_token,
            ALLOWED_KEYS,
            update_env,
            current_status,
        )
        if not verify_admin_token(inputs.get("admin_token", "")):
            return {"error": "Invalid admin_token"}
        credentials = inputs.get("credentials", {})
        if not isinstance(credentials, dict) or not credentials:
            return {"error": "credentials must be a non-empty object"}
        unknown = set(credentials) - ALLOWED_KEYS
        if unknown:
            return {
                "error": f"Unknown key(s): {sorted(unknown)}. Allowed: {sorted(ALLOWED_KEYS)}"
            }
        update_env(credentials)
        return {
            "updated": sorted(credentials.keys()),
            "status": current_status(),
        }

    return {"error": f"Unknown tool: {tool_name}"}


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
