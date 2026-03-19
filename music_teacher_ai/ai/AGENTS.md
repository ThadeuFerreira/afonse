# ai/

Natural-language understanding utilities. Converts free-text user input into
structured search parameters without requiring an LLM API call.

## Files

| File | Purpose |
|------|---------|
| `query_parser.py` | Rule-based parser — maps natural language to `ParsedQuery` |

## `ParsedQuery` fields

| Field | Example input | Resolved value |
|-------|--------------|----------------|
| `word` | "with the word dream" | `"dream"` |
| `year` | "in 1995" | `1995` |
| `year_min` / `year_max` | "from the 90s" | `1990` / `1999` |
| `artist` | "by Adele" | `"Adele"` |
| `genre` | _(not yet extracted)_ | `None` |
| `semantic_query` | "songs about loneliness" | the full query string |

## Patterns

- **LLM is a last resort.** The parser uses compiled regexes to extract
  structured intent (years, decades, keywords, artists) with zero latency and
  no API cost. Only queries that match semantic trigger words (`"about"`,
  `"theme"`, `"feeling"`, etc.) are forwarded to the FAISS semantic search —
  and even then no LLM is invoked; the raw query text is encoded locally by
  `sentence-transformers`.
- **Decade expansion.** Both `"90s"` (two-digit) and `"1990s"` (four-digit) are
  recognized and expanded to `year_min=1990, year_max=1999`.
- **Non-exclusive fields.** A single query may produce multiple populated fields
  (e.g. `word="dream"` + `year_min=1990` + `artist="Fleetwood Mac"`). Callers
  pass all non-None fields to `search_songs()` for compound filtering.
- **Extend here, not in callers.** Adding a new extraction rule (e.g. genre
  detection) belongs in `query_parser.py`. The CLI, REST API, and MCP server
  consume `ParsedQuery` directly and require no changes.
