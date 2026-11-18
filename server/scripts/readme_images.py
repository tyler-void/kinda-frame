"""Regenerate the README images in docs/img/ (run from server/: `uv run python scripts/readme_images.py`).

Everything is rendered by the real code, offline, with example data only (Berlin, a fake calendar):
  kindle-mockup.png    SVG mock-up of a generic e-reader: portrait art + landscape dashboard on a stand
  art-generators.png   the four art generators, two seeds each
  dashboard.png        the daily board, portrait and landscape side by side
  settings-page.png    screenshot of the LAN settings page
Needs Playwright's Chromium (`uv run playwright install chromium`).
"""

from __future__ import annotations

import base64
import io
import json
import socket
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import uvicorn
from PIL import Image

from kindaframe import art, boards
from kindaframe.art.base import art_area
from kindaframe.boards.base import BoardContext, SourceCache
from kindaframe.boards.daily import board as daily
from kindaframe.html import HtmlRenderer
from kindaframe.imaging import grey16
from kindaframe.settings_store import ConfigStore

OUT = Path(__file__).resolve().parents[2] / "docs" / "img"
W, H = 1072, 1448
TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 18, 8, 5, tzinfo=TZ)
EXAMPLE = {"location_label": "Berlin (example)", "latitude": 52.52, "longitude": 13.40, "units": "metric",
           "calendars": ["https://calendar.example.com/ical/demo/basic.ics"]}


