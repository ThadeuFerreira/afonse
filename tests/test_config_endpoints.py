"""
Tests for config endpoints in:
  - REST API  (music_teacher_ai/api/rest_api.py)
  - MCP server (music_teacher_ai/api/mcp_server.py)

No real .env file is written; credentials module is patched throughout.
"""
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

VALID_TOKEN = "a" * 64
MASKED_STATUS = [
    {"key": "GENIUS_ACCESS_TOKEN", "label": "Genius Access Token",
     "required": True, "set": False, "masked_value": "(not set)"},
]


@pytest.fixture()
def mock_credentials():
    """Patch all credential functions used by both REST and MCP."""
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN) as mock_verify,
        patch("music_teacher_ai.config.credentials.current_status",
              return_value=MASKED_STATUS) as mock_status,
        patch("music_teacher_ai.config.credentials.update_env") as mock_update,
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN", "SPOTIFY_CLIENT_ID",
                         "SPOTIFY_CLIENT_SECRET", "LASTFM_API_KEY",
                         "DATABASE_PATH", "API_CACHE_DIR"})),
    ):
        yield {
            "verify": mock_verify,
            "status": mock_status,
            "update": mock_update,
        }


# ---------------------------------------------------------------------------
# REST API tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def rest_client(mock_credentials):
    from fastapi.testclient import TestClient
    # TestClient reports "testclient" as client host, so add it to the
    # allowed localhost set so POST /config passes the origin check.
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN),
        patch("music_teacher_ai.config.credentials.current_status",
              return_value=MASKED_STATUS),
        patch("music_teacher_ai.config.credentials.update_env"),
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN", "SPOTIFY_CLIENT_ID",
                         "SPOTIFY_CLIENT_SECRET", "LASTFM_API_KEY",
                         "DATABASE_PATH", "API_CACHE_DIR"})),
        patch("music_teacher_ai.api.rest_api._LOCALHOST",
              {"127.0.0.1", "::1", "localhost", "testclient"}),
    ):
        from music_teacher_ai.api.rest_api import app
        yield TestClient(app)


def test_rest_get_config_no_auth(rest_client):
    resp = rest_client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["key"] == "GENIUS_ACCESS_TOKEN"


def test_rest_post_config_valid(rest_client):
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN),
        patch("music_teacher_ai.config.credentials.current_status",
              return_value=MASKED_STATUS),
        patch("music_teacher_ai.config.credentials.update_env"),
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN", "SPOTIFY_CLIENT_ID",
                         "SPOTIFY_CLIENT_SECRET", "LASTFM_API_KEY",
                         "DATABASE_PATH", "API_CACHE_DIR"})),
    ):
        resp = rest_client.post(
            "/config",
            json={"credentials": {"GENIUS_ACCESS_TOKEN": "newtoken"}},
            headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        )
    # localhost is the default test client host — should succeed
    assert resp.status_code == 200
    data = resp.json()
    assert "updated" in data
    assert "GENIUS_ACCESS_TOKEN" in data["updated"]


def test_rest_post_config_wrong_token(rest_client):
    resp = rest_client.post(
        "/config",
        json={"credentials": {"GENIUS_ACCESS_TOKEN": "x"}},
        headers={"Authorization": "Bearer wrongtoken"},
    )
    assert resp.status_code == 401


def test_rest_post_config_unknown_key(rest_client):
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN),
        patch("music_teacher_ai.config.credentials.current_status",
              return_value=MASKED_STATUS),
        patch("music_teacher_ai.config.credentials.update_env"),
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN", "SPOTIFY_CLIENT_ID",
                         "SPOTIFY_CLIENT_SECRET", "LASTFM_API_KEY",
                         "DATABASE_PATH", "API_CACHE_DIR"})),
    ):
        resp = rest_client.post(
            "/config",
            json={"credentials": {"UNKNOWN_KEY": "value"}},
            headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        )
    assert resp.status_code == 400
    assert "UNKNOWN_KEY" in resp.json()["detail"]


