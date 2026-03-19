# config/

Central configuration module. All runtime settings are read here and imported
from everywhere else — nothing reads `os.getenv` or `.env` directly outside
this package.

## Files

| File | Purpose |
|------|---------|
| `settings.py` | Loads `.env` via `python-dotenv`, exposes every setting as a module-level constant |

## Patterns

- **Single source of truth.** Add new env vars here and nowhere else. Downstream
  modules import the constant (e.g. `from music_teacher_ai.config.settings import GENIUS_ACCESS_TOKEN`).
- **No logic.** This package only reads and exposes values; it never validates,
  transforms, or acts on them.
- **Paths are `pathlib.Path` objects.** `DATABASE_PATH`, `FAISS_INDEX_PATH`,
  `PLAYLISTS_DIR`, and `API_CACHE_DIR` are all `Path` instances so callers can
  use `/` path joining without string manipulation.

## Key constants

| Constant | Default | Description |
|----------|---------|-------------|
| `SPOTIFY_CLIENT_ID / SECRET` | `""` | Optional — Spotify metadata + audio features |
| `GENIUS_ACCESS_TOKEN` | `""` | Required for lyrics |
| `LASTFM_API_KEY` | `""` | Optional — genre tags and play counts |
| `DATABASE_PATH` | `data/music.db` | SQLite database |
| `FAISS_INDEX_PATH` | `data/embeddings.index` | FAISS vector index |
| `PLAYLISTS_DIR` | `data/playlists/` | Playlist JSON files |
| `API_CACHE_DIR` | `data/api_cache/` | Disk cache for external API calls |
| `BILLBOARD_START_YEAR` | `1960` | Earliest year fetched from Wikipedia charts |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model name |
| `EMBEDDING_DIM` | `384` | Vector dimensionality — must match the model |
