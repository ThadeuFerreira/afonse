# Release Checklist (v0.1)

This checklist is the release gate for `v0.1`. A release is **go** only when:

- every CI gate in `release-gate.yml` is green;
- all required manual checks are marked complete;
- no open `P0` or `P1` defects remain.

How to use this file:

- mark each item with `[x]` only after validation;
- attach evidence (PR, issue, log, benchmark, or command output) in the release PR;
- mark not-applicable items as `N/A` with a short reason.

## CI Gates (automated)

- [ ] `uv run ruff check .` passes.
- [ ] `uv run pytest tests --ignore=tests/smoke` passes.
- [ ] Startup smoke passes:
  `uv run music-teacher status` and `GET /health` via FastAPI `TestClient`.
- [ ] `RELEASE_CHECKLIST.md` is uploaded as a CI artifact (`release-checklist`).

## 1. Deployment And First Run

- [ ] Fresh machine quickstart completes in under 5 minutes using documented commands.
- [ ] `music-teacher init` runs with default settings and no manual file edits.
- [ ] Runtime directories are auto-created:
  `data/`, `data/database/`, `data/playlists/`, `data/exercises/`, `logs/`.
- [ ] `music-teacher start --minimal` boots successfully and serves `GET /health`.
- [ ] Default config works without credentials for local/offline features.

## 2. Runtime Footprint And Dependencies

- [ ] Baseline memory usage is measured and acceptable on a 4 GB VPS target.
- [ ] Semantic model load is lazy (loaded only when semantic features are used).
- [ ] Exercise/NLP modules are lazy-loaded where practical.
- [ ] Startup does not require downloading large ML artifacts during API boot.

## 3. Data Integrity And Quality

- [ ] Duplicate prevention is enforced (unique keys/indexes for song identity).
- [ ] Metadata normalization exists for title/artist matching (punctuation/accents/case).
- [ ] Ingestion path is idempotent when the same source data is replayed.
- [ ] Failed ingestion records are tracked and retryable.
- [ ] Cleanup path exists for stale candidate/failed records.
- [ ] Maximum database size policy is defined (for example `max_songs=50k`) and enforced.

## 4. API And External Service Resilience

- [ ] Outbound API requests are rate-limited (global cap documented).
- [ ] Retry policy uses bounded exponential backoff (`max_retries` defined).
- [ ] External API failures degrade gracefully to local DB behavior where applicable.
- [ ] Timeouts are set for outbound API calls.
- [ ] Enrichment failures are visible in logs and status/report outputs.

## 5. Concurrency And Job Safety

- [ ] Write-heavy ingestion/enrichment uses a serialized single-writer strategy (or equivalent).
- [ ] Concurrent job triggers avoid duplicate inserts and unsafe races.
- [ ] SQLite locking strategy is defined and tested under concurrent triggers.
- [ ] Long-running jobs have limits/timeouts and do not block API responsiveness indefinitely.

## 6. Search And Performance

- [ ] Core DB indexes exist and are verified:
  `song.title`, `artist.name`, `song.release_year`, `song.genre`, `vocabularyindex.word`.
- [ ] Keyword search p95 latency is measured on representative dataset size.
- [ ] Semantic search p95 latency is measured on representative dataset size.
- [ ] Playlist creation and export are tested on larger result sets.

## 7. Security Baseline

- [ ] Output/export filenames are sanitized to prevent directory traversal.
- [ ] Sensitive/admin endpoints require authentication and proper scope checks.
- [ ] Optional API key mode is documented for non-local deployments.
- [ ] Inbound rate limiting is available (or reverse proxy guidance is documented).
- [ ] Secrets are never written to logs.

## 8. Observability And Operations

- [ ] Structured logs include timestamp, component, and operation status.
- [ ] Logs cover search, enrichment jobs, inserts/duplicates, and API failures.
- [ ] `/status` endpoint returns core operational counters.
- [ ] Failure modes produce actionable error messages (CLI and API).

## 9. Documentation And DX

- [ ] `INSTALL.md` is present and accurate.
- [ ] `QUICKSTART.md` is present and accurate.
- [ ] `COMMANDS.md` is present and accurate.
- [ ] `FEATURES.md` is present and accurate.
- [ ] README examples are runnable and match current CLI/API behavior.

## 10. Release Artifacts And Sign-Off

- [ ] Version/changelog entry prepared for `v0.1`.
- [ ] Known limitations and operational constraints documented.
- [ ] Rollback plan documented (DB/file backup + restore steps).
- [ ] Final release PR includes evidence for all mandatory checklist items.

Release sign-off:

- [ ] Engineering owner approval
- [ ] Product owner approval
- [ ] Release timestamp recorded
