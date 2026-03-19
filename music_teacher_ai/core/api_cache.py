"""
Disk-based cache for external API responses.

Successful responses (including "not found" None) are written as JSON to
API_CACHE_DIR (default: data/api_cache/).  On subsequent calls with the same
arguments the cached value is returned without hitting the network.

Exceptions are never cached — a failed request will be retried next time.
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


def cached_api(
    namespace: str,
    from_cache: Optional[Callable[[Any], Any]] = None,
    serialize: Optional[Callable[[Any], Any]] = None,
) -> Callable:
    """
    Decorator that persists successful API responses to disk as JSON.

    Args:
        namespace: Groups cache files by service (e.g. ``"spotify"``).
        from_cache: Callable that reconstructs the Python object from the
            stored JSON value.  Leave ``None`` for primitives and collections
            (``str``, ``int``, ``list[str]``, …) which round-trip through JSON
            unchanged.  For a single dataclass pass ``lambda d: MyClass(**d)``;
            for a list of dataclasses pass
            ``lambda data: [MyClass(**d) for d in data]``.
        serialize: Callable that converts the return value to a JSON-compatible
            object before writing.  Required when returning a list of dataclasses
            (e.g. ``lambda r: [dataclasses.asdict(e) for e in r]``).
            Single dataclasses are handled automatically without this argument.
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
