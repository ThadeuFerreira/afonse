"""
Smoke tests for the Last.fm client.

Requires LASTFM_API_KEY in .env.
Free key at https://www.last.fm/api/account/create
"""
import os

import pytest


def _clear_lastfm_cache(function_name: str, *args, **kwargs) -> None:
    """
    Remove one cached Last.fm API response so smoke tests always hit live logic.
    """
    from music_teacher_ai.core.api_cache import _cache_path, _make_key

    key = _make_key("lastfm", function_name, args, kwargs)
    cache_file = _cache_path(key)
    if cache_file.exists():
        cache_file.unlink()


def _lastfm_cache_exists(function_name: str, *args, **kwargs) -> bool:
    from music_teacher_ai.core.api_cache import _cache_path, _make_key

    key = _make_key("lastfm", function_name, args, kwargs)
    return _cache_path(key).exists()


requires_lastfm = pytest.mark.skipif(
    not os.getenv("LASTFM_API_KEY"),
    reason="LASTFM_API_KEY not set",
)


@requires_lastfm
def test_lastfm_get_tags():
    """get_tags returns a non-empty list for a well-known track."""
    from music_teacher_ai.core.lastfm_client import _fetch_tags

    _clear_lastfm_cache("_fetch_tags", "Imagine", "John Lennon", 5)
    try:
        tags = _fetch_tags("Imagine", "John Lennon", 5)
    except Exception as exc:
        pytest.skip(f"Last.fm request failed during smoke test: {exc}")

    assert isinstance(tags, list), f"Expected list, got {type(tags)}"
    assert len(tags) > 0, "No tags returned for 'Imagine'"
    assert all(isinstance(t, str) for t in tags), "Tags should be strings"


@requires_lastfm
def test_lastfm_tags_are_lowercase():
    """Tags are returned in lowercase."""
    from music_teacher_ai.core.lastfm_client import _fetch_tags

    _clear_lastfm_cache("_fetch_tags", "Imagine", "John Lennon", 5)
    try:
        tags = _fetch_tags("Imagine", "John Lennon", 5)
    except Exception as exc:
        pytest.skip(f"Last.fm request failed during smoke test: {exc}")

    assert isinstance(tags, list), f"Expected list, got {type(tags)}"
    assert len(tags) > 0, "No tags returned for 'Imagine'"
    for tag in tags:
        assert tag == tag.lower(), f"Tag not lowercase: {tag!r}"


@requires_lastfm
def test_lastfm_get_play_count():
    """get_play_count returns a positive integer for a well-known track."""
    from music_teacher_ai.core.lastfm_client import _fetch_play_count

    _clear_lastfm_cache("_fetch_play_count", "Imagine", "John Lennon")
    try:
        count = _fetch_play_count("Imagine", "John Lennon")
    except Exception as exc:
        pytest.skip(f"Last.fm request failed during smoke test: {exc}")

    assert count is not None, "play count is None"
    assert count > 0, f"play count should be positive, got {count}"


@requires_lastfm
def test_lastfm_fetch_tags_uses_cache_without_network(monkeypatch):
    """Second identical _fetch_tags call should be served from cache."""
    import music_teacher_ai.core.lastfm_client as lfm

    title, artist, limit = "Imagine", "John Lennon", 5
    _clear_lastfm_cache("_fetch_tags", title, artist, limit)

    try:
        first_tags = lfm._fetch_tags(title, artist, limit)
    except Exception as exc:
        pytest.skip(f"Last.fm request failed during smoke test: {exc}")

    assert _lastfm_cache_exists("_fetch_tags", title, artist, limit), (
        "Expected cache file to exist after first _fetch_tags call"
    )

    def _raise_if_network_used():
        raise RuntimeError("Network should not be used on cache hit")

    monkeypatch.setattr(lfm, "_get_network", _raise_if_network_used)
    second_tags = lfm._fetch_tags(title, artist, limit)
    assert second_tags == first_tags, "Cache hit should return the first result"


def test_lastfm_get_tags_returns_empty_when_not_configured(monkeypatch):
    """get_tags returns [] gracefully when the key is missing."""
    _clear_lastfm_cache("_fetch_tags", "Imagine", "John Lennon", 5)
    monkeypatch.setenv("LASTFM_API_KEY", "")
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.core.lastfm_client as lfm
    importlib.reload(s)
    importlib.reload(lfm)

    tags = lfm.get_tags("Imagine", "John Lennon")
    assert tags == []


def test_lastfm_is_configured(monkeypatch):
    """is_configured reflects whether LASTFM_API_KEY is set."""
    import importlib

    import music_teacher_ai.config.settings as s
    import music_teacher_ai.core.lastfm_client as lfm

    monkeypatch.setenv("LASTFM_API_KEY", "test_key")
    importlib.reload(s)
    importlib.reload(lfm)
    assert lfm.is_configured() is True

    monkeypatch.setenv("LASTFM_API_KEY", "")
    importlib.reload(s)
    importlib.reload(lfm)
    assert lfm.is_configured() is False
