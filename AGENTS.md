# Music Teacher AI – Agent Guide

This document describes the project for AI agents (e.g. OpenClaw) interacting with this codebase or the running system.

---

## What This System Does

Music Teacher AI is a **local knowledge base of song lyrics and metadata** designed to help English teachers find songs suitable for language learning.

It bootstraps from a built-in seed of ~120 well-known songs, downloads lyrics from Genius, and builds a local vocabulary index and vector embeddings. The catalog can be expanded on demand by artist via Last.fm / MusicBrainz discovery. It exposes data through a CLI, REST API (with a mobile web UI at `/web`), and MCP interface. Education endpoints transform lyrics into classroom-ready artifacts (gap-fill exercises, CEFR vocabulary, phrasal verb detection, full lesson bundles).

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
Returns an object:

- `results` – array of songs
- `database_expansion_triggered` – boolean indicating whether background expansion was triggered

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

### Web UI

Served at `http://localhost:8000/web`. Static mobile-first HTML/CSS/JS (no frameworks). Pages: Home, Search, Lyrics, Playlist, Exercise. Communicates with the REST API via native `fetch`.

### REST API

Base URL (default): `http://localhost:8000`

Key endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/search/simple?q=adele&limit=50` | Fast local title/artist ILIKE search (web UI default) |
| GET | `/search?word=dream&year=1995` | Keyword search with optional expansion trigger |
| POST | `/query` | Semantic search (`{"query": "..."}`) |
| GET | `/similar/song/{id}` | Similar songs by ID |
| POST | `/similar/text` | Similar songs by text fragment |
| GET | `/education/exercise/{id}?num_blanks=10` | Numbered fill-in-the-blank exercise (`_(N)_` format) |
| GET | `/education/vocabulary/{id}` | Vocabulary (CEFR) analysis |
| GET | `/education/phrasal-verbs/{id}` | Phrasal verb detection |
| POST | `/education/lesson` | Composite lesson payload |
| POST | `/exercise/gap` | Gap-fill exercise — returns `text_with_gaps`, `answer_key`, saved .txt |
| POST | `/playlists` | Create a playlist |
| GET | `/playlists` | List all playlists |
| GET | `/playlists/{id}` | Get a playlist |
| DELETE | `/playlists/{id}` | Delete a playlist |
| POST | `/playlists/{id}/refresh` | Re-run stored query |
| GET | `/playlists/{id}/export?fmt=m3u` | Export playlist |
| GET | `/config` | Credential status (masked) |
| POST | `/config` | Update credentials (admin token required) |
| GET | `/songs/{id}` | Song metadata |
| GET | `/lyrics/{id}` | Song lyrics |
| GET | `/songs` | List/filter songs |

**`POST /exercise/gap` body:** `{ "song_id": 1, "mode": "random", "level": 20 }` — `level` is a percentage (1–100); `mode` can also be `"manual"` with a `"words"` list.

---

## Database Schema (Summary)

| Table | Key Fields |
|-------|------------|
| `song` | id, spotify_id, title, artist_id, release_year, genre, popularity, metadata_source |
| `artist` | id, name, spotify_id, genres (JSON) |
| `album` | id, name, artist_id, release_year |
| `lyrics` | song_id, lyrics_text, word_count, unique_words |
| `chart` | song_id, chart_name, rank, date |
| `vocabularyindex` | word, song_id |
| `embedding` | song_id, embedding_vector (float32 bytes) |
| `ingestionfailure` | song_id, stage, error_message, retry_count |
| `songcandidate` | title, artist, year, source_api, query_origin, status |
| `backgroundjob` | job_type, query_origin, status, created_at, updated_at |

**`song.metadata_source` values:**

| Value | Meaning |
|-------|---------|
| `NULL` | Not yet enriched |
| `"lyrics_only"` | Seeded song — lyrics only, no external metadata enrichment needed |
| `"demo"` | Auto-loaded demo song with hardcoded lyrics (replaced on `init` or `config`) |
| `"spotify"` | Enriched via Spotify |
| `"musicbrainz"` | Enriched via MusicBrainz + Last.fm |
| `"failed"` | All enrichment sources returned no result |

---

## Data Coverage

- Built-in seed of ~120 well-known English songs (`music_teacher_ai/ingestion/songs_seed.json`)
- Expandable catalog via artist discovery (Last.fm / MusicBrainz)
- Lyrics from Genius (required credential)
- Optional: Spotify audio features, Last.fm genre tags / play counts

---

## CLI Notes (Current Behavior)

- `music-teacher init` initializes from the built-in seed: seed → lyrics → vocabulary → embeddings. No Billboard, no Spotify, no MusicBrainz in the init path.
- `music-teacher update "<artist>"` runs synchronous expansion for an artist (Last.fm / MusicBrainz), then downloads lyrics, rebuilds vocabulary index and embeddings.
- `music-teacher config` — at the end, if `GENIUS_ACCESS_TOKEN` is newly set and demo songs exist in the DB, automatically replaces hardcoded demo lyrics with real Genius downloads.
- `music-teacher inspect songs [--limit N] [--fix]` validates title/artist/lyrics and can delete invalid records.
- `music-teacher repair song <id>` re-fetches metadata and lyrics for a specific record with validation safeguards.

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

```
SPOTIFY_CLIENT_ID       # optional – full metadata + audio features (requires Premium)
SPOTIFY_CLIENT_SECRET   # optional
GENIUS_ACCESS_TOKEN     # required for lyrics
LASTFM_API_KEY          # optional – genre tags and play counts (free key)
DATABASE_PATH           # default: data/music.db
FAISS_INDEX_PATH        # default: data/embeddings.index
PLAYLISTS_DIR           # default: data/playlists
```

Metadata source priority when credentials are absent:
1. Spotify (title, artist, album, year, genres, audio features)
2. MusicBrainz (title, artist, album, year, duration — no key required)
3. Last.fm supplements MusicBrainz with genre tags and play counts