# ----------------------------------------------------------------------------- example data
def weather_json(now: datetime) -> dict:
    day0 = now.date()
    hours = [datetime.combine(day0, datetime.min.time()) + timedelta(hours=i) for i in range(48)]
    temps = [3 + 5 * np.sin((i - 9) / 24 * 2 * np.pi) for i in range(48)]
    codes = [3, 3, 3, 3, 3, 3, 2, 2, 1, 1, 1, 2, 2, 3, 61, 61, 63, 61, 3, 3, 3, 3, 3, 3] * 2
    return {
        "current": {"temperature_2m": 4.2, "apparent_temperature": 1.6, "weather_code": 2},
        "hourly": {"time": [t.strftime("%Y-%m-%dT%H:%M") for t in hours], "temperature_2m": temps,
                   "precipitation_probability": [min(90, max(0, (i % 24 - 11) * 12)) for i in range(48)],
                   "weather_code": codes},
        "daily": {"time": [str(day0), str(day0 + timedelta(days=1))], "weather_code": [61, 71],
                  "temperature_2m_max": [7.8, 3.1], "temperature_2m_min": [1.4, -1.2],
                  "precipitation_probability_max": [70, 40],
                  "sunrise": [f"{day0}T07:31", f"{day0 + timedelta(days=1)}T07:33"],
                  "sunset": [f"{day0}T16:12", f"{day0 + timedelta(days=1)}T16:11"]},
    }


ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//kinda-frame//readme//EN
BEGIN:VEVENT
UID:a
DTSTART;VALUE=DATE:20261118
DTEND;VALUE=DATE:20261119
SUMMARY:Bin day
END:VEVENT
BEGIN:VEVENT
UID:b
DTSTART;TZID=Europe/Berlin:20261118T091500
DTEND;TZID=Europe/Berlin:20261118T093000
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
SUMMARY:Stand-up
END:VEVENT
BEGIN:VEVENT
UID:c
DTSTART;TZID=Europe/Berlin:20261118T123000
DTEND;TZID=Europe/Berlin:20261118T133000
SUMMARY:Lunch with Sam
LOCATION:Markthalle Neun
END:VEVENT
BEGIN:VEVENT
UID:d
DTSTART;TZID=Europe/Berlin:20261118T180000
DTEND;TZID=Europe/Berlin:20261118T190000
SUMMARY:Climbing
END:VEVENT
BEGIN:VEVENT
UID:e
DTSTART;TZID=Europe/Berlin:20261119T190000
DTEND;TZID=Europe/Berlin:20261119T213000
SUMMARY:Board games night
END:VEVENT
END:VCALENDAR
"""


def fake_http(url: str) -> bytes:
    if url.startswith(daily.OPEN_METEO):
        return json.dumps(weather_json(NOW)).encode()
    return ICS


# ----------------------------------------------------------------------------- renders
def art_piece(name: str, seed: int, w: int = W, h: int = H) -> Image.Image:
    aw, ah = art_area(w, h)
    return art.compose(art.GENERATORS[name](np.random.default_rng(seed), aw, ah), w, h, seed, name)


def dashboard(html: HtmlRenderer, w: int, h: int) -> Image.Image:
    ctx = BoardContext(now=NOW, tz=TZ, cache=SourceCache(), battery=82, w=w, h=h,
                       orient="portrait" if w < h else "left", http=fake_http)
    page = boards.render_html("daily", EXAMPLE, ctx)
    return grey16.quantize(html.render(page, w, h), dither=False)


def data_uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def shot_html(html: HtmlRenderer, page: str, w: int, h: int) -> Image.Image:
    """Screenshot arbitrary HTML/SVG in colour (not quantized): for the mock-up."""
    png = html._pool.submit(html._render, page, w, h).result(timeout=60)
    return Image.open(io.BytesIO(png)).convert("RGB")


# ----------------------------------------------------------------------------- the mock-up
def e_reader(x: float, y: float, screen: Image.Image, scale: float, rotate: int = 0) -> str:
    """A generic e-reader (flush black front, wider bottom bezel) drawn upright, then rotated."""
    sw, sh = W * scale, H * scale
    side, top, bottom = 34 * scale / 0.42, 40 * scale / 0.42, 74 * scale / 0.42
    dw, dh = sw + 2 * side, sh + top + bottom
    cx, cy = dw / 2, dh / 2
    return f"""
  <g transform="translate({x} {y}) rotate({rotate} {cx} {cy})">
    <rect x="6" y="14" width="{dw}" height="{dh}" rx="{30 * scale / 0.42}" fill="#000" opacity="0.18" filter="url(#blur)"/>
    <rect width="{dw}" height="{dh}" rx="{30 * scale / 0.42}" fill="url(#body)"/>
    <rect x="1.5" y="1.5" width="{dw - 3}" height="{dh - 3}" rx="{29 * scale / 0.42}" fill="none" stroke="#3a3a3e" stroke-width="2"/>
    <rect x="{side - 3}" y="{top - 3}" width="{sw + 6}" height="{sh + 6}" fill="#0b0b0c"/>
    <image x="{side}" y="{top}" width="{sw}" height="{sh}" href="{data_uri(screen)}" style="image-rendering:auto"/>
    <rect x="{side}" y="{top}" width="{sw}" height="{sh}" fill="#e9e6dc" style="mix-blend-mode:multiply"/>
  </g>"""


def mockup(html: HtmlRenderer) -> Image.Image:
    # Device at scale 0.42: screen 450 x 608, bezels 34 / 40 / 74 -> 518 x 722 upright.
    # Rotated -90 about its centre (259, 361): bottom edge at y + 361 + 259 = y + 620.
    portrait_art = art_piece("attractor", 2)
    land = dashboard(html, H, W).transpose(Image.Transpose.ROTATE_270)  # as the Kindle buffer holds it
    s = 0.42
    W_SCENE, H_SCENE = 1600, 980
    y_portrait = H_SCENE - 120 - 722 - 4  # standing on the floor line
    y_land = H_SCENE - 150 - 620  # rotated bottom edge = top of the stand
    svg = f"""<!doctype html><html><body style="margin:0">
