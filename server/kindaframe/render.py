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

from zoneinfo import ZoneInfo

import numpy as np

from . import art, boards, photo
from .art.base import art_area
from .config import Config
from .imaging import grey16
from .imaging.orient import ORIENTS, canvas_size, to_buffer


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
    orient: str = "portrait"


DASHBOARD_MAX_AGE = 300  # seconds: a pre-rendered dashboard older than this is re-rendered on request


class Renderer:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.battery: int | None = None  # last value the Kindle reported (shown by boards)
        self.sources = boards.SourceCache()
        self._html = None
        self._lock = threading.Lock()
        self._cycle = 0
        self._last: str | None = None
        self._rng = random.Random(secrets.randbits(64))
        self._alt = 0

    def reconfigure(self, cfg: Config) -> None:
        with self._lock:
            self.cfg = cfg
            self._cycle = self._alt = 0
            self._last = None

    def _local_now(self) -> datetime:
        return datetime.now(ZoneInfo(self.cfg.timezone))

    def planned_mode(self) -> str | None:
        """The content mode a frame rendered *now* should have, or None when it isn't fixed (alternate)."""
        cfg = self.cfg
        if cfg.mode != "mixed":
            return cfg.mode
        if cfg.mixed.strategy == "schedule":
            t = self._local_now()
            return cfg.mixed.mode_at(t.hour * 60 + t.minute)
        return None

    def _pick_mode(self) -> str:
        planned = self.planned_mode()
        if planned is not None:
            return planned
        with self._lock:  # mixed + alternate: the next mode in the list on every frame
            modes = self.cfg.mixed.modes
            mode = modes[self._alt % len(modes)]
            self._alt += 1
            return mode

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

    def render(self, w: int, h: int, generator: str | None = None, seed: int | None = None,
               orient: str = "portrait", mode: str | None = None) -> Frame:
        """Render a frame for a w x h (portrait) buffer, laid out for the given orientation.

        `mode` forces a content mode (art | photo | dashboard); otherwise the configured one is used
        (for "mixed": the schedule, or the next mode in the alternation). An art override (generator
        or seed) always renders art.
        """
        if orient not in ORIENTS:
            raise ValueError(orient)
        now = datetime.now(timezone.utc)
        cw, ch = canvas_size(w, h, orient)
        if generator or seed is not None:
            mode = "art"
        mode = mode or self._pick_mode()
        if mode == "photo":
            try:
                path, i, total = photo.pick(self.cfg.photo, self.cfg.state_dir, self._rng)
            except photo.NoPhotos as e:
                raise NoContent(str(e)) from e
            img = to_buffer(photo.render(path, cw, ch, self.cfg.photo.fit), orient)
            return Frame(grey16.to_png(img), "photo", f"photo {i + 1}/{total}", None, now, w, h, orient)

        if mode == "dashboard":
            from . import html

            if self._html is None:
                self._html = html.shared()
            tz = ZoneInfo(self.cfg.timezone)
            ctx = boards.BoardContext(now=datetime.now(tz), tz=tz, cache=self.sources, battery=self.battery,
                                      w=cw, h=ch, orient=orient)
            page = boards.render_html(self.cfg.board, self.cfg.boards.get(self.cfg.board, {}), ctx)
            img = grey16.quantize(self._html.render(page, cw, ch), dither=False)  # crisp text: no dithering
            return Frame(grey16.to_png(to_buffer(img, orient)), "dashboard", self.cfg.board, None, now, w, h, orient)

        name = generator or self._next_generator()
        if name not in art.GENERATORS:
            raise KeyError(name)
        seed = secrets.randbits(31) if seed is None else seed
        aw, ah = art_area(cw, ch)
        piece = art.GENERATORS[name](np.random.default_rng(seed), aw, ah)
        img = to_buffer(art.compose(piece, cw, ch, seed, name), orient)
        return Frame(grey16.to_png(img), "art", name, seed, now, w, h, orient)


class FrameCache:
    """One prepared frame per screen size; refilled in the background after each hit."""

    def __init__(self, renderer: Renderer):
        self.renderer = renderer
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prerender")
        self._ready: dict[tuple[int, int, str], Future[Frame]] = {}
        self._lock = threading.Lock()
        self.last: Frame | None = None

    def _prepare(self, w: int, h: int, orient: str) -> None:
        with self._lock:
            self._ready[(w, h, orient)] = self._pool.submit(self.renderer.render, w, h, None, None, orient)

    def get(self, w: int, h: int, orient: str = "portrait") -> Frame:
        with self._lock:
            fut = self._ready.pop((w, h, orient), None)
        frame = None
        if fut is not None:
            try:
                frame = fut.result()
            except Exception:  # a failed background render must not fail the request
                frame = None
        redo_mode = None
        if frame is not None:
            planned = self.renderer.planned_mode()
            age = (datetime.now(timezone.utc) - frame.rendered_at).total_seconds()
            if planned is not None and frame.mode != planned:
                frame, redo_mode = None, planned  # the schedule moved on (e.g. 21:00 dashboard -> art)
            elif frame.mode == "dashboard" and age > DASHBOARD_MAX_AGE:
                frame, redo_mode = None, "dashboard"  # stale date/weather: render a fresh one now
        if frame is None:
            frame = self.renderer.render(w, h, orient=orient, mode=redo_mode)  # may raise NoContent
        self.last = frame
        self._prepare(w, h, orient)
        return frame

    def clear(self) -> None:
        """Drop prepared frames (after a settings change)."""
        with self._lock:
            self._ready.clear()

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
