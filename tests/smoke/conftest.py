"""
Shared fixtures and skip markers for smoke tests.

Smoke tests hit real external APIs and require credentials in .env.
Run them with:

    uv run pytest tests/smoke/ -v -m smoke

Or via the CLI:

    music-teacher doctor
"""
import os

import pytest
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Skip markers – each test declares which credentials it needs
# ---------------------------------------------------------------------------

def _skip_if_missing(*env_vars: str):
    missing = [v for v in env_vars if not os.getenv(v)]
    if missing:
        return pytest.mark.skip(reason=f"Missing env vars: {', '.join(missing)}")
    return pytest.mark.usefixtures()  # no-op marker


requires_spotify = pytest.mark.skipif(
    not (os.getenv("SPOTIFY_CLIENT_ID") and os.getenv("SPOTIFY_CLIENT_SECRET")),
    reason="SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET not set",
)

requires_genius = pytest.mark.skipif(
    not os.getenv("GENIUS_ACCESS_TOKEN"),
    reason="GENIUS_ACCESS_TOKEN not set",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """
    Provide a temporary SQLite database isolated from the real data directory.
    Patches DATABASE_PATH so all pipeline code uses the temp file.
    """
    db_file = tmp_path / "test_music.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_file))

    # Re-import settings so the patched env var is picked up
    import importlib

    import music_teacher_ai.config.settings as settings_mod
    import music_teacher_ai.database.sqlite as sqlite_mod

    importlib.reload(settings_mod)
    importlib.reload(sqlite_mod)

    sqlite_mod.create_db()
    yield db_file

    # cleanup is handled by tmp_path fixture


@pytest.fixture()
def tmp_faiss(tmp_path, monkeypatch):
    """Provide a temp path for the FAISS index."""
    index_file = tmp_path / "test_embeddings.index"
    monkeypatch.setenv("FAISS_INDEX_PATH", str(index_file))

    import importlib

    import music_teacher_ai.config.settings as settings_mod
    importlib.reload(settings_mod)

    yield index_file
