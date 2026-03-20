# Music Teacher AI

A local knowledge base of song lyrics and metadata to help English teachers find songs suitable for language learning.

## What It Does

- Bootstraps from a built-in curated song seed (fast local startup)
- Expands the catalog on demand (for example by artist) and enriches metadata
- Stores lyrics, metadata, and vocabulary indexes locally in SQLite
- Supports keyword search, semantic search, and natural language queries
- Provides education-oriented outputs (fill-in-the-blank, vocabulary levels, phrasal verbs, lesson bundles)
- Exposes a CLI, REST API, and MCP interface for AI agents

---

## Setup

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Install with uv

```bash
uv sync
```

If you need the CLI entrypoint (`music-teacher`) available as a shell command, install the project into the environment as well:

```bash
uv pip install -e ".[dev]"
```

### Install with pip

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Configure Cursor to use `.venv` (recommended)

- Select the interpreter: `Ctrl+Shift+P` → **Python: Select Interpreter** → choose `./.venv/bin/python`
- (Optional) Add a workspace setting in `.vscode/settings.json`:

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.terminal.activateEnvironment": true
}
```

### Configure credentials

```bash
cp .env.example .env
# Edit .env with your Spotify and Genius API keys
```

Spotify credentials: https://developer.spotify.com/dashboard

Genius API token: https://genius.com/api-clients

---

## Initialize the Knowledge Base

```bash
music-teacher init
```

This runs the bootstrap pipeline:

1. Creates the database schema
2. Seeds ~120 well-known songs from the built-in `songs_seed.json`
3. Downloads lyrics from Genius for every seeded song
4. Builds a vocabulary index (word → songs)
5. Generates sentence embeddings for semantic search

No Billboard, Spotify, or MusicBrainz calls during init — only Genius is required.

Estimated time: a few minutes for the default seed (depends on Genius API latency).

> **First run without credentials?** The app auto-loads 10 demo songs with hardcoded lyrics so every command works immediately. Run `music-teacher config` to set your Genius token, then re-run `music-teacher init` to replace demo lyrics with real downloads.

---

## Commands

```bash
music-teacher init                             # Bootstrap from built-in seed
music-teacher config                           # Set/update API credentials
music-teacher config --show                    # Print current credential status
music-teacher status                           # Show database stats
music-teacher migrate-db                       # Apply explicit DB migrations/indexes
music-teacher search --word dream              # Find songs containing "dream"
music-teacher search --query "songs about freedom"  # Semantic search
music-teacher search --word love --year-min 1970 --year-max 1980
music-teacher update "Nina Simone"             # Add an artist and download their lyrics
music-teacher inspect songs                    # Validate suspicious/corrupt song data
music-teacher inspect songs --fix              # Delete invalid rows automatically
music-teacher repair song 262                  # Re-fetch metadata + lyrics for one song
music-teacher retry-failed                     # Retry failed ingestion steps
music-teacher rebuild-embeddings               # Rebuild FAISS index
```

### `update` command

```bash
music-teacher update "<artist>"
```

Adds an artist's songs using the Last.fm / MusicBrainz discovery pipeline, then downloads lyrics and refreshes the vocabulary index and embeddings. Runs synchronously (blocks until complete).

### Troubleshooting: `music-teacher` command not found

If you see `zsh: command not found: music-teacher`, it usually means the environment isn’t active, or the project wasn’t installed into it.

```bash
source .venv/bin/activate
python -m pip install -e .
music-teacher status
```

If you’re using `uv`, you can also run through the environment explicitly:

```bash
uv run music-teacher status
```

---

## Web Interface

A mobile-first web UI is served automatically when the REST server is running:

```
http://localhost:8000/web
```

Pages: **Home** (search bar + recent searches), **Search** (title/artist), **Lyrics** (full text + exercise/playlist buttons), **Playlist** (cart-based, save or export M3U), **Exercise** (gap-fill, difficulty 10–40%, download .txt).

No external JS frameworks — plain HTML/CSS/JS with native `fetch`.

---

## REST API

Start the server:

```bash
music-teacher serve
# or directly:
uvicorn music_teacher_ai.api.rest_api:app --reload
```

Key endpoints:

```
GET  /search?word=dream&year=1995
     -> {"results":[...], "database_expansion_triggered":bool}
GET  /search/simple?q=adele&limit=50
     -> fast local title/artist ILIKE search (used by the web UI)
POST /query   {"query": "songs about hope"}
GET  /songs/{id}
GET  /lyrics/{id}
GET  /education/exercise/{id}?num_blanks=10
     -> numbered fill-in-the-blank exercise (_(1)_ format)
GET  /education/vocabulary/{id}
GET  /education/phrasal-verbs/{id}
POST /education/lesson
POST /exercise/gap
     -> {"song_id":1,"mode":"random","level":20}
     -> returns text_with_gaps, answer_key, blanked_count, total_words + saved file
GET  /config
POST /config
```

Interactive docs: http://localhost:8000/docs

---

## MCP Interface (for AI Agents)

```bash
python -m music_teacher_ai.api.mcp_server
```

Communicates via stdin/stdout (newline-delimited JSON). See `AGENTS.md` for full tool reference.

---

## Project Structure

```
music_teacher_ai/
├── application/    # Shared use-cases used by CLI/REST/MCP adapters
├── config/         # Settings and environment loading
├── core/           # API clients (Spotify, Genius, Billboard)
├── database/       # SQLModel models and SQLite engine
├── pipeline/       # Ingestion/expansion, fetchers, observers, reporting
├── education_services/ # Exercise/vocabulary/phrasal-verb/lesson builders
├── search/         # Keyword and semantic search
├── api/            # CLI (Typer), REST API (FastAPI), MCP server
└── ai/             # Natural language query parser
tests/
data/               # Generated at runtime (SQLite DB, FAISS index)
```

---

## Development

```bash
uv run pytest
uv run black .
uv run ruff check .
```

---

## Release Readiness Checklist (v0.1)

Use `RELEASE_CHECKLIST.md` as the release gate. Mark items only after evidence is collected.

Run the automated checklist gates locally:

```bash
uv sync --frozen --all-groups --all-extras

timeout 20m uv run ruff check .
timeout 20m uv run pytest tests --ignore=tests/smoke

timeout 5m uv run music-teacher status
timeout 5m uv run python - <<'PY'
from music_teacher_ai.api.rest_api import app, health

assert health().get("status") == "ok"
assert "/health" in {route.path for route in app.routes}
print("startup smoke passed")
PY
```

Run the same gate in CI with GitHub Actions:

- Workflow: `.github/workflows/release-gate.yml`
- Triggers: pull requests, pushes to `main`, or manual `workflow_dispatch`
- Artifact: `release-checklist` (uploads `RELEASE_CHECKLIST.md`)

---

## Resource Usage (estimated, seed-first default)

| Resource | Usage |
|----------|-------|
| Lyrics corpus | ~60 MB |
| FAISS embeddings | ~150 MB |
| SQLite database | ~20 MB |
| RAM (at rest) | ~300 MB |
| RAM (with model loaded) | ~700 MB |

Designed to run comfortably on a 4 GB VPS.
