"""
Credential management for Music Teacher AI.

Reads and writes the .env file in the project root.  The ADMIN_TOKEN value
is auto-generated on first use and stored in .env; it is required for the
REST and MCP config endpoints so that arbitrary callers cannot overwrite
credentials remotely.
"""
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_PATH = BASE_DIR / ".env"

# ---------------------------------------------------------------------------
# Field registry
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    secret: bool = True
    required: bool = False
    help: str = ""


FIELDS: list[ConfigField] = [
    ConfigField(
        key="GENIUS_ACCESS_TOKEN",
        label="Genius Access Token",
        secret=True,
        required=True,
        help="https://genius.com/api-clients",
    ),
    ConfigField(
        key="SPOTIFY_CLIENT_ID",
        label="Spotify Client ID",
        secret=False,
        required=False,
        help="https://developer.spotify.com/dashboard (optional — full metadata + audio features)",
    ),
    ConfigField(
        key="SPOTIFY_CLIENT_SECRET",
        label="Spotify Client Secret",
        secret=True,
        required=False,
    ),
    ConfigField(
        key="LASTFM_API_KEY",
        label="Last.fm API Key",
        secret=True,
        required=False,
        help="https://www.last.fm/api/account/create (optional — genre tags and play counts)",
    ),
    ConfigField(
        key="DATABASE_PATH",
        label="Database path",
        secret=False,
        required=False,
        help="Default: data/music.db",
    ),
    ConfigField(
        key="API_CACHE_DIR",
        label="API cache directory",
        secret=False,
        required=False,
        help="Default: data/api_cache",
    ),
]

# Lookup by key for fast access
FIELD_MAP: dict[str, ConfigField] = {f.key: f for f in FIELDS}

# Keys callers are allowed to set via REST / MCP (excludes internal settings)
ALLOWED_KEYS: frozenset[str] = frozenset(f.key for f in FIELDS)


# ---------------------------------------------------------------------------
# .env helpers
# ---------------------------------------------------------------------------

def read_env() -> dict[str, str]:
    """Return the current .env values as a plain dict (empty strings for unset keys)."""
    if not ENV_PATH.exists():
        return {}
    return {k: v or "" for k, v in dotenv_values(ENV_PATH).items()}


def update_env(updates: dict[str, str]) -> None:
    """
    Write *updates* into the .env file, preserving existing lines and comments.
    Keys not present in the file are appended at the end.
    Values are always written unquoted (dotenv handles them correctly either way).
    """
    lines: list[str] = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    remaining = dict(updates)

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                new_lines.append(f"{key}={remaining.pop(key)}")
                continue
        new_lines.append(line)

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(new_lines).rstrip() + "\n")


# ---------------------------------------------------------------------------
# Admin token
# ---------------------------------------------------------------------------

def get_admin_token() -> str:
    """
    Return the ADMIN_TOKEN from .env.  If not set, generate a secure random
    token, persist it, and return it.  The token is a 64-character hex string.
    """
    env = read_env()
    token = env.get("ADMIN_TOKEN", "").strip()
    if not token:
        token = secrets.token_hex(32)
        update_env({"ADMIN_TOKEN": token})
    return token


def verify_admin_token(token: str) -> bool:
    """Constant-time comparison to prevent timing attacks."""
    return secrets.compare_digest(token, get_admin_token())


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def mask(value: str) -> str:
    """Show the first 4 characters and replace the rest with ****."""
    if not value:
        return "(not set)"
    if len(value) <= 4:
        return "****"
    return value[:4] + "****"


def current_status() -> list[dict]:
    """
    Return a list of dicts describing each credential field and whether it is
    set.  Values are always masked — safe to log or return via API.
    """
    env = read_env()
    rows = []
    for field in FIELDS:
        value = env.get(field.key, "")
        rows.append({
            "key": field.key,
            "label": field.label,
            "required": field.required,
            "set": bool(value),
            "masked_value": mask(value) if field.secret else (value or "(not set)"),
        })
    return rows
