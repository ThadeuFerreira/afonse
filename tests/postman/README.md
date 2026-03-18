# Music Teacher API – Postman Test Suite

Automated REST API tests for the Music Teacher AI project.

---

## Files

| File | Purpose |
|------|---------|
| `music-teacher-api.postman_collection.json` | All requests and test scripts |
| `music-teacher-api.postman_environment.json` | Environment variables (base URL, dynamic IDs) |

---

## Prerequisites

The API server must be running before executing the tests.

Start the server:

```bash
uvicorn music_teacher_ai.api.rest_api:app --reload
```

The database must be initialized:

```bash
music-teacher init
```

---

## Import into Postman (GUI)

1. Open Postman
2. Click **Import**
3. Select both JSON files
4. Select the **Music Teacher API** environment from the top-right dropdown
5. Open the **Music Teacher API** collection and click **Run collection**

---

## Run with Newman (CLI)

Install Newman:

```bash
npm install -g newman
```

Run the full suite:

```bash
newman run tests/postman/music-teacher-api.postman_collection.json \
       -e tests/postman/music-teacher-api.postman_environment.json \
       --reporters cli,json \
       --reporter-json-export tests/postman/results.json
```

Run against a remote server:

```bash
newman run tests/postman/music-teacher-api.postman_collection.json \
       -e tests/postman/music-teacher-api.postman_environment.json \
       --env-var "base_url=https://your-vps-ip:8000"
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `base_url` | `http://localhost:8000` | API server URL |
| `song_id` | `1` | Set automatically by the keyword search request. Override manually if needed. |
| `playlist_id` | _(empty)_ | Set automatically by the playlist create request. |

---

## Test Folders

| Folder | What it tests |
|--------|--------------|
| **Health** | `GET /health` — server reachability |
| **Database** | `GET /status` — DB counts and field presence |
| **Search** | `GET /songs`, `GET /search`, `POST /query` |
| **Lyrics** | `GET /lyrics/{id}` — field presence |
| **Similar Lyrics** | `GET /similar/song/{id}`, `POST /similar/text` |
| **Playlists** | Full create → get → export → refresh → delete lifecycle |
| **Errors** | 404 / 409 / 422 error responses |

---

## Test Execution Order

Run the folders in the order they appear in the collection. The **Search** folder saves `song_id` and the **Playlists** folder saves `playlist_id` as environment variables for downstream tests.

If you run individual folders out of order, set `song_id` manually in the environment to a valid song ID from your database.

---

## Semantic / Similar Tests

The `POST /query` and `POST /similar/text` tests accept a `503` response when the FAISS index has not been built yet. Run `music-teacher rebuild-embeddings` to enable those tests to return `200`.

---

## CI/CD Integration

GitHub Actions example (`.github/workflows/api-tests.yml`):

```yaml
name: API Tests
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install uv
          uv sync
      - name: Start API server
        run: uvicorn music_teacher_ai.api.rest_api:app &
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
      - name: Install Newman
        run: npm install -g newman
      - name: Run Postman tests
        run: |
          newman run tests/postman/music-teacher-api.postman_collection.json \
                 -e tests/postman/music-teacher-api.postman_environment.json
```
