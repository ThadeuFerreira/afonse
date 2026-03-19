# database/

SQLite persistence layer. Defines the schema (SQLModel ORM) and provides a
session factory. No business logic lives here.

## Files

| File | Purpose |
|------|---------|
| `models.py` | SQLModel table definitions — one class per DB table |
| `sqlite.py` | Engine creation, `create_db()`, `get_session()`, and auto-migration |

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

## Patterns

- **`get_session()` is a context manager.** Always use `with get_session() as session:`.
  The session is committed or rolled back by the caller, never by the helper.
- **Auto-migration on startup.** `sqlite.py` runs `_migrate()` at import time
  when the DB file already exists. `_migrate()` iterates `SQLModel.metadata` and
  issues `ALTER TABLE … ADD COLUMN` for any column present in the model but
  absent in the live schema. New model fields are therefore picked up automatically
  without a full rebuild.
- **`metadata_source` sentinel.** `song.metadata_source = None` means the song
  has not been enriched yet. The enrichment pipeline queries `WHERE metadata_source IS NULL`
  to find work to do. Never set `metadata_source` to `None` after enrichment.
- **`faiss_id` links SQLite to FAISS.** Each `Embedding` row stores the integer
  offset at which its vector was inserted into the FAISS index. Use this to map
  FAISS search results back to songs rather than relying on insertion order.