<svg xmlns="http://www.w3.org/2000/svg" width="{W_SCENE}" height="{H_SCENE}" viewBox="0 0 {W_SCENE} {H_SCENE}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f4f1ea"/><stop offset="1" stop-color="#e4dfd3"/></linearGradient>
    <linearGradient id="body" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2b2b2f"/><stop offset="1" stop-color="#151517"/></linearGradient>
    <linearGradient id="wood" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c9a27a"/><stop offset="1" stop-color="#a77f58"/></linearGradient>
    <filter id="blur" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="14"/></filter>
  </defs>
  <rect width="100%" height="100%" fill="url(#bg)"/>
  <rect y="{H_SCENE - 120}" width="100%" height="120" fill="#d8d1c2"/>
  {e_reader(90, y_portrait, portrait_art, s)}
  <rect x="640" y="{H_SCENE - 150}" width="900" height="34" rx="6" fill="url(#wood)"/>
  {e_reader(831, y_land, land, s, rotate=-90)}
  <text x="{W_SCENE - 40}" y="{H_SCENE - 40}" text-anchor="end" font-family="DejaVu Sans, sans-serif" font-size="22" fill="#6b6559">portrait: generative art · landscape on its left edge: daily dashboard</text>
</svg></body></html>"""
    return shot_html(html, svg, W_SCENE, H_SCENE)


# ----------------------------------------------------------------------------- settings page
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def settings_page(html: HtmlRenderer) -> Image.Image:
    from kindaframe.app import create_app

    BoardContext.get = lambda self, url: fake_http(url)  # offline previews
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "config.toml"
        base.write_text(f"""mode = "mixed"
timezone = "Europe/Berlin"
[mixed]
strategy = "schedule"
schedule = [{{ from = "06:30", mode = "dashboard" }}, {{ from = "21:00", mode = "art" }}]
[boards.daily]
location_label = "{EXAMPLE['location_label']}"
latitude = 52.52
longitude = 13.40
calendars = ["{EXAMPLE['calendars'][0]}"]
""")
        app = create_app(store=ConfigStore(base, Path(tmp) / "state"))
        port = free_port()
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        while not server.started:
            time.sleep(0.05)
        import urllib.request

        urllib.request.urlopen(f"http://127.0.0.1:{port}/frame.png?w={W}&h={H}&batt=82&orient=left").read()

        def capture() -> bytes:  # runs on the renderer's own Chromium thread, reusing its browser
            ctx = html._ensure_browser().new_context(viewport={"width": 860, "height": 900}, device_scale_factor=1,
                                                     java_script_enabled=True)
            try:
                pg = ctx.new_page()
                pg.goto(f"http://127.0.0.1:{port}/settings", wait_until="networkidle")
                # Viewport = whole page, so the sticky Save bar sits at the bottom instead of mid-page.
                pg.set_viewport_size({"width": 860, "height": pg.evaluate("document.documentElement.scrollHeight")})
                pg.wait_for_timeout(300)
                return pg.screenshot()
            finally:
                ctx.close()

        png = html._pool.submit(capture).result(timeout=120)
        server.should_exit = True
        t.join(timeout=5)
    return Image.open(io.BytesIO(png)).convert("RGB")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    html = HtmlRenderer()

    mockup(html).save(OUT / "kindle-mockup.png", optimize=True)
    print("kindle-mockup.png")

    tw, th = 268, 362
    picks = [("chladni", 3), ("flowfield", 11), ("attractor", 4), ("orbits", 1),
             ("chladni", 8), ("flowfield", 2), ("attractor", 2), ("orbits", 6)]
    sheet = Image.new("L", (tw * 4 + 50, th * 2 + 30), 200)
    for i, (name, seed) in enumerate(picks):
        sheet.paste(art_piece(name, seed).resize((tw, th), Image.Resampling.LANCZOS),
                    (10 + (i % 4) * (tw + 10), 10 + (i // 4) * (th + 10)))
    sheet.save(OUT / "art-generators.png", optimize=True)
    print("art-generators.png")

    p = dashboard(html, W, H).resize((W // 2, H // 2), Image.Resampling.LANCZOS)
    land = dashboard(html, H, W).resize((H // 2, W // 2), Image.Resampling.LANCZOS)
    dash = Image.new("L", (p.width + land.width + 30, p.height + 20), 200)
    dash.paste(p, (10, 10))
    dash.paste(land, (p.width + 20, 10 + (p.height - land.height) // 2))
    dash.save(OUT / "dashboard.png", optimize=True)
    print("dashboard.png")

    settings_page(html).save(OUT / "settings-page.png", optimize=True)
    print("settings-page.png")


if __name__ == "__main__":
    main()
