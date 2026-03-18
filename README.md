# Music Teacher AI

A local knowledge base of song lyrics and metadata to help English teachers find songs suitable for language learning.

## What It Does

- Ingests Billboard Hot 100 charts (1960 → present) from Spotify and Genius
- Stores lyrics, metadata, and vocabulary indexes locally in SQLite
- Supports keyword search, semantic search, and natural language queries
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

This runs the full pipeline:

1. Fetches Billboard Hot 100 for every year (1960 → now)
2. Enriches each song with Spotify metadata
3. Downloads lyrics from Genius
4. Builds a vocabulary index (word → songs)
5. Generates sentence embeddings for semantic search

Estimated time: several hours for the full dataset. API rate limits apply.

---

## Commands

```bash
music-teacher status                    # Show database stats
music-teacher search --word dream       # Find songs containing "dream"
music-teacher search --query "songs about freedom"  # Semantic search
music-teacher search --word love --year-min 1970 --year-max 1980
music-teacher update --genre jazz       # Add more songs by genre
music-teacher update --artist "Nina Simone"
music-teacher update --year 1994
music-teacher retry-failed              # Retry failed ingestion steps
music-teacher rebuild-embeddings        # Rebuild FAISS index
```

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

## REST API

Start the server:

```bash
uvicorn music_teacher_ai.api.rest_api:app --reload
```

Key endpoints:

```
GET  /search?word=dream&year=1995
POST /query   {"query": "songs about hope"}
GET  /songs/{id}
GET  /lyrics/{id}
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
├── config/         # Settings and environment loading
├── core/           # API clients (Spotify, Genius, Billboard)
├── database/       # SQLModel models and SQLite engine
├── pipeline/       # Ingestion steps (charts, metadata, lyrics, embeddings)
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

## Resource Usage (estimated)

| Resource | Usage |
|----------|-------|
| Lyrics corpus | ~60 MB |
| FAISS embeddings | ~150 MB |
| SQLite database | ~20 MB |
| RAM (at rest) | ~300 MB |
| RAM (with model loaded) | ~700 MB |

Designed to run comfortably on a 4 GB VPS.
