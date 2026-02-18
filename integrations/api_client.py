"""Base HTTP client with retry, rate-limiting, and caching."""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".api_cache"


@dataclass
class RateLimiter:
    """Token-bucket rate limiter."""

    calls_per_second: float = 2.0
    _last_call: float = field(default=0.0, repr=False)

    def wait(self) -> None:
        now = time.monotonic()
        min_interval = 1.0 / self.calls_per_second
        elapsed = now - self._last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call = time.monotonic()


class APIClient:
    """Lightweight HTTP client built on ``urllib`` (no external deps).

    Features:
    * Automatic retries with exponential back-off
    * Per-host rate limiting
    * Optional on-disk response cache
    * JSON and raw-text response parsing
    """

    def __init__(
        self,
        base_url: str = "",
        headers: Optional[dict[str, str]] = None,
        rate_limit: float = 2.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout: int = 30,
        cache_ttl: int = 3600,
        name: str = "APIClient",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.headers.setdefault("User-Agent", "PE-Agent/1.0")
        self.headers.setdefault("Accept", "application/json")
        self._limiter = RateLimiter(calls_per_second=rate_limit)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._timeout = timeout
        self._cache_ttl = cache_ttl
        self._name = name

    # -- caching --------------------------------------------------------------

    def _cache_key(self, url: str, params: dict | None) -> str:
        raw = url + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cached(self, key: str) -> Optional[dict]:
        path = _CACHE_DIR / f"{key}.json"
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                entry = json.load(fh)
            if time.time() - entry.get("ts", 0) > self._cache_ttl:
                path.unlink(missing_ok=True)
                return None
            return entry.get("data")
        except (json.JSONDecodeError, OSError):
            return None

    def _set_cached(self, key: str, data: Any) -> None:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _CACHE_DIR / f"{key}.json"
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"ts": time.time(), "data": data}, fh, ensure_ascii=False)
        except OSError:
            pass

    # -- HTTP -----------------------------------------------------------------

    def get(
        self,
        path: str = "",
        params: Optional[dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}" if path else self.base_url
        if params:
            url = f"{url}?{urllib.parse.urlencode(params, doseq=True)}"

        if use_cache:
            key = self._cache_key(url, params)
            cached = self._get_cached(key)
            if cached is not None:
                logger.debug("%s: cache hit for %s", self._name, url)
                return cached

        last_exc: Optional[Exception] = None
        for attempt in range(1, self._max_retries + 1):
            self._limiter.wait()
            req = urllib.request.Request(url, headers=self.headers)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = resp.read().decode("utf-8")
                    content_type = resp.headers.get("Content-Type", "")
                    data = json.loads(body) if "json" in content_type else body
                    if use_cache:
                        self._set_cached(key, data)
                    logger.debug("%s: %s -> %d", self._name, url, resp.status)
                    return data
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                last_exc = exc
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "%s: attempt %d/%d failed for %s: %s – retrying in %.1fs",
                    self._name, attempt, self._max_retries, url, exc, wait,
                )
                time.sleep(wait)

        logger.error("%s: all %d attempts failed for %s", self._name, self._max_retries, url)
        raise ConnectionError(
            f"{self._name}: failed to fetch {url} after {self._max_retries} retries"
        ) from last_exc

    def get_safe(
        self,
        path: str = "",
        params: Optional[dict[str, Any]] = None,
        use_cache: bool = True,
        default: Any = None,
    ) -> Any:
        """Like ``get()`` but returns *default* on failure instead of raising."""
        try:
            return self.get(path, params, use_cache)
        except Exception as exc:
            logger.warning("%s: get_safe swallowed error: %s", self._name, exc)
            return default
