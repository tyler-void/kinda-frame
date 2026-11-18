"""Frame production with background pre-rendering (contracts/frame-api.md "Server obligations").

A request normally takes a frame that was rendered *after the previous request*, so the Kindle
gets an answer in milliseconds even though a render takes ~0.2–0.6 s. Right after serving, the
next frame for that screen size is rendered in the background. Debug overrides (art=, seed=)
bypass the cache.
"""

from __future__ import annotations

import random
import secrets
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

from . import art, photo
from .art.base import art_area
from .config import Config
from .imaging import grey16


class NoContent(RuntimeError):
    """Nothing can be rendered (e.g. photo mode with an empty folder) -> HTTP 503."""


@dataclass(frozen=True)
class Frame:
    png: bytes
    mode: str
    source: str  # generator name, or "photo 3/42" (no file names: they may be private)
    seed: int | None
    rendered_at: datetime
    w: int
    h: int


class Renderer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._cycle = 0
        self._last: str | None = None
        self._rng = random.Random(secrets.randbits(64))

    def _next_generator(self) -> str:
        gens = self.cfg.art.generators
        with self._lock:
            if self.cfg.art.order == "cycle":
                name = gens[self._cycle % len(gens)]
                self._cycle += 1
                return name
            # Random, but never the same generator twice in a row (variety from sleep to sleep).
            pool = [g for g in gens if g != self._last] or list(gens)
            self._last = self._rng.choice(pool)
            return self._last

    def render(self, w: int, h: int, generator: str | None = None, seed: int | None = None) -> Frame:
        now = datetime.now(timezone.utc)
        if self.cfg.mode == "photo":
            try:
                path, i, total = photo.pick(self.cfg.photo, self.cfg.state_dir, self._rng)
            except photo.NoPhotos as e:
                raise NoContent(str(e)) from e
            img = photo.render(path, w, h, self.cfg.photo.fit)
            return Frame(grey16.to_png(img), "photo", f"photo {i + 1}/{total}", None, now, w, h)

        name = generator or self._next_generator()
        if name not in art.GENERATORS:
            raise KeyError(name)
        seed = secrets.randbits(31) if seed is None else seed
        aw, ah = art_area(w, h)
        piece = art.GENERATORS[name](np.random.default_rng(seed), aw, ah)
        img = art.compose(piece, w, h, seed, name)
        return Frame(grey16.to_png(img), "art", name, seed, now, w, h)


class FrameCache:
    """One prepared frame per screen size; refilled in the background after each hit."""

    def __init__(self, renderer: Renderer):
        self.renderer = renderer
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prerender")
        self._ready: dict[tuple[int, int], Future[Frame]] = {}
        self._lock = threading.Lock()
        self.last: Frame | None = None

    def _prepare(self, w: int, h: int) -> None:
        with self._lock:
            self._ready[(w, h)] = self._pool.submit(self.renderer.render, w, h)

    def get(self, w: int, h: int) -> Frame:
        with self._lock:
            fut = self._ready.pop((w, h), None)
        frame = None
        if fut is not None:
            try:
                frame = fut.result()
            except Exception:  # a failed background render must not fail the request
                frame = None
        if frame is None:
            frame = self.renderer.render(w, h)  # may raise NoContent
        self.last = frame
        self._prepare(w, h)
        return frame

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
