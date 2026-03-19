"""
Unit tests for music_teacher_ai/config/credentials.py.
No database, external API, or real .env file required.
"""
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# mask()
# ---------------------------------------------------------------------------

def test_mask_empty_string():
    from music_teacher_ai.config.credentials import mask
    assert mask("") == "(not set)"


def test_mask_short_value():
    from music_teacher_ai.config.credentials import mask
    assert mask("abc") == "****"
    assert mask("abcd") == "****"


def test_mask_long_value():
    from music_teacher_ai.config.credentials import mask
    result = mask("abcde12345")
    assert result == "abcd****"


def test_mask_exact_five_chars():
    from music_teacher_ai.config.credentials import mask
    result = mask("abcde")
    assert result.startswith("abcd")
    assert result.endswith("****")


# ---------------------------------------------------------------------------
# ALLOWED_KEYS
# ---------------------------------------------------------------------------

def test_allowed_keys_contains_expected():
    from music_teacher_ai.config.credentials import ALLOWED_KEYS
    assert "GENIUS_ACCESS_TOKEN" in ALLOWED_KEYS
    assert "SPOTIFY_CLIENT_ID" in ALLOWED_KEYS
    assert "SPOTIFY_CLIENT_SECRET" in ALLOWED_KEYS
    assert "LASTFM_API_KEY" in ALLOWED_KEYS
    assert "DATABASE_PATH" in ALLOWED_KEYS
    assert "API_CACHE_DIR" in ALLOWED_KEYS


def test_allowed_keys_excludes_admin_token():
    from music_teacher_ai.config.credentials import ALLOWED_KEYS
    assert "ADMIN_TOKEN" not in ALLOWED_KEYS


# ---------------------------------------------------------------------------
# update_env() / read_env()
# ---------------------------------------------------------------------------

def test_update_env_creates_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    credentials.update_env({"FOO": "bar"})

    assert env_file.exists()
    assert "FOO=bar" in env_file.read_text()


def test_update_env_updates_existing_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=old\nBAR=keep\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    importlib = __import__("importlib")
    importlib.reload(credentials)
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    credentials.update_env({"FOO": "new"})
    text = env_file.read_text()
    assert "FOO=new" in text
    assert "FOO=old" not in text
    assert "BAR=keep" in text


def test_update_env_appends_new_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=yes\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    credentials.update_env({"NEW_KEY": "hello"})
    text = env_file.read_text()
    assert "NEW_KEY=hello" in text
    assert "EXISTING=yes" in text


def test_update_env_preserves_comments(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# this is a comment\nFOO=bar\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    credentials.update_env({"FOO": "new"})
    text = env_file.read_text()
    assert "# this is a comment" in text


def test_read_env_returns_empty_when_no_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    result = credentials.read_env()
    assert result == {}


def test_read_env_returns_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\nBAZ=qux\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    result = credentials.read_env()
    assert result["FOO"] == "bar"
    assert result["BAZ"] == "qux"


# ---------------------------------------------------------------------------
# get_admin_token() / verify_admin_token()
# ---------------------------------------------------------------------------

def test_get_admin_token_generates_token(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    token = credentials.get_admin_token()
    assert len(token) == 64
    assert all(c in "0123456789abcdef" for c in token)


def test_get_admin_token_persists(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    token1 = credentials.get_admin_token()
    token2 = credentials.get_admin_token()
    assert token1 == token2


def test_get_admin_token_reads_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    fixed_token = "a" * 64
    env_file.write_text(f"ADMIN_TOKEN={fixed_token}\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    assert credentials.get_admin_token() == fixed_token


def test_verify_admin_token_correct(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    fixed_token = "b" * 64
    env_file.write_text(f"ADMIN_TOKEN={fixed_token}\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    assert credentials.verify_admin_token(fixed_token) is True


def test_verify_admin_token_wrong(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    fixed_token = "c" * 64
    env_file.write_text(f"ADMIN_TOKEN={fixed_token}\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    assert credentials.verify_admin_token("wrong_token") is False


# ---------------------------------------------------------------------------
# current_status()
# ---------------------------------------------------------------------------

def test_current_status_returns_all_fields(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    status = credentials.current_status()
    keys = {row["key"] for row in status}
    assert keys == credentials.ALLOWED_KEYS


def test_current_status_masks_secret_fields(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("GENIUS_ACCESS_TOKEN=supersecretvalue\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    status = credentials.current_status()
    genius_row = next(r for r in status if r["key"] == "GENIUS_ACCESS_TOKEN")
    assert genius_row["set"] is True
    assert "supersecretvalue" not in genius_row["masked_value"]
    assert "****" in genius_row["masked_value"]


def test_current_status_not_set_fields(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    status = credentials.current_status()
    for row in status:
        assert row["set"] is False


def test_current_status_non_secret_field_shows_value(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_PATH=/tmp/music.db\n")
    monkeypatch.setattr("music_teacher_ai.config.credentials.ENV_PATH", env_file)

    from music_teacher_ai.config import credentials
    status = credentials.current_status()
    db_row = next(r for r in status if r["key"] == "DATABASE_PATH")
    assert db_row["masked_value"] == "/tmp/music.db"