def test_rest_post_config_empty_credentials(rest_client):
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN),
        patch("music_teacher_ai.config.credentials.update_env"),
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN"})),
    ):
        resp = rest_client.post(
            "/config",
            json={"credentials": {}},
            headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        )
    assert resp.status_code == 400


def test_rest_post_config_non_localhost():
    """Requests from a non-localhost IP must be rejected with 403."""
    from fastapi.testclient import TestClient

    from music_teacher_ai.api.rest_api import app

    # base_url with a non-localhost host simulates remote client
    client = TestClient(app, base_url="http://10.0.0.1")
    resp = client.post(
        "/config",
        json={"credentials": {"GENIUS_ACCESS_TOKEN": "x"}},
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# MCP server dispatch() tests
# ---------------------------------------------------------------------------

def test_mcp_get_config():
    with patch("music_teacher_ai.config.credentials.current_status",
               return_value=MASKED_STATUS):
        from music_teacher_ai.api.mcp_server import dispatch
        result = dispatch("get_config", {})
    assert isinstance(result, list)
    assert result[0]["key"] == "GENIUS_ACCESS_TOKEN"


def test_mcp_configure_valid():
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN),
        patch("music_teacher_ai.config.credentials.current_status",
              return_value=MASKED_STATUS),
        patch("music_teacher_ai.config.credentials.update_env"),
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN", "SPOTIFY_CLIENT_ID",
                         "SPOTIFY_CLIENT_SECRET", "LASTFM_API_KEY",
                         "DATABASE_PATH", "API_CACHE_DIR"})),
    ):
        from music_teacher_ai.api.mcp_server import dispatch
        result = dispatch("configure", {
            "admin_token": VALID_TOKEN,
            "credentials": {"GENIUS_ACCESS_TOKEN": "newvalue"},
        })
    assert "updated" in result
    assert "GENIUS_ACCESS_TOKEN" in result["updated"]
    assert "status" in result


def test_mcp_configure_wrong_token():
    with patch("music_teacher_ai.config.credentials.verify_admin_token",
               side_effect=lambda t: t == VALID_TOKEN):
        from music_teacher_ai.api.mcp_server import dispatch
        result = dispatch("configure", {
            "admin_token": "wrongtoken",
            "credentials": {"GENIUS_ACCESS_TOKEN": "x"},
        })
    assert "error" in result
    assert "admin_token" in result["error"].lower()


def test_mcp_configure_empty_credentials():
    with patch("music_teacher_ai.config.credentials.verify_admin_token",
               side_effect=lambda t: t == VALID_TOKEN):
        from music_teacher_ai.api.mcp_server import dispatch
        result = dispatch("configure", {
            "admin_token": VALID_TOKEN,
            "credentials": {},
        })
    assert "error" in result


def test_mcp_configure_unknown_key():
    with (
        patch("music_teacher_ai.config.credentials.verify_admin_token",
              side_effect=lambda t: t == VALID_TOKEN),
        patch("music_teacher_ai.config.credentials.ALLOWED_KEYS",
              frozenset({"GENIUS_ACCESS_TOKEN"})),
    ):
        from music_teacher_ai.api.mcp_server import dispatch
        result = dispatch("configure", {
            "admin_token": VALID_TOKEN,
            "credentials": {"UNKNOWN_KEY": "v"},
        })
    assert "error" in result
    assert "UNKNOWN_KEY" in result["error"]


def test_mcp_unknown_tool():
    from music_teacher_ai.api.mcp_server import dispatch
    result = dispatch("nonexistent_tool", {})
    assert "error" in result


# ---------------------------------------------------------------------------
# MCP TOOLS list completeness
# ---------------------------------------------------------------------------

def test_mcp_tools_list_contains_config_tools():
    from music_teacher_ai.api.mcp_server import TOOLS
    names = {t["name"] for t in TOOLS}
    assert "get_config" in names
    assert "configure" in names


def test_mcp_configure_tool_requires_admin_token():
    from music_teacher_ai.api.mcp_server import TOOLS
    configure = next(t for t in TOOLS if t["name"] == "configure")
    required = configure["input_schema"].get("required", [])
    assert "admin_token" in required
    assert "credentials" in required
