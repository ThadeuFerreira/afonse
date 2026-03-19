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

## CLI commands (`music-teacher`)

| Command | Description |
|---------|-------------|
| `init` | Full pipeline: charts → metadata → lyrics → vocabulary → embeddings |
| `init --quick` | Top 10 songs/year since 2000 (~250 songs, fast bootstrap) |
| `init --workers N` | Tune parallel Wikipedia fetchers (default 5) |
| `update` | Incremental update for a specific year, genre, or artist |
| `search` | Keyword or semantic search |
| `similar` | Find lyrically similar songs |
| `playlist create/show/list/delete/export/refresh` | Playlist management |
| `doctor` | Health-check all components and credentials |
| `retry-failed` | Reprocess `IngestionFailure` rows |
| `rebuild-embeddings` | Rebuild the FAISS index from scratch |
| `migrate-db` | Run explicit database migrations/index creation |

## Patterns

- **Validation before ingestion.** The `init` command clamps and validates `start`/`end`
  years before computing `chart_start`, so raw CLI arguments never reach the
  pipeline unchecked.
- **`--quick` uses validated `end`.** Quick mode overrides `chart_start` to 2000
  *after* the validation block so the sanitized `end` year is preserved.
- **Lazy pipeline imports.** Pipeline modules are imported inside command
  functions (`from music_teacher_ai.pipeline.charts_ingestion import …`) to keep
  CLI startup fast and avoid import-time side-effects.
- **MCP tool dispatch.** `mcp_server.py` reads newline-delimited JSON from stdin
  and writes responses to stdout. Dispatch is registry-based (`tool_name -> handler`)
  to keep handlers cohesive and reduce if/elif growth.
- **Application-service delegation.** Shared behaviors (search expansion policy,
  playlist orchestration, enrichment validation, config updates) live in
  `music_teacher_ai/application/*` and are reused across CLI/REST/MCP.
- **Search response contract.** REST/MCP `search` returns:
  `{ "results": [...], "database_expansion_triggered": bool }`.
- **Education endpoints (REST).** `rest_api.py` exposes lesson-generation routes:
  `/education/exercise/{song_id}`, `/education/vocabulary/{song_id}`,
  `/education/phrasal-verbs/{song_id}`, and `/education/lesson`.
