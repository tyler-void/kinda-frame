"""Dashboard boards (spec FR-017, FR-017a; data-model "Board").

A board is a module with:
  NAME       registry key, e.g. "daily"
  TEMPLATE   file name of its Jinja2 template, in the board's own folder
  build(settings, ctx) -> dict   the template context

Data sources go through `ctx.source(name, ttl, fetch)`: results are cached for `ttl` seconds and
any exception becomes `Section(ok=False, error=...)` so the template shows "unavailable" for that
part and the frame still renders. A stale-but-cached value is preferred over an error.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 5.0  # per source request (seconds)
MAX_BODY = 5 * 1024 * 1024


@dataclass(frozen=True)
class Section:
    ok: bool
    data: Any = None
    error: str | None = None
    stale: bool = False  # served from cache after a failed refresh


class SourceCache:
    """Process-wide cache shared by all renders (pre-render thread and request threads)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float, fetch: Callable[[], Any]) -> Section:
        now = self._clock()
        with self._lock:
            hit = self._entries.get(key)
        if hit and now - hit[0] < ttl:
            return Section(True, hit[1])
        try:
            data = fetch()
        except Exception as e:  # noqa: BLE001 - any source failure must stay contained
            log.warning("source %s failed: %s", key, e)
            if hit:
                return Section(True, hit[1], error=str(e), stale=True)
            return Section(False, error=_short(e))
        with self._lock:
            self._entries[key] = (now, data)
        return Section(True, data)


def _short(e: Exception) -> str:
    msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
    return msg[:120]


@dataclass
class BoardContext:
    now: datetime  # timezone-aware, in the configured zone
    tz: ZoneInfo
    cache: SourceCache
    battery: int | None
    w: int
    h: int
    orient: str
    http: Callable[[str], bytes] | None = None  # injectable for tests

    def source(self, key: str, ttl: float, fetch: Callable[[], Any]) -> Section:
        return self.cache.get(key, ttl, fetch)

    def get(self, url: str) -> bytes:
        if self.http is not None:
            return self.http(url)
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": "kinda-frame/0.1 (home dashboard)"}) as c:
            r = c.get(url)
            r.raise_for_status()
            if len(r.content) > MAX_BODY:
                raise ValueError("response too large")
            return r.content
