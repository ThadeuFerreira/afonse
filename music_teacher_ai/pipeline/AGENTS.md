# pipeline/

Sequential ingestion stages that populate the database. Each stage is an
idempotent function that reads what is missing and writes what it finds.
Stages are run in order by `music-teacher init`.

## Files

| File | Stage | What it does |
|------|-------|-------------|
| `lyrics_downloader.py` | 1 — Lyrics | Downloads lyrics from Genius for songs without a `Lyrics` row |
| `vocabulary_indexer.py` | 2 — Vocabulary | Tokenizes lyrics and populates the `VocabularyIndex` table |
| `embedding_pipeline.py` | 3 — Embeddings | Encodes lyrics with `sentence-transformers` and writes vectors to FAISS + `Embedding` table |
| `validation.py` | Input guard | Validates title, artist, and lyrics fields; classifies hard failures vs soft warnings |
| `metadata_enrichment.py` | Optional enrichment | Enriches `Song` rows where `metadata_source IS NULL` via Spotify → MusicBrainz + Last.fm (not part of the default init path) |
| `charts_ingestion.py` | Legacy / on-demand | Fetches Wikipedia Year-End Hot 100 for each year |
| `enrichment.py` | Expansion ingest | Variant-based enrichment orchestration (genre/artist/year) |
| `expansion.py` | On-demand growth | Artist/genre expansion triggered from `update` command or sparse search results |
| `fetchers.py` | Shared fetch primitives | Last.fm / MusicBrainz fetch functions and variant planner |
| `types.py` | Shared pipeline types | `CandidateSong`, `EnrichmentResult`, `Variant` |
| `observers.py` | Output adapters | `RichObserver` and `NullObserver` for UI/headless execution |
| `reporter.py` | JSON reporting | Persists structured stage/enrichment reports |
| `jobs.py` | Job seam | Background job interface for future queue adapters |

## Ordering dependency (default `init` path)

```
seed (ingestion/seed_ingestion.py) → lyrics → vocabulary → embeddings
```

Charts and metadata enrichment are not part of the default init path. They are available as standalone commands for on-demand use.

## Lyrics validation (`validation.py`)

`validate_lyrics()` applies these rules in order:

| Check | Severity | Threshold |
|-------|----------|-----------|
| Empty / blank | Hard fail | — |
| Too short | Hard fail | < 20 chars |
| Too long | Hard fail | > 10 000 chars |
| Word count too high | Hard fail | > 1 000 words |
| Word count suspicious | Soft warning (stored) | 500–1 000 words |
| JSON bracket at start | Hard fail | — |
| Dense JSON-key patterns | Hard fail | ≥ 3 in first 500 chars |
| Parses as valid JSON | Hard fail | — |
| Control characters | Hard fail | — |

`ValidationResult` has both `issues` (hard failures, set `ok=False`) and `warnings` (soft flags, `ok` stays `True`). Lyrics in the warning band are stored and logged to the pipeline report but not rejected.

## Patterns

- **Idempotent by design.** Every stage skips rows that are already complete (`WHERE song_id NOT IN lyrics`, etc.). Re-running a stage is safe.
- **Per-song sessions.** Each song is processed inside its own `with get_session()` block so a single failure does not roll back the entire batch.
- **`IngestionFailure` for errors.** Failed songs are recorded in `ingestionfailure` with `stage`, `error_message`, and `retry_count`. Use `music-teacher retry-failed` to reprocess them.
- **Rich progress bars.** Each stage renders a live `rich.progress.Progress` bar showing `M/N` counts, elapsed time, and per-stage counters.
- **Adaptive rate-limit backoff.** `lyrics_downloader.py` halves the worker count on each 429 response; at 1 worker it records a hard rate limit and stops cleanly.
- **Debug logging via icecream.** Set `DEBUG=1` to enable `ic()` trace output showing per-song API responses and resolved sources.
- **Metadata source priority** (enrichment stage, when used):
  1. Spotify — disabled for the whole batch on the first `SpotifyPremiumRequiredError`
  2. MusicBrainz + Last.fm — used as fallback
  3. `IngestionFailure(stage="metadata")` if neither source returns a result
