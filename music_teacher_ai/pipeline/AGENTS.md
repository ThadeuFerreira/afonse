# pipeline/

Sequential ingestion stages that populate the database. Each stage is an
idempotent function that reads what is missing and writes what it finds.
Stages are run in order by `music-teacher init`.

## Files

| File | Stage | What it does |
|------|-------|-------------|
| `charts_ingestion.py` | 1 — Charts | Fetches Wikipedia Year-End Hot 100 for each year; inserts `Artist`, `Song`, and `Chart` rows |
| `metadata_enrichment.py` | 2 — Metadata | Enriches `Song` rows where `metadata_source IS NULL` via Spotify → MusicBrainz + Last.fm |
| `lyrics_downloader.py` | 3 — Lyrics | Downloads lyrics from Genius for songs without a `Lyrics` row |
| `vocabulary_indexer.py` | 4 — Vocabulary | Tokenizes lyrics and populates the `VocabularyIndex` table |
| `embedding_pipeline.py` | 5 — Embeddings | Encodes lyrics with `sentence-transformers` and writes vectors to FAISS + `Embedding` table |
| `enrichment.py` | Expansion ingest | Variant-based enrichment orchestration (genre/artist/year) |
| `expansion.py` | On-demand growth | Background expansion triggered from sparse search results |
| `fetchers.py` | Shared fetch primitives | Last.fm / MusicBrainz fetch functions and variant planner |
| `types.py` | Shared pipeline types | `CandidateSong`, `EnrichmentResult`, `Variant` |
| `observers.py` | Output adapters | `RichObserver` and `NullObserver` for UI/headless execution |
| `reporter.py` | JSON reporting | Persists structured stage/enrichment reports |
| `jobs.py` | Job seam | Background job interface for future queue adapters |

## Ordering dependency

```
charts → metadata → lyrics → vocabulary → embeddings
```

Each stage depends only on what the previous stage wrote — they can be run
independently to resume or update partial ingestions.

## Patterns

- **Idempotent by design.** Every stage skips rows that are already complete
  (e.g. `WHERE metadata_source IS NULL`, `WHERE song_id NOT IN lyrics`).
  Re-running a stage is safe and only processes new or failed entries.
- **Per-song sessions.** Each song is processed inside its own `with get_session()`
  block so a single failure does not roll back the entire batch.
- **`IngestionFailure` for errors.** Instead of crashing, failed songs are
  recorded in `ingestionfailure` with `stage`, `error_message`, and `retry_count`.
  Use `music-teacher retry-failed` to reprocess them.
- **Rich progress bars.** Each stage renders a live `rich.progress.Progress` bar
  showing `M/N` counts, percentage, elapsed time, and per-stage counters
  (e.g. `✓enriched ✗failed`).
- **Headless-friendly enrichment.** `enrich_database()` accepts an optional
  observer (`PipelineObserver`); default is `RichObserver`, while `NullObserver`
  is suitable for service/worker execution without terminal output.
- **Shared primitives, no private cross-imports.** Expansion and enrichment
  share public modules (`fetchers.py`, `types.py`) rather than importing each
  other's private helpers.
- **Debug logging via icecream.** Set `DEBUG=1` to enable `ic()` trace output
  showing per-song API responses, resolved sources, and ISRC values.
- **Metadata source priority** (enrichment stage):
  1. Spotify — disabled for the whole batch on the first `SpotifyPremiumRequiredError`
  2. MusicBrainz + Last.fm — used as fallback
  3. `IngestionFailure(stage="metadata")` if neither source returns a result
