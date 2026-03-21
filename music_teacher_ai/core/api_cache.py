"""
Disk-based cache for external API responses.

Successful responses are written as JSON to API_CACHE_DIR (default:
data/api_cache/).  On subsequent calls with the same arguments the cached
value is returned without hitting the network.

Exceptions are never cached — a failed request will be retried next time.
By default None results are also NOT cached (use cache_none=True to opt in).
"""
import dataclasses
import hashlib
import json
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

from music_teacher_ai.config.settings import API_CACHE_DIR


def _make_key(namespace: str, fn_name: str, args: tuple, kwargs: dict) -> str:
    raw = json.dumps([namespace, fn_name, list(args), kwargs], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _cache_path(key: str) -> Path:
    # Two-character prefix to avoid giant flat directories.
    return API_CACHE_DIR / key[:2] / f"{key}.json"


def cache_stats(namespace: str | None = None) -> dict:
    """Return counts of cached entries per namespace (total and None results)."""
    stats: dict[str, dict[str, int]] = {}
    root = API_CACHE_DIR
    if not root.exists():
        return stats
    for path in root.rglob("*.json"):
        ns = path.parent.parent.name  # …/genius/ab/abc123.json → "genius"
        if namespace and ns != namespace:
            continue
        entry = stats.setdefault(ns, {"total": 0, "null_results": 0})
        entry["total"] += 1
        try:
            with path.open() as f:
                if json.load(f).get("result") is None:
                    entry["null_results"] += 1
        except Exception:
            pass
    return stats


def clear_cache(namespace: str | None = None) -> int:
    """Delete cache files for *namespace* (or all namespaces). Returns file count."""
    root = API_CACHE_DIR
    if not root.exists():
        return 0
    deleted = 0
    for path in list(root.rglob("*.json")):
        ns = path.parent.parent.name
        if namespace and ns != namespace:
            continue
        path.unlink(missing_ok=True)
        deleted += 1
    return deleted


def clear_null_cache(namespace: str | None = None) -> int:
    """Delete only cache entries that stored a None result. Returns file count."""
    root = API_CACHE_DIR
    if not root.exists():
        return 0
    deleted = 0
    for path in list(root.rglob("*.json")):
        ns = path.parent.parent.name
        if namespace and ns != namespace:
            continue
        try:
            with path.open() as f:
                if json.load(f).get("result") is None:
                    path.unlink(missing_ok=True)
                    deleted += 1
        except Exception:
            pass
    return deleted


def cached_api(
    namespace: str,
    from_cache: Optional[Callable[[Any], Any]] = None,
    serialize: Optional[Callable[[Any], Any]] = None,
    cache_none: bool = False,
) -> Callable:
    """
    Decorator that persists successful API responses to disk as JSON.

    Args:
        namespace:   Groups cache files by service (e.g. ``"spotify"``).
        from_cache:  Callable that reconstructs the Python object from the
                     stored JSON value.  Leave ``None`` for primitives and
                     collections that round-trip through JSON unchanged.
        serialize:   Callable that converts the return value to a JSON-
                     compatible object before writing.
        cache_none:  If True, cache None ("not found") responses so they are
                     not re-queried.  Default False — None is not cached so a
                     retry with valid credentials will actually hit the API.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = _make_key(namespace, fn.__name__, args, kwargs)
            path = _cache_path(key)

            if path.exists():
                with path.open() as f:
                    envelope = json.load(f)
                raw = envelope["result"]
                if raw is None:
                    return None
                return from_cache(raw) if from_cache else raw

            result = fn(*args, **kwargs)

            # Only persist to disk when there is something worth caching.
            if result is not None or cache_none:
                if serialize is not None:
                    stored = serialize(result)
                elif result is not None and dataclasses.is_dataclass(result):
                    stored = dataclasses.asdict(result)
                else:
                    stored = result

                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w") as f:
                    json.dump({"result": stored}, f)

            return result

        return wrapper
    return decorator
