# search/

Query execution layer. Translates search parameters into SQL or FAISS lookups
and returns plain `list[dict]` results. No HTTP, no ingestion logic.

## Files

| File | Function | Backing store |
|------|----------|---------------|
| `keyword_search.py` | `search_songs()` | SQL — filters on `Song`, `VocabularyIndex`, `Artist` |
| `semantic_search.py` | `semantic_search()` | FAISS — encodes query text and finds nearest embeddings |
| `similar_search.py` | `find_similar_by_song()` / `find_similar_by_title()` / `find_similar_by_text()` | FAISS — finds songs whose lyrics vectors are close to a reference |

## Patterns

- **All functions return `list[dict]`.** Dicts have consistent keys (`id`, `title`,
  `artist`, `year`, `genre`, `popularity`, `score` where applicable) so callers
  (CLI, REST API, MCP) can render results uniformly.
- **`limit` is applied in SQL, not Python.** Artist and genre filters are pushed
  into the `WHERE` clause before `LIMIT` so the result count is always correct.
- **FAISS → SQLite via `faiss_id`.** Search results come back as raw FAISS integer
  IDs. `Embedding.faiss_id` maps each index position back to a `song_id`. Never
  assume FAISS position equals `song_id` or insertion order.
- **`min_score` filtering.** Similar-search functions accept a `min_score`
  threshold (0.0–1.0 cosine similarity) that is applied after the FAISS search
  to drop low-confidence matches.
- **Requires populated index.** Semantic and similar searches raise `FileNotFoundError`
  if `FAISS_INDEX_PATH` does not exist. Run `music-teacher rebuild-embeddings` first.
