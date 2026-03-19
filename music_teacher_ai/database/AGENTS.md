# database/

SQLite persistence layer. Defines the schema (SQLModel ORM) and provides a
session factory. No business logic lives here.

## Files

| File | Purpose |
|------|---------|
| `models.py` | SQLModel table definitions — one class per DB table |
| `sqlite.py` | Engine creation, `create_db()`, `get_session()`, and explicit migration entrypoint |
| `repositories.py` | Shared persistence helpers (`SongRepository`, `SongCandidateRepository`, `song_key`) |

## Schema

| Table | Key columns |
|-------|-------------|
| `song` | `id`, `title`, `artist_id`, `release_year`, `genre`, `popularity`, `isrc`, `metadata_source` |
| `artist` | `id`, `name`, `spotify_id`, `genres` (JSON list) |
| `album` | `id`, `name`, `artist_id`, `release_year` |
| `lyrics` | `song_id` (PK), `lyrics_text`, `word_count`, `unique_words` |
| `chart` | `song_id`, `chart_name`, `rank`, `date` |
| `vocabularyindex` | `word`, `song_id` — one row per word per song |
| `embedding` | `song_id` (PK), `embedding_vector` (bytes), `faiss_id` |
| `ingestionfailure` | `song_id`, `stage`, `error_message`, `retry_count` |
| `songcandidate` | `title`, `artist`, `query_origin`, `status`, `source_api` |
| `backgroundjob` | `job_type`, `query_origin`, `status`, timestamps |

## Patterns

- **`get_session()` is a context manager.** Always use `with get_session() as session:`.
  The session is committed or rolled back by the caller, never by the helper.
- **Explicit migration flow.** Use `migrate_db()` (or CLI `music-teacher migrate-db`)
  to run schema/index migrations. This avoids hidden import-time side effects.
- **Integrity indexes for idempotency.** Migration ensures unique/index constraints
  for duplicate-prone paths (e.g. song identity and candidate identity).
- **`metadata_source` sentinel.** `song.metadata_source = None` means the song
  has not been enriched yet. The enrichment pipeline queries `WHERE metadata_source IS NULL`
  to find work to do. Never set `metadata_source` to `None` after enrichment.
- **`faiss_id` links SQLite to FAISS.** Each `Embedding` row stores the integer
  offset at which its vector was inserted into the FAISS index. Use this to map
  FAISS search results back to songs rather than relying on insertion order.
