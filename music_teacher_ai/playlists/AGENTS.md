# playlists/

Playlist creation, storage, and export. Playlists are file-backed JSON
documents stored under `data/playlists/{slug}/`. No playlist data is kept in
SQLite.

## Files

| File | Purpose |
|------|---------|
| `models.py` | Pydantic models: `Playlist`, `PlaylistSong`, `PlaylistQuery` |
| `manager.py` | CRUD operations: `create`, `get`, `list_all`, `delete`, `refresh` |
| `exporters.py` | Format renderers: `to_m3u`, `to_m3u8`, `to_json`, `render`, `export_all` |

## Data model

```
Playlist
├── id          slug derived from name, e.g. "dream-vocabulary"
├── name        human-readable label
├── description optional
├── created_at  ISO date string
├── query       PlaylistQuery — stored so the list can be refreshed later
└── songs[]     PlaylistSong{song_id, title, artist, year, spotify_id}
```

`PlaylistQuery` mirrors the fields of `search_songs()` plus `semantic_query`,
`similar_text`, and `similar_song_id`. All fields are optional; the combination
used at creation time is replayed on `refresh`.

## Patterns

- **Slug uniqueness is directory-based.** `create()` raises `FileExistsError` if
  `data/playlists/{slug}/` already exists. Callers (CLI, REST) map this to a 409
  response or an error message.
- **Slug generation is character-exact.** Each whitespace or underscore character
  in the name is replaced with a single `-` (no collapsing of runs). `"Love  Songs"`
  becomes `"love--songs"`, not `"love-songs"`, so two differently-spaced names
  always produce different slugs.
- **`refresh` replays `PlaylistQuery`.** The stored query is re-executed against
  the current database, so a refreshed playlist automatically picks up newly
  ingested songs that match the original criteria.
- **Export formats.** `render(playlist, fmt)` accepts `"m3u"`, `"m3u8"`, or
  `"json"`. M3U/M3U8 files embed `#EXTINF` tags and use `spotify:track:{id}` URIs
  when `spotify_id` is available, falling back to `title - artist`.
