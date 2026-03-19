# core/

Thin, stateless clients for every external data source. Each module wraps one
API and returns plain Python dataclasses — no database access, no side-effects.

All public functions that make network requests are decorated with
`@cached_api(namespace)` (see `api_cache.py`) so successful responses are
persisted to `data/api_cache/` and never re-fetched.

## Files

| File | External service | What it returns |
|------|-----------------|-----------------|
| `spotify_client.py` | Spotify Web API | `TrackMetadata` — full metadata + audio features |
| `musicbrainz_client.py` | MusicBrainz API | `TrackMetadata` — title, artist, album, year, ISRC |
| `lastfm_client.py` | Last.fm API | genre tags (`list[str]`) and play counts (`int`) |
| `lyrics_client.py` | Genius API | normalized lyrics (`str`) |
| `billboard_client.py` | Wikipedia Year-End Hot 100 pages | `list[ChartEntry]` per year |
| `api_cache.py` | (local disk) | `@cached_api` decorator used by all clients above |

## Patterns

- **No DB imports.** Core modules never touch `database/`. The pipeline layer owns
  persistence.
- **`TrackMetadata` is the shared DTO.** Spotify, MusicBrainz, and Last.fm all
  return (or augment) this dataclass so the enrichment pipeline can treat every
  source uniformly.
- **Errors propagate.** Clients raise `RuntimeError` (or service-specific
  exceptions like `SpotifyPremiumRequiredError`) on failure. Callers decide
  whether to swallow or surface the error — core modules never silently return
  stale/partial data.
- **Last.fm is an exception:** `get_tags` / `get_play_count` return `[]` / `None`
  on failure because they are supplemental enrichment; the inner `_fetch_*`
  functions raise and are cached separately.
- **Cache key = (namespace, function name, args).** Two calls with different
  arguments (e.g. different `limit` values) produce separate cache entries.

## `api_cache` usage

```python
@cached_api("spotify", from_cache=lambda d: TrackMetadata(**d))
def search_track(title: str, artist: str) -> Optional[TrackMetadata]: ...

# For list-of-dataclasses use serialize + from_cache:
@cached_api(
    "wikipedia_charts",
    serialize=lambda r: [dataclasses.asdict(e) for e in r],
    from_cache=lambda data: [ChartEntry(**d) for d in data],
)
def fetch_chart_for_year(year: int, limit: int | None = None) -> list[ChartEntry]: ...
```
