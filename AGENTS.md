# Music Teacher AI – Agent Guide

This document describes the project for AI agents (e.g. OpenClaw) interacting with this codebase or the running system.

---

## What This System Does

Music Teacher AI is a **local knowledge base of song lyrics and metadata** designed to help English teachers find songs suitable for language learning.

It ingests data from Spotify, Billboard, and Genius into a local SQLite database, then exposes that data through a CLI, REST API, and MCP interface.

---

## Available Interfaces

### MCP (Model Context Protocol)

The preferred interface for AI agents.

Start the MCP server:

```
python -m music_teacher_ai.api.mcp_server
```

The server communicates via stdin/stdout using newline-delimited JSON.

**Tool discovery:** On startup, the server emits a JSON object:

```json
{"tools": [...]}
```

**Calling a tool:**

Send a JSON line:

```json
{"tool": "search_songs", "inputs": {"word": "dream", "year_min": 1990, "year_max": 1999}}
```

Response:

```json
{"result": [...]}
```

---

### Available MCP Tools

#### search_songs

Search by keyword, year, artist, or genre.

Input fields (all optional):

- `word` – keyword to find in lyrics
- `year` – exact release year
- `year_min` / `year_max` – year range
- `artist` – artist name filter
- `genre` – genre filter
- `limit` – max results (default 20)

#### semantic_search

Search by theme or concept using vector similarity.

Input fields:

- `query` (required) – e.g. `"songs about losing hope"`
- `top_k` – number of results (default 10)

#### get_lyrics

Retrieve full lyrics for a song.

Input fields:

- `song_id` (required) – integer ID from search results

#### find_similar_lyrics

Find songs whose lyrics are semantically similar to a given song, song title, or text fragment.

Input fields (provide one of):

- `song_id` – integer ID of the reference song
- `song_title` – title string (partial match); combine with `artist` to disambiguate
- `text` – lyric fragment or theme description, e.g. `"dreaming about a better world"`

Optional:

- `top_k` – number of results (default 10)
- `min_score` – minimum similarity threshold 0.0–1.0 (default 0.0)

#### create_playlist

Create a playlist from a search query and save it locally. Returns the full playlist object.

Input fields:

- `name` (required) – playlist name
- `description` – optional
- `word` / `year` / `year_min` / `year_max` / `artist` / `genre` – keyword filters
- `semantic_query` – theme query, e.g. `"songs about hope"`
- `similar_text` – text to find similar songs for
- `similar_song_id` – song ID to find similar songs for
- `limit` – max songs (default 20)

#### list_playlists

List all saved playlists. Returns array of playlist objects.

Input: none.

#### get_playlist

Get a saved playlist by slug.

Input fields:

- `playlist_id` (required) – slug from `list_playlists`

#### export_playlist

Export a playlist as text in M3U, M3U8, or JSON.

Input fields:

- `playlist_id` (required)
- `format` – `json`, `m3u`, or `m3u8` (default `m3u`)

#### find_vocabulary_examples

Find songs containing specific words.

Input fields:

- `words` (required) – list of strings
- `year`, `year_min`, `year_max`, `limit` – optional filters

---

### REST API

Base URL (default): `http://localhost:8000`

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/search?word=dream&year=1995` | Keyword search |
| POST | `/query` | Semantic search (`{"query": "..."}`) |
| GET | `/similar/song/{id}` | Similar songs by ID |
| POST | `/similar/text` | Similar songs by text fragment |
| POST | `/playlists` | Create a playlist |
| GET | `/playlists` | List all playlists |
| GET | `/playlists/{id}` | Get a playlist |
| DELETE | `/playlists/{id}` | Delete a playlist |
| POST | `/playlists/{id}/refresh` | Re-run stored query |
| GET | `/playlists/{id}/export?fmt=m3u` | Export playlist |
| GET | `/songs/{id}` | Song metadata |
| GET | `/lyrics/{id}` | Song lyrics |
| GET | `/songs` | List/filter songs |

---

## Database Schema (Summary)

| Table | Key Fields |
|-------|------------|
| `song` | id, spotify_id, title, artist_id, release_year, genre, popularity |
| `artist` | id, name, spotify_id, genres (JSON) |
| `album` | id, name, artist_id, release_year |
| `lyrics` | song_id, lyrics_text, word_count, unique_words |
| `chart` | song_id, chart_name, rank, date |
| `vocabularyindex` | word, song_id |
| `embedding` | song_id, embedding_vector (float32 bytes) |
| `ingestionfailure` | song_id, stage, error_message, retry_count |

---

## Data Coverage

- Billboard Hot 100 from 1960 to present
- ~6500 songs
- Metadata from Spotify (tempo, valence, energy, danceability, genres)
- Lyrics from Genius

---

## Query Examples

```json
{"tool": "search_songs", "inputs": {"word": "freedom", "year_min": 1960, "year_max": 1980}}
```

```json
{"tool": "semantic_search", "inputs": {"query": "songs about growing up and leaving home"}}
```

```json
{"tool": "find_vocabulary_examples", "inputs": {"words": ["dream", "hope"], "year_min": 1990, "year_max": 1999}}
```

---

## Environment Variables

Required:

```
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
GENIUS_ACCESS_TOKEN
```

Optional:

```
DATABASE_PATH   (default: data/music.db)
FAISS_INDEX_PATH (default: data/embeddings.index)
```
