"""HTML -> PNG with headless Chromium (Playwright), for dashboard boards (SPEC.md D4).

Playwright's sync API is not thread-safe, but frames are rendered from both the request threads
(cold path) and the pre-render thread. So one dedicated thread owns the browser and everything
else hands it jobs. The browser stays warm between renders; a crashed browser is relaunched once.

Pages are rendered offline: every network request from the page is aborted. Templates are
self-contained (inline CSS and SVG), and calendar/RSS text is untrusted, so a template must
never be able to fetch anything.
"""

from __future__ import annotations

import io
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

log = logging.getLogger(__name__)

CHROMIUM_ARGS = [
    "--no-sandbox",  # the container drops all capabilities; content is our own offline templates
    "--disable-dev-shm-usage",  # Docker's 64 MB /dev/shm is too small for Chromium
    "--disable-gpu",
    "--font-render-hinting=none",
    "--disable-lcd-text",  # greyscale antialiasing only: no colour fringes to quantize
]


class HtmlRenderer:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="chromium")
        self._pw = None
        self._browser = None
        self._lock = threading.Lock()

    # -- runs on the chromium thread only ------------------------------------------------
    def _ensure_browser(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(args=CHROMIUM_ARGS)
        return self._browser

    def _render(self, html: str, w: int, h: int) -> bytes:
        for attempt in (1, 2):
            try:
                browser = self._ensure_browser()
                ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1,
                                          java_script_enabled=False)
                try:
                    page = ctx.new_page()
                    page.route("**/*", lambda route: route.abort()
                               if not route.request.url.startswith(("data:", "about:")) else route.continue_())
                    page.set_content(html, wait_until="load", timeout=10_000)
                    return page.screenshot(type="png", full_page=False, timeout=10_000)
                finally:
                    ctx.close()
            except Exception:
                if attempt == 2:
                    raise
                log.exception("chromium render failed; relaunching browser")
                self._browser = None

    # -- any thread ------------------------------------------------------------------------
    def render(self, html: str, w: int, h: int) -> Image.Image:
        """Screenshot `html` at exactly w x h CSS pixels (1:1 device pixels). Returns an 'L' image."""
        png = self._pool.submit(self._render, html, w, h).result(timeout=60)
        return Image.open(io.BytesIO(png)).convert("L")


_shared: HtmlRenderer | None = None
_shared_lock = threading.Lock()


def shared() -> HtmlRenderer:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = HtmlRenderer()
        return _shared
