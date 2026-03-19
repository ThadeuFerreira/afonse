# api/

User-facing interfaces. Three parallel surfaces — CLI, REST API, and MCP — all
backed by the same `search/` and `playlists/` layer. No business logic lives
here; this package only translates input formats and renders output.

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
  and writes responses to stdout. Tool names match the `AGENTS.md` at the project
  root. Add new tools by extending the `TOOLS` list and the dispatch dict.
- **REST returns plain lists.** Search endpoints return `list[dict]` directly,
  not wrapped in `{results: […]}`, so Postman tests and downstream clients can
  index the array at `[0]` without unwrapping.
