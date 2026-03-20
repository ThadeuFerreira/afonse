# api/

User-facing interfaces. Three parallel surfaces — CLI, REST API, and MCP.
Business orchestration is delegated to `music_teacher_ai/application/*` services;
`api/` modules are adapters that parse inputs and map outputs/errors.

## Files

| File | Interface | Entry point |
|------|-----------|-------------|
| `cli.py` | Typer CLI | `music-teacher` command (registered in `pyproject.toml`) |
| `rest_api.py` | FastAPI HTTP | `uvicorn music_teacher_ai.api.rest_api:app` |
| `mcp_server.py` | MCP over stdio | `python -m music_teacher_ai.api.mcp_server` |
| `web/` | Static web UI | Served at `/web` by FastAPI `StaticFiles` mount |

## CLI commands (`music-teacher`)

| Command | Description |
|---------|-------------|
| `init` | Seed-first bootstrap: seed → lyrics → vocabulary → embeddings |
| `config [--show]` | Set/update API credentials; auto-upgrades demo songs when Genius is configured |
| `update "<artist>"` | Synchronous artist expansion + lyrics + vocabulary + embeddings |
| `search` | Keyword or semantic search |
| `similar` | Find lyrically similar songs |
| `inspect songs [--fix]` | Validate title/artist/lyrics; optionally delete invalid rows |
| `repair song <id>` | Re-fetch metadata + lyrics for one song with validation safeguards |
| `playlist create/show/list/delete/export/refresh` | Playlist management |
| `retry-failed` | Reprocess `IngestionFailure` rows |
| `rebuild-embeddings` | Rebuild the FAISS index from scratch |
| `migrate-db` | Run explicit database migrations/index creation |

## Web UI (`web/`)

Mobile-first static interface served at `/web`. No external JS frameworks.

| Page | File | Description |
|------|------|-------------|
| Home | `index.html` | Search bar, recent searches (LocalStorage), nav grid |
| Search | `search.html` | Title/artist search via `/search/simple` |
| Lyrics | `lyrics.html` | Full lyrics, Generate exercise button, Add to playlist |
| Playlist | `playlist.html` | Cart (SessionStorage), save/export M3U |
| Exercise | `exercise.html` | Gap-fill, difficulty pills (10/20/30/40%), download .txt |

## Patterns

- **Seed-first init.** `init` loads `ingestion/songs_seed.json`, then runs lyrics → vocabulary → embeddings. No external chart/metadata APIs in the hot path.
- **Demo-to-live upgrade.** Demo songs (`metadata_source='demo'`) are automatically upgraded to real lyrics by `seed_songs()` during `init`, or by `_maybe_upgrade_demo()` at the end of `config` when Genius credentials are set.
- **Lazy pipeline imports.** Pipeline modules are imported inside command functions to keep CLI startup fast and avoid import-time side-effects.
- **MCP tool dispatch.** `mcp_server.py` reads newline-delimited JSON from stdin and writes responses to stdout. Dispatch is registry-based (`tool_name -> handler`).
- **Application-service delegation.** Shared behaviors (search expansion policy, playlist orchestration, enrichment validation, config updates) live in `music_teacher_ai/application/*` and are reused across CLI/REST/MCP.
- **Search response contract.** REST/MCP `search` returns: `{ "results": [...], "database_expansion_triggered": bool }`.
- **Exercise endpoints.** Two separate exercise generators: `fill_in_blank.py` (numbered `_(N)_` blanks, used by `/education/exercise/{id}`) and `gap_fill.py` (underscore blanks scaled to word length, used by `POST /exercise/gap` and the web UI).
