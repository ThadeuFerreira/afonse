"""
Smoke tests for the Last.fm client.

Requires LASTFM_API_KEY in .env.
Free key at https://www.last.fm/api/account/create
"""
import os
import pytest

requires_lastfm = pytest.mark.skipif(
    not os.getenv("LASTFM_API_KEY"),
    reason="LASTFM_API_KEY not set",
)


@requires_lastfm
def test_lastfm_get_tags():
    """get_tags returns a non-empty list for a well-known track."""
    from music_teacher_ai.core.lastfm_client import get_tags

    tags = get_tags("Imagine", "John Lennon")

    assert isinstance(tags, list), f"Expected list, got {type(tags)}"
    assert len(tags) > 0, "No tags returned for 'Imagine'"
    assert all(isinstance(t, str) for t in tags), "Tags should be strings"


@requires_lastfm
def test_lastfm_tags_are_lowercase():
    """Tags are returned in lowercase."""
    from music_teacher_ai.core.lastfm_client import get_tags

    tags = get_tags("Imagine", "John Lennon")
    for tag in tags:
        assert tag == tag.lower(), f"Tag not lowercase: {tag!r}"


@requires_lastfm
def test_lastfm_get_play_count():
    """get_play_count returns a positive integer for a well-known track."""
    from music_teacher_ai.core.lastfm_client import get_play_count

    count = get_play_count("Imagine", "John Lennon")

    assert count is not None, "play count is None"
    assert count > 0, f"play count should be positive, got {count}"


def test_lastfm_get_tags_returns_empty_when_not_configured(monkeypatch):
    """get_tags returns [] gracefully when the key is missing."""
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
